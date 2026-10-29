"""Rule 5: guests see nothing internal. Never weaken or skip.

Every route under /g is called automatically (taken from the router, so new
routes are covered without touching this file) after internal content exists:
backroom messages, a pulled message, an agent result and an open draft.
"""

import json

from fastapi.routing import APIRoute

from ..conftest import channels, drain

SECRET = "BACKROOM-SECRET-91c2"
FORBIDDEN_KEYS = {
    "pulled", "pulled_from", "from_draft", "draft", "draft_id", "drafts", "work_results", "work_result",
    "memory", "memory_marks", "agent", "agent_id", "agents", "backroom", "backroom_id", "backroom_for_id",
    "role_label", "label", "tone", "sources", "permission", "staged_by_id", "audit",
}


def walk(value, path="$"):
    if isinstance(value, dict):
        for k, v in value.items():
            assert k not in FORBIDDEN_KEYS, f"internal field {k!r} at {path}"
            yield from walk(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk(v, f"{path}[{i}]")
    else:
        yield path, value


def check(payload) -> None:
    for path, v in walk(payload):
        if isinstance(v, str):
            assert SECRET not in v, f"backroom content at {path}"
            assert "QuoteAgent" not in v and "Quote agent" not in v, f"agent at {path}"
            assert v != "agent", f"agent author at {path}"


def make_internal_content(client, lena, sarah):
    ch = channels(lena)
    shared, backroom = ch["Hollmann Bau"]["id"], ch["Hollmann Bau"]["backroom_id"]
    first = lena.get(f"/api/channels/{shared}/messages").json()[0]
    lena.post(f"/api/messages/{first['id']}/pull", json={"note": f"{SECRET} @QuoteAgent price this"})
    drain(client)
    lena.post(f"/api/channels/{backroom}/messages", json={"body": f"Internal only {SECRET}"})
    drain(client)
    work = [w for m in lena.get(f"/api/channels/{backroom}/messages").json() for w in m["work_results"]]
    assert work, "the agent should have produced a quote"
    assert lena.post(f"/api/work-results/{work[0]['id']}/stage").status_code == 200
    sarah.post("/g/api/messages", json={"body": "Thanks!"})
    return shared, backroom


def guest_routes(app):
    """Every HTTP route under /g. The guest router is the only one allowed to define /g paths."""
    from atrium.guest import routes

    found = [r for r in routes.router.routes if isinstance(r, APIRoute)]
    assert all(r.path.startswith("/g/api/") for r in found)
    for router in _other_routers():
        assert not [r for r in router.routes if getattr(r, "path", "").startswith("/g/api")], "guest paths outside the guest router"
    return found


def _other_routers():
    from atrium.api import admin, auth, channels, work

    return [admin.router, auth.router, auth.me_router, channels.router, work.router]


def test_guest_routes_use_guest_schemas_only(app):
    for r in guest_routes(app):
        if r.response_model is not None:
            model = getattr(r.response_model, "__args__", (r.response_model,))[0]
            assert model.__module__ == "atrium.guest.schemas", f"{r.path} answers with {model.__module__}"


def test_no_guest_route_leaks_internal_content(client, app, lena, sarah, seeded):
    make_internal_content(client, lena, sarah)
    token = seeded["links"]["Sarah Hollmann"].rsplit("/", 1)[-1]
    bodies = {
        "/g/api/join-info": {"token": token},
        "/g/api/session": {"token": token, "name": ""},
        "/g/api/messages": {"body": "hello"},
    }
    called = 0
    for r in guest_routes(app):
        if "{" in r.path:
            continue  # file download is checked below
        for method in r.methods - {"HEAD"}:
            res = sarah._req(method, r.path, json=bodies.get(r.path)) if method != "GET" else sarah.get(r.path)
            if r.path == "/g/api/files":
                continue
            assert res.status_code < 500, (r.path, res.text)
            if res.headers.get("content-type", "").startswith("application/json"):
                check(res.json())
            called += 1
    assert called >= 5

    # Files: the draft PDF and backroom files are not downloadable as a guest.
    drafts = lena.get("/api/drafts").json()
    for d in drafts:
        for a in d["attachments"]:
            assert sarah.get(f"/g/api/files/{a['id']}").status_code == 404


def test_guest_socket_gets_only_guest_events(client, lena, sarah):
    with sarah.ws("/g/ws") as ws:
        shared, backroom = make_internal_content(client, lena, sarah)
        lena.post(f"/api/channels/{shared}/messages", json={"body": "Hi Sarah, it's on its way."})
        drain(client)
        events = []
        # Sarah's own message and Lena's reply, nothing else.
        for _ in range(2):
            events.append(ws.receive_json())
    texts = json.dumps(events)
    assert SECRET not in texts
    for e in events:
        assert e["type"] == "message.created"
        check(e)


def test_preview_is_the_guest_api_and_read_only(client, lena, sarah):
    shared = channels(lena)["Hollmann Bau"]
    detail = lena.get(f"/api/channels/{shared['id']}").json()
    sarah_id = next(g["id"] for g in detail["guests"] if g["name"] == "Sarah Hollmann")
    make_internal_content(client, lena, sarah)
    token = lena.post(f"/api/guests/{sarah_id}/preview").json()["token"]
    client.cookies.clear()
    msgs = client.get("/g/api/messages", headers={"Authorization": f"Preview {token}"})
    assert msgs.status_code == 200
    check(msgs.json())
    me = client.get("/g/api/me", headers={"Authorization": f"Preview {token}"}).json()
    assert me["preview"] is True
    blocked = client.post("/g/api/messages", json={"body": "x"},
                          headers={"Authorization": f"Preview {token}", "X-Requested-With": "atrium"})
    assert blocked.status_code == 403

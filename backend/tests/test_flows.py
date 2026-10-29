"""The flows from the mockup, end to end through the API, with the scripted LLM."""

from sqlalchemy import select

from atrium.llm.base import LLMResponse, ToolCall
from atrium.models import AuditEvent

from .conftest import channels, db_call, drain, guest, login


def audit_actions(client) -> list[str]:
    async def q(s):
        return list((await s.execute(select(AuditEvent.action).order_by(AuditEvent.at))).scalars())

    return db_call(client, q)


def setup_quote(client, lena):
    ch = channels(lena)
    shared = ch["Hollmann Bau"]
    msgs = lena.get(f"/api/channels/{shared['id']}/messages").json()
    request = next(m for m in msgs if "40 loads" in m["body"])
    copy = lena.post(f"/api/messages/{request['id']}/pull").json()
    lena.post(f"/api/channels/{shared['backroom_id']}/messages",
              json={"body": "@QuoteAgent please price this: 40 loads a month, routes from 2026 plus Erfurt, prices 2026 plus 3 %."})
    drain(client)
    back = lena.get(f"/api/channels/{shared['backroom_id']}/messages").json()
    work = next(w for m in back for w in m["work_results"] if w["kind"] == "quote")
    return shared, request, copy, work


def test_pull_copies_and_audits_and_is_idempotent(client, lena):
    shared = channels(lena)["Hollmann Bau"]
    msgs = lena.get(f"/api/channels/{shared['id']}/messages").json()
    original = msgs[0]
    copy = lena.post(f"/api/messages/{original['id']}/pull").json()
    assert copy["channel_id"] == shared["backroom_id"]
    assert copy["body"] == original["body"]
    assert copy["author"]["kind"] == "guest"
    assert copy["pulled_from"]["by_name"] == "Lena Kraft"
    again = lena.post(f"/api/messages/{original['id']}/pull").json()
    assert again["id"] == copy["id"]
    marked = lena.get(f"/api/channels/{shared['id']}/messages").json()[0]
    assert marked["pulled"]["copy_id"] == copy["id"]
    assert audit_actions(client).count("message.pulled") == 1


def test_people_outside_the_channel_cannot_pull_or_read(client, lena):
    shared = channels(lena)["Hollmann Bau"]
    mia = login(client, "mia")
    first = lena.get(f"/api/channels/{shared['id']}/messages").json()[0]
    assert mia.post(f"/api/messages/{first['id']}/pull").status_code == 404
    assert mia.get(f"/api/channels/{shared['backroom_id']}/messages").status_code == 404


def test_quote_flow_from_mockup(client, lena, sarah):
    shared, request, copy, work = setup_quote(client, lena)
    assert [l["rate"] for l in work["data"]["lines"]] == [412, 468, 1190]
    assert work["data"]["total_per_month"] == 23488
    assert "4 of the 8" in work["data"]["note"]
    assert work["sources"] == ["Prices from the ERP", "Capacity from dispatch", "Terms from the contract 2026"]
    assert "Can't send anything to customers" in work["permission"]

    # Change a price, the total follows.
    edited = lena.patch(f"/api/work-results/{work['id']}", json={"rates": [412, 468, 1200]}).json()
    assert edited["data"]["total_per_month"] == 23488 + 80

    # Memory: the promise from Sarah's request
    mem = lena.get(f"/api/channels/{shared['backroom_id']}/memory").json()
    promise = next(e for e in mem if e["kind"] == "committed")
    assert promise["source_message_id"] == copy["id"]

    # Take it over: a draft in Lena's composer, with the PDF. Nothing is sent.
    draft = lena.post(f"/api/work-results/{work['id']}/stage").json()
    assert draft["attachments"][0]["filename"].endswith(".pdf")
    assert "€23,568 a month" in draft["attachments"][0]["summary"]
    assert draft["body"].startswith("Hi Sarah")
    assert not any("here's our quote" in m["body"].lower() for m in sarah.get("/g/api/messages").json())
    pdf = lena.get(draft["attachments"][0]["url"])
    assert pdf.content.startswith(b"%PDF")
    assert b"subcontractor" not in pdf.content

    # Tom doesn't see Lena's draft.
    tom = login(client, "tom")
    assert tom.get("/api/drafts").json() == []

    # Lena edits the text a little and sends. The message is hers.
    sent = lena.post(f"/api/channels/{shared['id']}/messages",
                     json={"body": draft["body"] + " Cheers", "draft_id": draft["id"]}).json()
    assert sent["author"]["name"] == "Lena Kraft"
    assert sent["author"]["kind"] == "user"
    assert sent["from_draft"] is True
    assert sent["attachments"][0]["filename"].endswith(".pdf")

    guest_view = sarah.get("/g/api/messages").json()[-1]
    assert guest_view["author"] == {"kind": "staff", "id": sent["author"]["id"], "name": "Lena Kraft", "initials": "LK"}
    assert guest_view["attachments"][0]["filename"].endswith(".pdf")
    assert sarah.get(guest_view["attachments"][0]["url"]).content.startswith(b"%PDF")

    mem = lena.get(f"/api/channels/{shared['backroom_id']}/memory").json()
    assert next(e for e in mem if e["id"] == promise["id"])["status"] == "done"
    back = lena.get(f"/api/channels/{shared['backroom_id']}/messages").json()
    assert next(w for m in back for w in m["work_results"] if w["id"] == work["id"])["status"] == "sent"
    actions = audit_actions(client)
    assert "draft.created" in actions and "draft.sent" in actions and "llm.call" in actions


def test_draft_attachment_can_be_removed_and_draft_discarded(client, lena):
    shared, _, _, work = setup_quote(client, lena)
    draft = lena.post(f"/api/work-results/{work['id']}/stage").json()
    att = draft["attachments"][0]["id"]
    after = lena.delete(f"/api/drafts/{draft['id']}/attachments/{att}").json()
    assert after["attachments"] == []
    lena.delete(f"/api/drafts/{draft['id']}")
    assert lena.get("/api/drafts").json() == []
    back = lena.get(f"/api/channels/{shared['backroom_id']}/messages").json()
    assert next(w for m in back for w in m["work_results"] if w["id"] == work["id"])["status"] == "internal"


def test_payment_terms_flow(client, lena):
    shared, *_ = setup_quote(client, lena)
    msgs = lena.get(f"/api/channels/{shared['id']}/messages").json()
    question = next(m for m in msgs if "45 day" in m["body"])
    lena.post(f"/api/messages/{question['id']}/pull", json={"note": "@QuoteAgent calculate the payment terms please"})
    drain(client)
    back = lena.get(f"/api/channels/{shared['backroom_id']}/messages").json()
    work = next(w for m in back for w in m["work_results"] if w["kind"] == "payment_terms")
    rows = {r["label"]: r["value"] for r in work["data"]["rows"]}
    assert rows["Customer pays on average"] == "15 days later"
    assert rows["Extra outstanding"] == "about €11,600"
    assert rows["Cost at 6 % interest"] == "about €700 a year"
    assert rows["Share of revenue"] == "about 0.25 %"
    assert "0.3 %" in work["data"]["draft_text"]
    mem = lena.get(f"/api/channels/{shared['backroom_id']}/memory").json()
    open_q = next(e for e in mem if e["kind"] == "open")
    assert open_q["status"] == "active"
    draft = lena.post(f"/api/work-results/{work['id']}/stage").json()
    assert draft["attachments"] == []
    lena.post(f"/api/channels/{shared['id']}/messages", json={"body": draft["body"], "draft_id": draft["id"]})
    mem = lena.get(f"/api/channels/{shared['backroom_id']}/memory").json()
    assert next(e for e in mem if e["id"] == open_q["id"])["status"] == "done"


def test_interest_rate_comes_from_settings(client, lena):
    lena.patch("/api/admin/settings", json={"interest_rate_pct": 12})
    shared, *_ = setup_quote(client, lena)
    msgs = lena.get(f"/api/channels/{shared['id']}/messages").json()
    question = next(m for m in msgs if "45 day" in m["body"])
    lena.post(f"/api/messages/{question['id']}/pull", json={"note": "@QuoteAgent calculate the payment terms"})
    drain(client)
    back = lena.get(f"/api/channels/{shared['backroom_id']}/messages").json()
    work = next(w for m in back for w in m["work_results"] if w["kind"] == "payment_terms")
    assert any(r["label"] == "Cost at 12 % interest" for r in work["data"]["rows"])


def test_agent_only_gets_tools_from_its_yaml(client, lena, llm):
    """The quote agent may not write memory, even if the model tries."""
    calls = []

    def script(system, turns, tools):
        names = [t.name for t in tools]
        if "create_quote" in names:
            calls.append(names)
            if len([t for t in turns if t.role == "assistant"]) == 0:
                return LLMResponse(text="", tool_calls=[ToolCall("x", "record_memory", {"entries": [
                    {"kind": "decided", "text": "smuggled", "source": "m1"}]})])
            results = [r for t in turns for r in t.tool_results]
            assert results[-1].is_error and "not available" in results[-1].content
            return LLMResponse(text="ok", tool_calls=[])
        return LLMResponse(text="", tool_calls=[])

    llm.script = script
    sales = channels(lena)["sales"]
    lena.post(f"/api/channels/{sales['id']}/messages", json={"body": "@QuoteAgent hi"})
    drain(client)
    assert calls and "record_memory" not in calls[0]
    assert set(calls[0]) == {"erp_prices", "dispatch_capacity", "contract_terms", "create_quote", "calculate_payment_terms"}
    assert lena.get(f"/api/channels/{sales['id']}/memory").json() == []


def test_ask_answers_with_source_or_says_it_does_not_know(client, lena):
    shared = channels(lena)["Hollmann Bau"]
    tom = login(client, "tom")
    tom.post(f"/api/channels/{shared['backroom_id']}/messages",
             json={"body": "Erfurt works. Two carriers from the pool run it Tuesdays and Thursdays."})
    drain(client)
    yes = lena.post("/api/ask", json={"question": "Can we do Erfurt?", "channel_id": shared["backroom_id"]}).json()
    assert yes["known"] and yes["sources"][0]["kind"] == "message"
    no = lena.post("/api/ask", json={"question": "What does Sarah's boss think?", "channel_id": shared["backroom_id"]}).json()
    assert not no["known"] and no["sources"] == []
    assert "don't read the customer channel" in no["answer"]


def test_memory_can_be_edited_and_deleted_by_people(client, lena):
    shared, *_ = setup_quote(client, lena)
    tom = login(client, "tom")
    mem = tom.get(f"/api/channels/{shared['backroom_id']}/memory").json()
    e = mem[0]
    changed = tom.patch(f"/api/memory/{e['id']}", json={"text": "Changed by Tom", "status": "done"}).json()
    assert changed["text"] == "Changed by Tom" and changed["status"] == "done"
    assert tom.delete(f"/api/memory/{e['id']}").status_code == 200
    assert all(x["id"] != e["id"] for x in tom.get(f"/api/channels/{shared['backroom_id']}/memory").json())


def test_guest_invite_join_chat_revoke(client, lena):
    shared = channels(lena)["Hollmann Bau"]
    inv = lena.post(f"/api/channels/{shared['id']}/guests", json={"company": "Hollmann Bau", "name": "Petra"}).json()
    assert "/g/" in inv["link"]
    token = inv["link"].split("/g/")[1].split("#")[0]
    info = client.post("/g/api/join-info", json={"token": token}, headers={"X-Requested-With": "atrium"}).json()
    assert info == {"company_name": "Kessler Logistik", "needs_name": True, "suggested_name": ""}
    client.cookies.clear()
    bad = client.post("/g/api/session", json={"token": token, "name": " "}, headers={"X-Requested-With": "atrium"})
    assert bad.status_code == 400
    petra = guest(client, inv["link"], "Petra Lang")
    ch = petra.get("/g/api/channel").json()
    assert ch["notice"] == ("Only people from Kessler Logistik write here. Messages are stored on their server in Frankfurt. "
                            "Kessler Logistik may work on single messages internally with AI.")
    assert any(m["name"] == "Petra Lang" for m in ch["members"])
    assert petra.post("/g/api/messages", json={"body": "Hello!"}).status_code == 200
    # Same link on a second device: same guest, name kept.
    again = guest(client, inv["link"], "Someone Else")
    assert again.get("/g/api/me").json()["name"] == "Petra Lang"
    lena.delete(f"/api/guests/{inv['guest']['id']}")
    assert petra.get("/g/api/messages").status_code == 401
    client.cookies.clear()
    gone = client.post("/g/api/session", json={"token": token, "name": "x"}, headers={"X-Requested-With": "atrium"})
    assert gone.status_code == 401
    assert {"guest.invited", "guest.joined", "guest.revoked"} <= set(audit_actions(client))


def test_guest_cannot_reach_internal_api(client, sarah):
    assert sarah.get("/api/channels").status_code == 401
    assert sarah.get("/api/me").status_code == 401


def test_live_chat_between_lena_and_sarah(client, lena, sarah):
    shared = channels(lena)["Hollmann Bau"]
    with lena.ws("/ws") as lw, sarah.ws("/g/ws") as sw:
        lw.receive_json()
        sarah.post("/g/api/messages", json={"body": "Are you there?"})
        while True:
            e = lw.receive_json()
            if e["type"] == "message.created":
                break
        assert e["message"]["body"] == "Are you there?"
        assert sw.receive_json()["message"]["body"] == "Are you there?"
        lena.post(f"/api/channels/{shared['id']}/messages", json={"body": "Yes!"})
        assert sw.receive_json()["message"]["author"]["kind"] == "staff"


def test_admin_export_and_delete_guest(client, lena, sarah):
    sarah.post("/g/api/messages", json={"body": "My personal note"})
    shared = channels(lena)["Hollmann Bau"]
    first = next(m for m in lena.get(f"/api/channels/{shared['id']}/messages").json() if m["author"]["name"] == "Sarah Hollmann")
    lena.post(f"/api/messages/{first['id']}/pull")
    gid = next(g["id"] for g in lena.get("/api/admin/guests").json() if g["name"] == "Sarah Hollmann")
    export = lena.get(f"/api/admin/guests/{gid}/export").json()
    assert any(m["body"] == "My personal note" for m in export["messages"])
    assert any(m["copy_in_backroom"] for m in export["messages"])
    assert lena.delete(f"/api/admin/guests/{gid}").json()["messages"] >= 3
    bodies = [m["body"] for m in lena.get(f"/api/channels/{shared['id']}/messages").json()]
    assert "My personal note" not in bodies
    assert all(m["author"]["kind"] != "guest" for m in lena.get(f"/api/channels/{shared['backroom_id']}/messages").json())
    assert sarah.get("/g/api/messages").status_code == 401


def test_non_admin_cannot_use_admin_api(client):
    tom = login(client, "tom")
    assert tom.get("/api/admin/audit").status_code == 403


def test_csrf_header_required(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "lena@kessler.example", "password": "x"})
    assert r.status_code == 403


def test_room_notes_summary_lands_in_room_channel(client, lena, llm):
    rooms = lena.get("/api/rooms").json()
    dispatch = next(r for r in rooms if r["name"] == "Dispatch")
    with lena.ws("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "room.join", "room_id": dispatch["id"]})
        ws.send_bytes(b"This is said while notes are off.")
        ws.send_json({"type": "room.notes", "on": True})
        ws.send_bytes(b"We take the Thursday tours with two pool carriers.")
        ws.send_json({"type": "room.notes", "on": False})
        ws.send_json({"type": "ping"})
        while ws.receive_json()["type"] != "pong":
            pass
    drain(client)
    payload = "\n".join(str(c) for c in llm.calls)
    assert "Thursday tours" in payload
    assert "while notes are off" not in payload
    msgs = lena.get(f"/api/channels/{dispatch['channel_id']}/messages").json()
    last = msgs[-1]
    assert last["author"]["kind"] == "agent"
    assert last["body"].startswith("Notes from Dispatch, switched on by Lena Kraft")


def test_edit_and_delete_own_messages(client, lena, sarah):
    shared = channels(lena)["Hollmann Bau"]
    mine = lena.post(f"/api/channels/{shared['id']}/messages", json={"body": "Typo hree"}).json()
    with sarah.ws("/g/ws") as ws:
        edited = lena.patch(f"/api/messages/{mine['id']}", json={"body": "Typo here"}).json()
        assert edited["body"] == "Typo here" and edited["edited_at"]
        e = ws.receive_json()
        assert e["type"] == "message.updated" and e["message"]["body"] == "Typo here" and e["message"]["edited_at"]
        assert lena.delete(f"/api/messages/{mine['id']}").status_code == 200
        e = ws.receive_json()
        assert e == {"type": "message.deleted", "message": None, "message_id": mine["id"], "members": None}
    # Not someone else's
    first = lena.get(f"/api/channels/{shared['id']}/messages").json()[0]
    assert lena.patch(f"/api/messages/{first['id']}", json={"body": "x"}).status_code == 403
    assert lena.delete(f"/api/messages/{first['id']}").status_code == 403
    assert sarah.patch(f"/g/api/messages/{first['id']}", json={"body": "Changed by Sarah"}).status_code == 200


def test_guest_deleting_takes_the_backroom_copy_along(client, lena, sarah):
    shared = channels(lena)["Hollmann Bau"]
    m = sarah.post("/g/api/messages", json={"body": "Please forget this"}).json()
    copy = lena.post(f"/api/messages/{m['id']}/pull").json()
    assert sarah.delete(f"/g/api/messages/{m['id']}").json() == {"ok": True}
    back = lena.get(f"/api/channels/{shared['backroom_id']}/messages").json()
    assert all(x["id"] != copy["id"] for x in back)
    assert "message.deleted" in audit_actions(client)


def test_backroom_copy_cannot_be_edited_and_agent_messages_can_be_removed(client, lena):
    shared, request, copy, work = setup_quote(client, lena)
    assert lena.patch(f"/api/messages/{copy['id']}", json={"body": "rewritten"}).status_code == 403
    assert lena.delete(f"/api/messages/{work['message_id']}").status_code == 200

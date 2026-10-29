"""Admins shape the floor plan to their company. Presence stays in memory throughout."""

from .conftest import channels, login


def plan(who):
    return who.get("/api/rooms").json()


def test_seed_plan_has_one_floor_and_a_hallway(client, lena):
    p = plan(lena)
    assert [f["name"] for f in p["floors"]] == ["Dortmund office"]
    assert sum(r["kind"] == "hallway" for r in p["rooms"]) == 1


def test_admin_adds_a_floor_and_a_members_only_room(client, lena):
    p = lena.put("/api/admin/floors", json={"floors": [{"id": "main", "name": "Dortmund office", "columns": 2},
                                                        {"name": "Erfurt depot", "columns": 3}]}).json()
    erfurt = next(f for f in p["floors"] if f["name"] == "Erfurt depot")
    assert erfurt["id"] == "erfurt-depot"
    admin_channels = lena.get("/api/admin/channels").json()
    wh = next(c for c in admin_channels if c["name"] == "warehouse")
    r = lena.post("/api/admin/rooms", json={"name": "Loading bay", "floor_id": erfurt["id"], "col": 0, "row": 0, "col_span": 3,
                                            "channel_id": wh["id"], "members_only": True})
    assert r.status_code == 200, r.text
    bay = next(x for x in r.json()["rooms"] if x["name"] == "Loading bay")
    assert bay["can_enter"] is False  # Lena isn't in #warehouse
    kai = login(client, "kai")
    assert next(x for x in plan(kai)["rooms"] if x["name"] == "Loading bay")["can_enter"] is True

    with lena.ws("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "room.join", "room_id": bay["id"]})
        while (e := ws.receive_json())["type"] != "error":
            pass
        assert e["detail"] == "Only members of this room's channel can go in"
        assert client.app.state.atrium.presence.where == {}
    with kai.ws("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "room.join", "room_id": bay["id"]})
        while (e := ws.receive_json())["type"] != "room.voice":
            pass
        assert client.app.state.atrium.presence.room_of(next(iter(client.app.state.atrium.presence.where))).name == "Loading bay"


def test_plan_rules_are_checked(client, lena):
    rooms = plan(lena)["rooms"]
    dispatch = next(r for r in rooms if r["name"] == "Dispatch")
    shared = channels(lena)["Hollmann Bau"]
    base = {"name": "Cube", "floor_id": "main", "col": 0, "row": 0}
    assert "overlaps Dispatch" in lena.post("/api/admin/rooms", json=base).json()["detail"]
    assert "doesn't fit" in lena.post("/api/admin/rooms", json=base | {"row": 5, "col": 1, "col_span": 2}).json()["detail"]
    assert "already a hallway" in lena.post("/api/admin/rooms", json=base | {"row": 5, "kind": "hallway"}).json()["detail"]
    assert "never to a customer channel" in lena.post("/api/admin/rooms", json=base | {"row": 5, "channel_id": shared["id"]}).json()["detail"]
    assert "floor" in lena.post("/api/admin/rooms", json=base | {"row": 5, "floor_id": "nope"}).json()["detail"]
    # Shrinking the floor below a room is refused.
    assert "wouldn't fit" in lena.put("/api/admin/floors", json={"floors": [{"id": "main", "name": "Office", "columns": 1}]}).json()["detail"]
    assert dispatch["col_span"] == 2


def test_deleting_a_room_moves_people_out_and_ends_notes(client, lena, llm):
    rooms = plan(lena)["rooms"]
    sales = next(r for r in rooms if r["name"] == "Sales corner")
    with lena.ws("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "room.join", "room_id": sales["id"]})
        ws.send_json({"type": "room.notes", "on": True})
        ws.send_bytes(b"Mia takes the Brandt call.")
        ws.send_json({"type": "ping"})
        while ws.receive_json()["type"] != "pong":
            pass
        assert lena.delete(f"/api/admin/rooms/{sales['id']}").status_code == 200
        seen = set()
        while "rooms.updated" not in seen or "presence.state" not in seen:
            seen.add(ws.receive_json()["type"])
    from .conftest import drain

    drain(client)
    assert client.app.state.atrium.presence.where == {}
    assert any("Brandt call" in str(c) for c in llm.calls)  # the notes were summarized, not lost


def test_rooms_without_channel_have_no_notes_and_non_admins_cannot_edit(client, lena):
    tom = login(client, "tom")
    assert tom.post("/api/admin/rooms", json={"name": "x"}).status_code == 403
    r = lena.post("/api/admin/rooms", json={"name": "Kitchen", "floor_id": "main", "col": 0, "row": 3, "col_span": 2}).json()
    kitchen = next(x for x in r["rooms"] if x["name"] == "Kitchen")
    with tom.ws("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "room.join", "room_id": kitchen["id"]})
        ws.send_json({"type": "room.notes", "on": True})
        ws.send_json({"type": "ping"})
        while ws.receive_json()["type"] != "pong":
            pass
        assert client.app.state.atrium.presence.rooms[__import__("uuid").UUID(kitchen["id"])].notes_by_id is None

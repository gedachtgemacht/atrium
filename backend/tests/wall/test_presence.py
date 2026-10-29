"""Rule 6: rooms store no presence. Never weaken or skip.

A full room visit (join, mute, switch rooms, leave, disconnect) must leave the
database exactly as it was, and no log line may tie a person to a room.
"""

import logging

from sqlalchemy import text

from atrium.db import Base

from ..conftest import db_call, drain


def dump(client) -> dict:
    async def q(s):
        out = {}
        for table in Base.metadata.sorted_tables:
            rows = (await s.execute(text(f'SELECT * FROM "{table.name}"'))).all()
            out[table.name] = sorted(str(tuple(r)) for r in rows)
        return out

    return db_call(client, q)


def test_room_visit_leaves_no_trace(client, lena, tom, caplog):
    rooms = lena.get("/api/rooms").json()["rooms"]
    dispatch = next(r for r in rooms if r["name"] == "Dispatch")
    warehouse = next(r for r in rooms if r["name"] == "Warehouse office")
    before = dump(client)
    caplog.set_level(logging.DEBUG)

    with lena.ws("/ws") as a, tom.ws("/ws") as b:
        a.receive_json()
        b.receive_json()
        a.send_json({"type": "room.join", "room_id": dispatch["id"]})
        b.send_json({"type": "room.join", "room_id": dispatch["id"]})
        a.send_json({"type": "room.mute", "muted": True})
        a.send_json({"type": "room.join", "room_id": warehouse["id"]})
        b.send_json({"type": "room.leave"})
        a.send_json({"type": "ping"})
        seen = []
        while True:
            e = a.receive_json()
            seen.append(e)
            if e["type"] == "pong":
                break
        assert any(
            e["type"] == "presence.state" and any(p["people"] for p in e["rooms"]) for e in seen
        ), "presence should be live over the socket"
    drain(client)

    assert dump(client) == before
    me_ids = {lena.get("/api/me").json()["id"], tom.get("/api/me").json()["id"]}
    for rec in caplog.records:
        line = rec.getMessage()
        tied = any(i in line for i in me_ids) or "Lena" in line or "Tom" in line
        room = dispatch["id"] in line or warehouse["id"] in line or "Dispatch" in line or "Warehouse" in line
        assert not (tied and room), f"log ties a person to a room: {line}"
    assert client.app.state.atrium.presence.where == {}

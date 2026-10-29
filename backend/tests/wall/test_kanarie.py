"""Canary test (rule 1). Never weaken, skip or rewrite this test to make something pass.

A unique text goes into the shared channel. Then every agent path runs. The
fake LLM records every payload; the canary must not show up anywhere until a
person pulls the message into the backroom.
"""

import time

from sqlalchemy import select

from atrium.models import LlmCall, Message

from ..conftest import channels, db_call, drain, payloads, uid

CANARY = "KANARIE-7f3a"


def _all_context_ids(client):
    async def q(s):
        rows = (await s.execute(select(LlmCall.context_message_ids))).scalars().all()
        return {i for ids in rows for i in ids}

    return db_call(client, q)


def _run_every_agent_path(client, lena, ch, label):
    backroom = ch["Hollmann Bau"]["backroom_id"]
    sales = ch["sales"]["id"]
    # 1. mention in the backroom
    assert lena.post(f"/api/channels/{backroom}/messages", json={"body": f"@QuoteAgent price it please {label}"}).status_code == 200
    # 2. mention in an ordinary internal channel
    assert lena.post(f"/api/channels/{sales}/messages", json={"body": f"@QuoteAgent anything new? {label}"}).status_code == 200
    # 3. a mention inside the shared channel must not start anything at all
    assert lena.post(f"/api/channels/{ch['Hollmann Bau']['id']}/messages", json={"body": f"@QuoteAgent look at this {label}"}).status_code == 200
    drain(client)  # memory extraction for the backroom runs here (4.)
    # 5. ask the backroom, in the backroom and globally
    assert lena.post("/api/ask", json={"question": "What does Sarah want? Secret plan carrier", "channel_id": backroom}).status_code == 200
    assert lena.post("/api/ask", json={"question": "What is still open?"}).status_code == 200
    assert lena.post("/api/ask", json={"question": "Erfurt?", "channel_id": ch["Hollmann Bau"]["id"]}).status_code == 200
    # 6. room notes
    rooms = lena.get("/api/rooms").json()["rooms"]
    dispatch = next(r for r in rooms if r["name"] == "Dispatch")
    with lena.ws("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "room.join", "room_id": dispatch["id"]})
        ws.send_json({"type": "room.notes", "on": True})
        ws.send_bytes(b"We take the Thursday tours with two pool carriers.")
        ws.send_json({"type": "ping"})
        while ws.receive_json()["type"] != "pong":
            pass
        ws.send_json({"type": "room.notes", "on": False})
        ws.send_json({"type": "ping"})
        while ws.receive_json()["type"] != "pong":
            pass
    time.sleep(0.05)
    drain(client)


def test_canary_never_reaches_an_llm_until_pulled(client, llm, lena, sarah):
    ch = channels(lena)
    shared = ch["Hollmann Bau"]
    r = sarah.post("/g/api/messages", json={"body": f"Secret plan {CANARY}: we also talk to another carrier."})
    assert r.status_code == 200
    canary_id = uid(r.json()["id"])

    _run_every_agent_path(client, lena, ch, "first")

    kinds = {c["tools"][0] if c["tools"] else "none" for c in llm.calls}
    assert {"erp_prices", "record_memory", "answer", "none"} <= kinds, f"not every agent path ran: {kinds}"
    assert CANARY not in payloads(llm)
    assert canary_id not in _all_context_ids(client)

    # Human search may find it: people can read the customer channel.
    hits = lena.get("/api/search", params={"q": CANARY}).json()
    assert any(h["message"]["id"] == str(canary_id) for h in hits)

    # After a person pulls it in, it may show up, but only as the backroom copy.
    pulled = lena.post(f"/api/messages/{canary_id}/pull")
    assert pulled.status_code == 200
    copy_id = uid(pulled.json()["id"])
    before = len(llm.calls)
    lena.post(f"/api/channels/{shared['backroom_id']}/messages", json={"body": "@QuoteAgent and now?"})
    drain(client)
    assert CANARY in payloads(llm.calls[before:])
    ids = _all_context_ids(client)
    assert copy_id in ids
    assert canary_id not in ids


def test_agent_context_rejects_shared_messages(client, lena, sarah):
    """The ContextBuilder itself refuses shared content, even if code hands it over."""
    import pytest

    from atrium.actors import AgentActor
    from atrium.llm.context import ContextBuilder
    from atrium.policy import WallViolation

    ch = channels(lena)
    shared_id = uid(ch["Hollmann Bau"]["id"])
    sarah.post("/g/api/messages", json={"body": CANARY})
    state = client.app.state.atrium

    async def attempt(s):
        msg = (await s.execute(select(Message).where(Message.channel_id == shared_id))).scalars().first()
        agent = AgentActor(agent_id=state.agent_ids["quote-agent"], org_id=await _org(s), name="Quote agent",
                           scope_channel_ids=frozenset({shared_id}))
        with pytest.raises(WallViolation):
            await ContextBuilder(s, agent, "mention").add_messages([msg])

    db_call(client, attempt)


async def _org(s):
    from atrium.models import Organization

    return (await s.execute(select(Organization.id))).scalar_one()

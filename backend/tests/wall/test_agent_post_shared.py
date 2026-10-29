"""Rule 2: only people write in shared channels. Never weaken or skip."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from atrium import policy
from atrium.actors import AgentActor, SystemActor
from atrium.agents import runner
from atrium.models import AuthorKind, Message, Organization
from atrium.services.messages import post_message

from ..conftest import channels, db_call, drain, uid


def test_agent_posting_in_shared_channel_is_403(client, lena):
    shared_id = uid(channels(lena)["Hollmann Bau"]["id"])
    state = client.app.state.atrium

    async def attempt(s):
        org = (await s.execute(select(Organization.id))).scalar_one()
        ch = await policy.get_channel(s, SystemActor(org), shared_id)
        # Even an agent whose scope (wrongly) includes the shared channel is refused.
        agent = AgentActor(agent_id=state.agent_ids["quote-agent"], org_id=org, name="Quote agent",
                           scope_channel_ids=frozenset({shared_id}))
        with pytest.raises(HTTPException) as e:
            await post_message(state, s, agent, ch, "Hello from the agent")
        return e.value.status_code

    assert db_call(client, attempt) == 403


def test_agent_run_aimed_at_shared_channel_reads_and_writes_nothing(client, lena, llm):
    shared_id = uid(channels(lena)["Hollmann Bau"]["id"])
    state = client.app.state.atrium
    cfg = state.agents["quote-agent"]
    me = uid(lena.get("/api/me").json()["id"])

    with pytest.raises(HTTPException) as e:
        client.portal.call(runner.run_mention, state, cfg, shared_id, shared_id, me)
    assert e.value.status_code == 404  # the agent cannot even see that the channel exists
    assert llm.calls == []

    async def agent_messages(s):
        return (await s.execute(select(Message).where(Message.channel_id == shared_id,
                                                      Message.author_kind == AuthorKind.agent))).scalars().all()

    assert db_call(client, agent_messages) == []


def test_mention_in_shared_channel_starts_no_agent(client, lena, llm):
    shared = channels(lena)["Hollmann Bau"]
    r = lena.post(f"/api/channels/{shared['id']}/messages", json={"body": "@QuoteAgent can you answer Sarah?"})
    assert r.status_code == 200
    drain(client)
    assert llm.calls == []

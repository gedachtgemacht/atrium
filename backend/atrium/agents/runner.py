"""Agent runs: the tool calling loop over the provider neutral LLM interface."""

import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import policy
from ..actors import AgentActor
from ..db import utcnow
from ..llm.base import ProviderError, ToolResult
from ..llm.context import BuiltContext, ContextBuilder
from ..models import Agent, AgentRun, Channel, Organization
from .config import AgentConfig
from .tools.registry import TOOLS, ToolEnv, dumps, specs_for

log = logging.getLogger("atrium.agents")
MAX_ROUNDS = 8


async def sync_agents(state, session: AsyncSession) -> None:
    """Make sure every YAML agent has a row (messages need an author id)."""
    org = (await session.execute(select(Organization).limit(1))).scalar_one_or_none()
    if org is None:
        return
    rows = {a.slug: a for a in (await session.execute(select(Agent))).scalars()}
    for cfg in state.agents.values():
        row = rows.get(cfg.slug)
        if row is None:
            row = Agent(org_id=org.id, slug=cfg.slug, handle=cfg.handle, name=cfg.name, initial=cfg.initial)
            session.add(row)
        else:
            row.handle, row.name, row.initial, row.is_active = cfg.handle, cfg.name, cfg.initial, True
    for slug, row in rows.items():
        if slug not in state.agents:
            row.is_active = False
    await session.commit()
    state.agent_ids = {a.slug: a.id for a in (await session.execute(select(Agent))).scalars()}
    state.agent_permissions = {state.agent_ids[c.slug]: c.permission for c in state.agents.values() if c.slug in state.agent_ids}


def system_prompt(cfg: AgentConfig, org: Organization) -> str:
    return cfg.system.format(org=org.name, today=date.today().isoformat())


def actor_for(state, cfg: AgentConfig, org: Organization, scope) -> AgentActor:
    return AgentActor(agent_id=state.agent_ids[cfg.slug], org_id=org.id, name=cfg.name, scope_channel_ids=frozenset(scope))


async def loop(state, ctx: BuiltContext, cfg: AgentConfig, env: ToolEnv, run_id, provider_name=None) -> str:
    """Call the model, run the tools it asks for, repeat. Tools outside the YAML are refused."""
    allowed = set(cfg.tools)
    specs = specs_for(cfg.tools)
    text = ""
    for _ in range(MAX_ROUNDS):
        resp = await state.llm.complete(ctx, specs, run_id=run_id, provider_name=provider_name)
        text = resp.text or text
        if not resp.tool_calls:
            break
        ctx.add_assistant(resp.text, resp.tool_calls)
        results = []
        for call in resp.tool_calls:
            if call.name not in allowed or call.name not in TOOLS:
                results.append(ToolResult(call.id, call.name, f"Tool {call.name} is not available to this agent.", True))
                continue
            try:
                value = await TOOLS[call.name].run(env, call.arguments or {})
                results.append(ToolResult(call.id, call.name, dumps(value)))
            except Exception as e:  # tool errors go back to the model, not to the user
                log.exception("tool %s failed", call.name)
                results.append(ToolResult(call.id, call.name, f"Error: {e}", True))
        ctx.add_tool_results(results)
    return text.strip()


def env_for(state, session, actor, channel, org, labels, run_id) -> ToolEnv:
    return ToolEnv(session=session, agent=actor, channel=channel, org=org, labels=labels, run_id=run_id,
                   erp=state.erp, dispatch=state.dispatch, contracts=state.contracts)


async def _start_run(session, actor: AgentActor, channel_id, trigger, ref, user_id) -> AgentRun:
    run = AgentRun(agent_id=actor.agent_id, channel_id=channel_id, trigger=trigger, trigger_ref=ref, started_by_id=user_id)
    session.add(run)
    await session.commit()
    return run


async def _finish(session, run: AgentRun, status: str, error: str = "") -> None:
    run.status, run.error, run.finished_at = status, error[:2000], utcnow()
    await session.commit()


async def _status(state, session, channel: Channel, cfg: AgentConfig, busy: bool) -> None:
    from ..services.events import to_readers

    await to_readers(state, session, channel, {"type": "agent.status", "slug": cfg.slug, "channel_id": str(channel.id), "busy": busy})


async def run_mention(state, cfg: AgentConfig, channel_id: uuid.UUID, trigger_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """@QuoteAgent in an internal channel or backroom."""
    from ..services.messages import post_message, publish_work_result

    async with state.db.sessions() as session:
        org = (await session.execute(select(Organization).limit(1))).scalar_one()
        actor = actor_for(state, cfg, org, {channel_id})
        channel = await policy.get_channel(session, actor, channel_id)  # 404 for shared channels: rule 1
        run = await _start_run(session, actor, channel_id, "mention", trigger_id, user_id)
        await _status(state, session, channel, cfg, True)
        try:
            history = await policy.channel_messages(session, actor, channel_id, limit=40)
            builder = ContextBuilder(session, actor, "mention").system(system_prompt(cfg, org))
            await builder.add_messages(history, heading="Backroom messages, oldest first:" if channel.kind.value == "backroom" else "Channel messages, oldest first:")
            await builder.add_memory(await policy.channel_memory(session, actor, channel_id))
            trigger = next((m for m in history if m.id == trigger_id), None)
            if trigger is not None:
                builder.add_text("", f"You were mentioned in {builder.label(trigger.id)}. Do what it asks.")
            ctx = builder.build()
            env = env_for(state, session, actor, channel, org, builder.labels, run.id)
            text = await loop(state, ctx, cfg, env, run.id, org.llm_provider)
            msg = await post_message(state, session, actor, channel, text or "Done.")
            # A result answers a customer message. If the model didn't say which, take the latest pulled one.
            latest_pulled = next((m.id for m in reversed(history) if m.pulled_from_id), None)
            for w in env.created:
                w.message_id = msg.id
                if not w.answers_message_ids and latest_pulled:
                    w.answers_message_ids = [latest_pulled]
            await session.commit()
            from ..services.events import publish_message

            await publish_message(state, session, channel, msg, event="message.updated")
            for w in env.created:
                await publish_work_result(state, session, channel, w)
            await _finish(session, run, "done")
        except ProviderError as e:
            await session.rollback()
            await post_message(state, session, actor, channel, "I couldn't reach the language model, so nothing was calculated. Try again in a moment.")
            await _finish(session, run, "failed", str(e))
        except Exception as e:
            await session.rollback()
            log.exception("agent run failed")
            await _finish(session, run, "failed", repr(e))
        finally:
            await _status(state, session, channel, cfg, False)

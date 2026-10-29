"""Memory extraction from backroom messages: decided, open, committed. Each entry keeps its source."""

import logging
import uuid

from sqlalchemy import select

from .. import policy
from ..agents.runner import _finish, _start_run, actor_for, env_for, loop, system_prompt
from ..llm.base import ProviderError
from ..llm.context import ContextBuilder
from ..models import ChannelKind, Organization
from ..services.events import publish_message, to_readers

log = logging.getLogger("atrium.memory")


async def run(state, channel_id: uuid.UUID) -> None:
    cfg = state.agent_with_role("memory")
    if cfg is None:
        return
    async with state.db.sessions() as session:
        org = (await session.execute(select(Organization).limit(1))).scalar_one()
        actor = actor_for(state, cfg, org, {channel_id})
        channel = await policy.get_channel(session, actor, channel_id)
        if channel.kind != ChannelKind.backroom:
            return
        run_row = await _start_run(session, actor, channel_id, "memory", None, None)
        try:
            recent = await policy.channel_messages(session, actor, channel_id, limit=15)
            builder = ContextBuilder(session, actor, "memory").system(system_prompt(cfg, org))
            await builder.add_memory(await policy.channel_memory(session, actor, channel_id), heading="Memory (existing entries):")
            await builder.add_messages(recent, heading="Newest backroom messages, oldest first:")
            builder.add_text("", "Record what is new. Call record_memory exactly once.")
            ctx = builder.build()
            env = env_for(state, session, actor, channel, org, builder.labels, run_row.id)
            await loop(state, ctx, cfg, env, run_row.id, org.llm_provider)
            await session.commit()
            await _finish(session, run_row, "done")
        except ProviderError as e:
            await session.rollback()
            await _finish(session, run_row, "failed", str(e))
            return
        except Exception as e:
            await session.rollback()
            log.exception("memory extraction failed")
            await _finish(session, run_row, "failed", repr(e))
            return
        if env.memory_changed:
            await to_readers(state, session, channel, {"type": "memory.updated", "channel_id": str(channel_id)})
            # Refresh "Remembered as ..." under the source messages.
            for m in recent:
                await publish_message(state, session, channel, m, event="message.updated")

"""Ask the backroom: answers only from backrooms and memory, always with a source."""

import uuid

from sqlalchemy import select

from .. import policy
from ..actors import UserActor
from ..agents.runner import _finish, _start_run, actor_for, env_for, loop, system_prompt
from ..llm.base import ProviderError
from ..llm.context import ContextBuilder
from ..models import Organization
from ..i18n import t
from ..schemas import AskOut, AskSource


async def ask(state, session, user: UserActor, question: str, channel_id: uuid.UUID | None) -> AskOut:
    cfg = state.agent_with_role("ask")
    question = question.strip()[:1000]
    if channel_id is not None:
        ch = await policy.get_channel(session, user, channel_id)
        if ch.kind.value == "shared":
            ch = await policy.backroom_of(session, user, ch)
            if ch is None:
                raise policy.forbidden()
        if ch.kind.value != "backroom":
            raise policy.forbidden("Ask works in backrooms")
        scope = [ch.id]
    else:
        scope = [c.id for c in await policy.all_backrooms(session, user)]
    org = (await session.execute(select(Organization).limit(1))).scalar_one()
    from ..models import User

    me = await session.get(User, user.user_id)
    L = (me.locale if me else "") or org.language
    if cfg is None or not scope:
        return AskOut(question=question, answer=t(L, "ask.dont_know"), known=False, sources=[])

    # The agent may only read what this person may read, and only backrooms.
    actor = actor_for(state, cfg, org, scope)
    run = await _start_run(session, actor, scope[0] if len(scope) == 1 else None, "ask", None, user.user_id)
    builder = ContextBuilder(session, actor, "ask").system(system_prompt(cfg, org, L))
    memory = await policy.memory_in(session, actor, scope)
    await builder.add_memory(memory, heading="Memory entries:")
    if len(scope) == 1:
        recent = await policy.channel_messages(session, actor, scope[0], limit=40)
    else:
        recent = []
        for cid in scope:
            recent += await policy.channel_messages(session, actor, cid, limit=10)
    hits = await policy.search_messages(session, actor, question, channel_ids=scope, limit=10) if question else []
    seen = {m.id for m in recent}
    await builder.add_messages(recent + [h for h in hits if h.id not in seen], heading="Backroom messages:")
    builder.add_text("Question:", question)
    ctx = builder.build()
    env = env_for(state, session, actor, None, org, builder.labels, run.id)
    try:
        await loop(state, ctx, cfg, env, run.id, org.llm_provider)
    except ProviderError as e:
        await _finish(session, run, "failed", str(e))
        return AskOut(question=question, answer=t(L, "ask.no_model"), known=False, sources=[])
    await _finish(session, run, "done")

    result = env.answer or {"text": "", "known": False, "sources": []}
    by_label = builder.labels
    mem_by_id = {str(e.id): e for e in memory}
    msg_channel = {m.id: m.channel_id for m in recent + hits}
    sources: list[AskSource] = []
    for ref in result["sources"]:
        ref = str(ref).strip().strip("[]")
        if ref in by_label and by_label[ref] in msg_channel:
            mid = by_label[ref]
            sources.append(AskSource(kind="message", id=mid, channel_id=msg_channel[mid], label=ref))
        elif ref in mem_by_id:
            e = mem_by_id[ref]
            sources.append(AskSource(kind="memory", id=e.id, channel_id=e.channel_id, label=e.text[:60]))
    # No source, no answer: the backroom never guesses.
    if not result["known"] or not sources or not result["text"].strip():
        return AskOut(question=question, answer=t(L, "ask.dont_know"), known=False, sources=[])
    return AskOut(question=question, answer=result["text"].strip(), known=True, sources=sources)

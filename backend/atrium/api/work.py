import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import policy
from ..actors import UserActor
from ..db import utcnow
from ..deps import current_user, get_session, get_state
from ..memory.ask import ask as ask_backroom
from ..models import (
    AgentRun,
    AuthorKind,
    Draft,
    DraftStatus,
    MemoryKind,
    MemoryStatus,
    Room,
    WorkResult,
    WorkStatus,
)
from ..schemas import AgentOut, AskOut, DraftOut, MemoryOut, RoomsOut, SearchHit, WorkResultOut
from ..serialize import attachment_out, messages_out, user_names, work_result_out
from ..services import messages as svc
from ..services.audit import audit
from ..services.events import to_readers
from ..state import AppState

router = APIRouter(prefix="/api", tags=["work"])


def draft_out(state: AppState, d: Draft) -> DraftOut:
    name = next((c.name for c in state.agents.values() if state.agent_ids.get(c.slug) == d.agent_id), "")
    return DraftOut(id=d.id, channel_id=d.channel_id, work_result_id=d.work_result_id, agent_name=name, body=d.body,
                    status=d.status.value, attachments=[attachment_out(a) for a in d.attachments], created_at=d.created_at)


@router.get("/drafts", response_model=list[DraftOut])
async def my_drafts(channel_id: uuid.UUID | None = None, actor: UserActor = Depends(current_user),
                    session: AsyncSession = Depends(get_session), state: AppState = Depends(get_state)):
    stmt = select(Draft).where(Draft.owner_id == actor.user_id, Draft.status == DraftStatus.open)
    if channel_id:
        stmt = stmt.where(Draft.channel_id == channel_id)
    return [draft_out(state, d) for d in (await session.execute(stmt.order_by(Draft.created_at))).scalars()]


class DraftPatch(BaseModel):
    body: str


@router.patch("/drafts/{draft_id}", response_model=DraftOut)
async def patch_draft(draft_id: uuid.UUID, body: DraftPatch, actor: UserActor = Depends(current_user),
                      session: AsyncSession = Depends(get_session), state: AppState = Depends(get_state)):
    return draft_out(state, await svc.update_draft_body(session, actor, draft_id, body.body))


@router.delete("/drafts/{draft_id}")
async def discard(draft_id: uuid.UUID, actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session),
                  state: AppState = Depends(get_state)):
    await svc.discard_draft(state, session, actor, draft_id)
    return {"ok": True}


@router.delete("/drafts/{draft_id}/attachments/{attachment_id}", response_model=DraftOut)
async def remove_attachment(draft_id: uuid.UUID, attachment_id: uuid.UUID, actor: UserActor = Depends(current_user),
                            session: AsyncSession = Depends(get_session), state: AppState = Depends(get_state)):
    return draft_out(state, await svc.remove_draft_attachment(state, session, actor, draft_id, attachment_id))


@router.post("/work-results/{work_id}/stage", response_model=DraftOut)
async def stage(work_id: uuid.UUID, actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session),
                state: AppState = Depends(get_state)):
    return draft_out(state, await svc.stage_work_result(state, session, actor, work_id))


class RatesIn(BaseModel):
    rates: list[int]


@router.patch("/work-results/{work_id}", response_model=WorkResultOut)
async def edit_rates(work_id: uuid.UUID, body: RatesIn, actor: UserActor = Depends(current_user),
                     session: AsyncSession = Depends(get_session), state: AppState = Depends(get_state)):
    w = await svc.update_quote_rates(state, session, actor, work_id, body.rates)
    return work_result_out(w, await user_names(session, [w.staged_by_id]), state.agent_permissions)


# ---------------------------------------------------------------- memory


def memory_out(e, labels: dict) -> MemoryOut:
    return MemoryOut(id=e.id, channel_id=e.channel_id, kind=e.kind.value, text=e.text, owner_name=e.owner_name,
                     due_label=e.due_label, due_date=e.due_date, source_message_id=e.source_message_id,
                     source_label=labels.get(e.source_message_id, ""), status=e.status.value, done_at=e.done_at,
                     done_note=e.done_note, created_at=e.created_at)


async def source_labels(session, actor, entries) -> dict:
    msgs = await policy.messages_by_ids(session, actor, [e.source_message_id for e in entries if e.source_message_id])
    out = {}
    for m in msgs:
        who = m.author_user.name if m.author_user else (m.author_guest.name if m.author_guest else (m.author_agent.name if m.author_agent else ""))
        out[m.id] = f"{who.split(' ')[0]}, {m.created_at.isoformat()}"
    return out


@router.get("/channels/{channel_id}/memory", response_model=list[MemoryOut])
async def channel_memory(channel_id: uuid.UUID, actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session)):
    ch = await policy.get_channel(session, actor, channel_id)
    entries = await policy.channel_memory(session, actor, ch.id)
    labels = await source_labels(session, actor, entries)
    return [memory_out(e, labels) for e in entries]


class MemoryIn(BaseModel):
    kind: str
    text: str = Field(min_length=1, max_length=500)
    owner_name: str = ""
    due_label: str = ""
    due_date: date | None = None
    source_message_id: uuid.UUID | None = None


class MemoryPatch(BaseModel):
    kind: str | None = None
    text: str | None = Field(default=None, min_length=1, max_length=500)
    owner_name: str | None = None
    due_label: str | None = None
    due_date: date | None = None
    status: str | None = None


@router.post("/channels/{channel_id}/memory", response_model=MemoryOut)
async def add_memory(channel_id: uuid.UUID, body: MemoryIn, actor: UserActor = Depends(current_user),
                     session: AsyncSession = Depends(get_session), state: AppState = Depends(get_state)):
    from ..models import MemoryEntry

    ch = await policy.get_channel(session, actor, channel_id)
    if ch.kind.value == "shared":
        raise HTTPException(400, "Memory lives in the backroom")
    if body.source_message_id:
        src = await policy.get_message(session, actor, body.source_message_id)
        if src.channel_id != ch.id:
            raise HTTPException(400, "Source must be in this channel")
    e = MemoryEntry(channel_id=ch.id, kind=MemoryKind(body.kind), text=body.text.strip(), owner_name=body.owner_name,
                    due_label=body.due_label, due_date=body.due_date, source_message_id=body.source_message_id,
                    created_by_kind=AuthorKind.user, updated_by_id=actor.user_id)
    session.add(e)
    audit(session, actor.org_id, actor, "memory.created", channel_id=ch.id, kind=body.kind)
    await session.commit()
    await to_readers(state, session, ch, {"type": "memory.updated", "channel_id": str(ch.id)})
    return memory_out(e, await source_labels(session, actor, [e]))


@router.patch("/memory/{entry_id}", response_model=MemoryOut)
async def edit_memory(entry_id: uuid.UUID, body: MemoryPatch, actor: UserActor = Depends(current_user),
                      session: AsyncSession = Depends(get_session), state: AppState = Depends(get_state)):
    e = await policy.get_memory(session, actor, entry_id)
    changes = body.model_dump(exclude_unset=True)
    if "kind" in changes:
        e.kind = MemoryKind(changes.pop("kind"))
    if "status" in changes:
        st = MemoryStatus(changes.pop("status"))
        if st != e.status:
            e.status = st
            e.done_at = utcnow() if st == MemoryStatus.done else None
            from ..i18n import t as tr
            from ..models import Organization

            language = (await session.get(Organization, actor.org_id)).language
            e.done_note = tr(language, "mem.marked_done", name=actor.name) if st == MemoryStatus.done else ""
    for k, v in changes.items():
        setattr(e, k, v.strip() if isinstance(v, str) else v)
    e.updated_by_id = actor.user_id
    audit(session, actor.org_id, actor, "memory.edited", subject_id=e.id, fields=list(body.model_dump(exclude_unset=True)))
    await session.commit()
    ch = await policy.get_channel(session, actor, e.channel_id)
    await to_readers(state, session, ch, {"type": "memory.updated", "channel_id": str(ch.id)})
    return memory_out(e, await source_labels(session, actor, [e]))


@router.delete("/memory/{entry_id}")
async def delete_memory(entry_id: uuid.UUID, actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session),
                        state: AppState = Depends(get_state)):
    e = await policy.get_memory(session, actor, entry_id)
    ch = await policy.get_channel(session, actor, e.channel_id)
    await session.delete(e)
    audit(session, actor.org_id, actor, "memory.deleted", subject_id=entry_id, channel_id=ch.id)
    await session.commit()
    await to_readers(state, session, ch, {"type": "memory.updated", "channel_id": str(ch.id)})
    return {"ok": True}


# ---------------------------------------------------------------- ask and search


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    channel_id: uuid.UUID | None = None


@router.post("/ask", response_model=AskOut)
async def ask(body: AskIn, actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session),
              state: AppState = Depends(get_state)):
    return await ask_backroom(state, session, actor, body.question, body.channel_id)


@router.get("/search", response_model=list[SearchHit])
async def search(q: str, actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session),
                 state: AppState = Depends(get_state)):
    """Full text search for people. People may read shared channels; the AI may not (that is /ask)."""
    if not q.strip():
        return []
    hits = await policy.search_messages(session, actor, q.strip(), limit=20)
    channels = {c.id: c for c in await policy.list_channels(session, actor)}
    outs = await messages_out(session, actor, hits, permissions=state.agent_permissions)
    return [SearchHit(message=o, channel_name=channels[o.channel_id].name, channel_kind=channels[o.channel_id].kind.value)
            for o in outs if o.channel_id in channels]


# ---------------------------------------------------------------- agents and rooms


@router.get("/agents", response_model=list[AgentOut])
async def agents(actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session),
                 state: AppState = Depends(get_state)):
    from ..agents.config import agent_description, agent_name
    from ..models import Organization, User

    me = await session.get(User, actor.user_id)
    org = await session.get(Organization, actor.org_id)
    lang = (me.locale if me else "") or org.language
    readable = policy.readable_channel_ids(actor)
    out = []
    for cfg in state.agents.values():
        if cfg.hidden or cfg.slug not in state.agent_ids:
            continue
        aid = state.agent_ids[cfg.slug]
        busy = (await session.execute(
            select(func.count()).select_from(AgentRun).where(AgentRun.agent_id == aid, AgentRun.status == "running",
                                                             AgentRun.channel_id.in_(readable))
        )).scalar_one()
        waiting = (await session.execute(
            select(func.count()).select_from(Draft).where(Draft.agent_id == aid, Draft.owner_id == actor.user_id,
                                                          Draft.status == DraftStatus.open)
        )).scalar_one()
        fresh = (await session.execute(
            select(func.count()).select_from(WorkResult).where(WorkResult.agent_id == aid, WorkResult.status == WorkStatus.internal,
                                                               WorkResult.channel_id.in_(readable))
        )).scalar_one()
        notes_rooms = state.presence.rooms_with_notes() if cfg.role == "notes" and state.presence is not None else []
        out.append(AgentOut(id=aid, slug=cfg.slug, handle=cfg.handle, name=agent_name(cfg, lang), initial=cfg.initial,
                            description=agent_description(cfg, lang), role=cfg.role, busy=bool(busy),
                            drafts_waiting=waiting, results_waiting=fresh, notes_rooms=notes_rooms))
    return out


@router.get("/rooms", response_model=RoomsOut)
async def rooms(actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session)):
    from .rooms_admin import rooms_out

    return await rooms_out(session, actor)

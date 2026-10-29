"""Posting messages, pulling customer messages into the backroom, staging and sending drafts."""

import re
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import files, policy
from ..actors import Actor, AgentActor, GuestActor, SystemActor, UserActor
from ..db import utcnow
from ..models import (
    Attachment,
    AuthorKind,
    Channel,
    ChannelKind,
    Draft,
    DraftStatus,
    MemoryKind,
    MemoryStatus,
    Message,
    Organization,
    Pull,
    User,
    WorkResult,
    WorkStatus,
)
from .audit import audit
from .events import publish_message, to_readers, to_user

MENTION = re.compile(r"(?<![\w@])@([A-Za-z][\w-]{1,59})")
MAX_BODY = 20000


def mentions(body: str) -> list[str]:
    return list(dict.fromkeys(MENTION.findall(body)))


async def post_message(
    state,
    session: AsyncSession,
    actor: Actor,
    channel: Channel,
    body: str,
    *,
    attachment_ids: list[uuid.UUID] | None = None,
    draft_id: uuid.UUID | None = None,
) -> Message:
    policy.assert_can_post(actor, channel)
    body = (body or "").strip()
    if len(body) > MAX_BODY:
        raise HTTPException(400, "Message is too long")
    msg = Message(channel_id=channel.id, body=body)
    if isinstance(actor, UserActor):
        msg.author_kind, msg.author_user_id = AuthorKind.user, actor.user_id
    elif isinstance(actor, GuestActor):
        msg.author_kind, msg.author_guest_id = AuthorKind.guest, actor.guest_id
    elif isinstance(actor, AgentActor):
        msg.author_kind, msg.author_agent_id = AuthorKind.agent, actor.agent_id
    else:
        raise policy.forbidden()
    session.add(msg)
    await session.flush()

    has_files = False
    if attachment_ids:
        has_files = await _claim_uploads(session, actor, msg, attachment_ids)

    draft = None
    if draft_id is not None:
        draft = await _send_draft(state, session, actor, channel, msg, draft_id)
        has_files = has_files or bool(draft.attachments)

    if not body and not has_files:
        raise HTTPException(400, "Message is empty")
    await session.commit()

    await publish_message(state, session, channel, msg)
    if draft is not None:
        await _after_draft_sent(state, session, actor, channel, draft)
    if isinstance(actor, UserActor) and channel.kind != ChannelKind.shared:
        schedule_followups(state, channel, msg, actor)
    return msg


async def _claim_uploads(session, actor, msg: Message, ids) -> bool:
    stmt = select(Attachment).where(
        Attachment.id.in_(list(ids)), Attachment.message_id.is_(None), Attachment.draft_id.is_(None)
    )
    if isinstance(actor, UserActor):
        stmt = stmt.where(Attachment.uploader_user_id == actor.user_id)
    elif isinstance(actor, GuestActor):
        stmt = stmt.where(Attachment.uploader_guest_id == actor.guest_id)
    else:
        return False
    rows = (await session.execute(stmt)).scalars().all()
    for a in rows:
        a.message_id = msg.id
    return bool(rows)


def schedule_followups(state, channel: Channel, msg: Message, actor: UserActor) -> None:
    """Mentions start agents in internal channels; backroom messages feed the memory."""
    from ..agents import runner

    for handle in mentions(msg.body):
        cfg = state.agent_by_handle(handle)
        if cfg is not None and cfg.role == "mention":
            state.tasks.spawn(runner.run_mention(state, cfg, channel.id, msg.id, actor.user_id), name=f"agent:{cfg.slug}")
    if channel.kind == ChannelKind.backroom:
        schedule_memory(state, channel.id)


def schedule_memory(state, channel_id: uuid.UUID) -> None:
    from ..memory import extract

    state.tasks.debounce(f"memory:{channel_id}", state.memory_delay, lambda: extract.run(state, channel_id))


# ---------------------------------------------------------------- pulling


async def pull_message(state, session: AsyncSession, actor: UserActor, message_id: uuid.UUID, note: str = "") -> Message:
    """Rule 3: a person copies one customer message into the backroom. Audited."""
    original, shared, backroom = await policy.assert_can_pull(session, actor, message_id)
    existing = await policy.existing_pull(session, original.id)
    if existing is not None:
        return await policy.get_message(session, actor, existing.copy_id)
    copy = Message(
        channel_id=backroom.id,
        body=original.body,
        author_kind=original.author_kind,
        author_user_id=original.author_user_id,
        author_guest_id=original.author_guest_id,
        pulled_from_id=original.id,
        created_at=utcnow(),
    )
    session.add(copy)
    await session.flush()
    for a in original.attachments:
        session.add(Attachment(
            message_id=copy.id, filename=a.filename, mime=a.mime, size=a.size, sha256=a.sha256,
            storage_key=a.storage_key, summary=a.summary,
        ))
    pull = Pull(original_id=original.id, copy_id=copy.id, pulled_by_id=actor.user_id)
    session.add(pull)
    audit(session, actor.org_id, actor, "message.pulled", subject_id=original.id,
          original_id=original.id, copy_id=copy.id, shared_channel_id=shared.id, backroom_id=backroom.id)
    await session.commit()

    await publish_message(state, session, backroom, copy)
    await publish_message(state, session, shared, original, event="message.updated")
    schedule_memory(state, backroom.id)
    if note.strip():
        await post_message(state, session, actor, backroom, note)
    return copy


# ---------------------------------------------------------------- drafts


async def stage_work_result(state, session: AsyncSession, actor: UserActor, work_id: uuid.UUID) -> Draft:
    """Rule 4: an agent result moves into this person's composer in the shared channel. Nothing is sent."""
    work = await get_work_result(session, actor, work_id)
    backroom = await policy.get_channel(session, actor, work.channel_id)
    shared = await policy.shared_of(session, actor, backroom)
    existing = (
        await session.execute(
            select(Draft).where(Draft.work_result_id == work.id, Draft.owner_id == actor.user_id, Draft.status == DraftStatus.open)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    if work.status == WorkStatus.sent:
        raise HTTPException(409, "Already sent")
    draft = Draft(owner_id=actor.user_id, channel_id=shared.id, work_result_id=work.id, agent_id=work.agent_id,
                  body=work.data.get("draft_text", ""))
    session.add(draft)
    await session.flush()
    if work.kind == "quote":
        from ..pdf import quote_pdf

        org = await session.get(Organization, actor.org_id)
        data = quote_pdf(work.data, org.name, actor.name)
        key, sha = files.store(state.settings.upload_dir, data)
        from ..agents.tools.registry import quote_summary

        session.add(Attachment(
            draft_id=draft.id, filename=work.data.get("pdf_name") or f"{work.title}.pdf", mime="application/pdf",
            size=len(data), sha256=sha, storage_key=key, summary=quote_summary(work.data), uploader_user_id=actor.user_id,
        ))
    work.status = WorkStatus.with_user
    work.staged_by_id = actor.user_id
    audit(session, actor.org_id, actor, "draft.created", subject_id=draft.id, work_result_id=work.id,
          agent_id=work.agent_id, shared_channel_id=shared.id)
    await session.commit()
    await session.refresh(draft, ["attachments"])
    await publish_work_result(state, session, backroom, work)
    await to_user(state, actor.user_id, {"type": "draft.updated", "channel_id": str(shared.id)})
    return draft


async def get_work_result(session: AsyncSession, actor: UserActor, work_id: uuid.UUID) -> WorkResult:
    work = (
        await session.execute(
            select(WorkResult).where(WorkResult.id == work_id, WorkResult.channel_id.in_(policy.readable_channel_ids(actor)))
        )
    ).scalar_one_or_none()
    if work is None:
        raise policy.not_found()
    return work


async def get_draft(session: AsyncSession, actor: UserActor, draft_id: uuid.UUID) -> Draft:
    draft = await session.get(Draft, draft_id)
    if draft is None or draft.owner_id != actor.user_id:
        raise policy.not_found()
    return draft


async def _send_draft(state, session, actor, channel: Channel, msg: Message, draft_id) -> Draft:
    if not isinstance(actor, UserActor) or channel.kind != ChannelKind.shared:
        raise HTTPException(400, "Drafts are sent by people in shared channels")
    draft = await get_draft(session, actor, draft_id)
    if draft.channel_id != channel.id or draft.status != DraftStatus.open:
        raise HTTPException(409, "Draft is not open in this channel")
    for a in list(draft.attachments):
        a.message_id = msg.id
        a.draft_id = None
    msg.from_draft_id = draft.id
    draft.status = DraftStatus.sent
    draft.sent_message_id = msg.id
    draft.sent_at = utcnow()
    work = await session.get(WorkResult, draft.work_result_id) if draft.work_result_id else None
    closed = []
    if work is not None:
        work.status = WorkStatus.sent
        work.sent_at = draft.sent_at
        for e in await policy.memory_answered_by(session, work.id, work.answers_message_ids):
            if e.status == MemoryStatus.active and e.kind in (MemoryKind.open, MemoryKind.committed):
                e.status = MemoryStatus.done
                e.done_at = draft.sent_at
                e.done_note = f"{'Answered' if e.kind == MemoryKind.open else 'Done'}, sent by {actor.name}"
                e.updated_by_id = actor.user_id
                closed.append(str(e.id))
    audit(session, actor.org_id, actor, "draft.sent", subject_id=draft.id, message_id=msg.id,
          work_result_id=draft.work_result_id, edited=(msg.body != draft.body), memory_closed=closed)
    return draft


async def _after_draft_sent(state, session, actor: UserActor, shared: Channel, draft: Draft) -> None:
    await to_user(state, actor.user_id, {"type": "draft.updated", "channel_id": str(shared.id)})
    if draft.work_result_id:
        work = await session.get(WorkResult, draft.work_result_id)
        backroom = await policy.get_channel(session, SystemActor(actor.org_id), work.channel_id)
        await publish_work_result(state, session, backroom, work)
        await to_readers(state, session, backroom, {"type": "memory.updated", "channel_id": str(backroom.id)})


async def discard_draft(state, session: AsyncSession, actor: UserActor, draft_id: uuid.UUID) -> None:
    draft = await get_draft(session, actor, draft_id)
    if draft.status != DraftStatus.open:
        return
    draft.status = DraftStatus.discarded
    for a in list(draft.attachments):
        await delete_attachment(state, session, a)
    work = await session.get(WorkResult, draft.work_result_id) if draft.work_result_id else None
    if work is not None and work.status == WorkStatus.with_user:
        work.status = WorkStatus.internal
        work.staged_by_id = None
    audit(session, actor.org_id, actor, "draft.discarded", subject_id=draft.id, work_result_id=draft.work_result_id)
    await session.commit()
    await to_user(state, actor.user_id, {"type": "draft.updated", "channel_id": str(draft.channel_id)})
    if work is not None:
        backroom = await policy.get_channel(session, actor, work.channel_id)
        await publish_work_result(state, session, backroom, work)


async def remove_draft_attachment(state, session, actor: UserActor, draft_id, attachment_id) -> Draft:
    draft = await get_draft(session, actor, draft_id)
    if draft.status != DraftStatus.open:
        raise HTTPException(409, "Draft is not open")
    for a in list(draft.attachments):
        if a.id == attachment_id:
            await delete_attachment(state, session, a)
    audit(session, actor.org_id, actor, "draft.attachment_removed", subject_id=draft.id, attachment_id=attachment_id)
    await session.commit()
    await session.refresh(draft, ["attachments"])
    await to_user(state, actor.user_id, {"type": "draft.updated", "channel_id": str(draft.channel_id)})
    return draft


async def update_draft_body(session, actor: UserActor, draft_id, body: str) -> Draft:
    draft = await get_draft(session, actor, draft_id)
    if draft.status == DraftStatus.open:
        draft.body = body[:MAX_BODY]
        await session.commit()
    return draft


async def delete_attachment(state, session: AsyncSession, a: Attachment) -> None:
    others = (
        await session.execute(select(Attachment.id).where(Attachment.storage_key == a.storage_key, Attachment.id != a.id))
    ).first()
    await session.delete(a)
    if others is None:
        files.remove(state.settings.upload_dir, a.storage_key)


async def publish_work_result(state, session, backroom: Channel, work: WorkResult) -> None:
    from ..serialize import user_names, work_result_out

    names = await user_names(session, [work.staged_by_id])
    out = work_result_out(work, names, state.agent_permissions)
    await to_readers(state, session, backroom, {"type": "work_result.updated", "work_result": out.model_dump(mode="json")})


async def update_quote_rates(state, session, actor: UserActor, work_id, rates: list[int]) -> WorkResult:
    work = await get_work_result(session, actor, work_id)
    if work.kind != "quote":
        raise HTTPException(400, "Only quotes have prices")
    if work.status != WorkStatus.internal:
        raise HTTPException(409, "This quote already left the backroom")
    data = dict(work.data)
    lines = [dict(l) for l in data["lines"]]
    if len(rates) != len(lines):
        raise HTTPException(400, "One price per line")
    for line, rate in zip(lines, rates):
        line["rate"] = max(0, int(rate))
    from ..agents.tools.registry import quote_draft_text, quote_total

    data["lines"] = lines
    data["total_per_month"] = quote_total(lines)
    data["draft_text"] = quote_draft_text(data)
    work.data = data
    audit(session, actor.org_id, actor, "work_result.edited", subject_id=work.id, rates=rates)
    await session.commit()
    backroom = await policy.get_channel(session, actor, work.channel_id)
    await publish_work_result(state, session, backroom, work)
    return work


async def user_row(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)

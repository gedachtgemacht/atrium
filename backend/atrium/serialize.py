"""Build internal response objects from rows."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import policy
from .actors import Actor
from .models import Attachment, Message, User, WorkResult
from .schemas import AttachmentOut, AuthorOut, MemoryMark, MessageOut, PullInfo, WorkResultOut


def author_of(m: Message, partner_name: str = "") -> AuthorOut:
    if m.author_user is not None:
        u = m.author_user
        return AuthorOut(kind="user", id=u.id, name=u.name, initials=u.initials, tone=u.tone, label=u.role_label)
    if m.author_guest is not None:
        g = m.author_guest
        company = g.company or partner_name
        return AuthorOut(
            kind="guest", id=g.id, name=g.name or "Guest", initials=initials(g.name or "G"),
            label=company,
        )
    if m.author_agent is not None:
        a = m.author_agent
        return AuthorOut(kind="agent", id=a.id, name=a.name, initials=a.initial, label="Agent")
    return AuthorOut(kind="user", id=None, name="Former member", initials="?")


def initials(name: str) -> str:
    parts = [p for p in name.replace("-", " ").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def attachment_out(a: Attachment) -> AttachmentOut:
    return AttachmentOut(id=a.id, filename=a.filename, mime=a.mime, size=a.size, summary=a.summary, url=f"/api/files/{a.id}")


def work_result_out(w: WorkResult, names: dict, permissions: dict) -> WorkResultOut:
    return WorkResultOut(
        id=w.id, channel_id=w.channel_id, message_id=w.message_id, kind=w.kind, title=w.title, data=w.data,
        sources=list(w.sources or []), status=w.status.value, staged_by_id=w.staged_by_id,
        staged_by_name=names.get(w.staged_by_id, ""), sent_at=w.sent_at,
        permission=permissions.get(w.agent_id, ""),
    )


async def user_names(session: AsyncSession, ids) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = await session.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return dict(rows.all())


async def messages_out(
    session: AsyncSession, actor: Actor, messages: Sequence[Message], *, partner_name: str = "", permissions=None
) -> list[MessageOut]:
    ids = [m.id for m in messages]
    pulls = await policy.pulls_for(session, actor, ids)
    marks = await policy.memory_marks(session, actor, ids)
    works = (await session.execute(select(WorkResult).where(WorkResult.message_id.in_(ids)))).scalars().all() if ids else []
    names = await user_names(session, [p.pulled_by_id for p in pulls.values()] + [w.staged_by_id for w in works])
    permissions = permissions or {}
    out = []
    for m in messages:
        p = pulls.get(m.id)
        info = None
        if p is not None:
            info = PullInfo(original_id=p.original_id, copy_id=p.copy_id, by_id=p.pulled_by_id,
                            by_name=names.get(p.pulled_by_id, "Former member"), at=p.pulled_at)
        out.append(
            MessageOut(
                id=m.id, channel_id=m.channel_id, author=author_of(m, partner_name), body=m.body,
                created_at=m.created_at, edited_at=m.edited_at, attachments=[attachment_out(a) for a in m.attachments],
                pulled=info if p is not None and p.original_id == m.id else None,
                pulled_from=info if p is not None and p.copy_id == m.id else None,
                from_draft=m.from_draft_id is not None,
                memory_marks=[MemoryMark(id=e.id, kind=e.kind.value) for e in marks if e.source_message_id == m.id],
                work_results=[work_result_out(w, names, permissions) for w in works if w.message_id == m.id],
            )
        )
    return out

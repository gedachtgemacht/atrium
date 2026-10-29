"""The wall. The single place that decides who may read or write what.

Every read path (REST, search, WebSocket fanout, memory, ask the backroom,
agent context) builds its queries from the functions here. Nothing outside
this module selects Channel, Message, Pull or MemoryEntry rows directly; a test
enforces that (tests/wall/test_policy_single_place.py).

Rules (see CLAUDE.md):
1. Agents cannot read shared channels, on any path.
2. Only people write in shared channels.
3. Customer messages reach the backroom only when a person pulls them.
4. Agents only produce drafts; a person sends them as themselves.
5. Guests see nothing internal.
"""

import uuid
from collections.abc import Sequence

from fastapi import HTTPException
from sqlalchemy import Select, delete, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from .actors import Actor, AgentActor, GuestActor, SystemActor, UserActor
from .models import (
    INTERNAL_KINDS,
    Channel,
    ChannelKind,
    ChannelMember,
    Guest,
    MemoryEntry,
    Message,
    Pull,
)


class WallViolation(Exception):
    """Raised when code tries to move shared channel content to an agent or internal content to a guest."""


def forbidden(detail: str = "Not allowed") -> HTTPException:
    return HTTPException(status_code=403, detail=detail)


def not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Not found")


# ---------------------------------------------------------------- channels


def readable_channel_ids(actor: Actor) -> Select:
    """SELECT channel.id for every channel the actor may read."""
    if isinstance(actor, UserActor):
        direct = select(ChannelMember.channel_id).where(ChannelMember.user_id == actor.user_id)
        parent = aliased(Channel)
        backrooms = (
            select(Channel.id)
            .join(parent, Channel.backroom_for_id == parent.id)
            .join(ChannelMember, ChannelMember.channel_id == parent.id)
            .where(Channel.kind == ChannelKind.backroom, ChannelMember.user_id == actor.user_id)
        )
        return select(Channel.id).where(
            Channel.org_id == actor.org_id,
            Channel.kind != ChannelKind.backroom,
            Channel.id.in_(direct),
        ).union(backrooms)
    if isinstance(actor, GuestActor):
        return select(Channel.id).where(Channel.id == actor.channel_id, Channel.kind == ChannelKind.shared)
    if isinstance(actor, AgentActor):
        if not actor.scope_channel_ids:
            return select(Channel.id).where(false())
        return select(Channel.id).where(
            Channel.org_id == actor.org_id,
            Channel.id.in_(actor.scope_channel_ids),
            Channel.kind.in_(INTERNAL_KINDS),
        )
    if isinstance(actor, SystemActor):
        return select(Channel.id).where(Channel.org_id == actor.org_id)
    raise TypeError(actor)


def readable_channels(actor: Actor) -> Select:
    return select(Channel).where(Channel.id.in_(readable_channel_ids(actor)))


async def get_channel(session: AsyncSession, actor: Actor, channel_id: uuid.UUID) -> Channel:
    ch = (await session.execute(readable_channels(actor).where(Channel.id == channel_id))).scalar_one_or_none()
    if ch is None:
        raise not_found()
    return ch


async def list_channels(session: AsyncSession, actor: Actor) -> Sequence[Channel]:
    return (await session.execute(readable_channels(actor).order_by(Channel.name))).scalars().all()


async def backroom_of(session: AsyncSession, actor: UserActor, shared: Channel) -> Channel | None:
    stmt = readable_channels(actor).where(Channel.backroom_for_id == shared.id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def shared_of(session: AsyncSession, actor: UserActor, backroom: Channel) -> Channel:
    if backroom.kind != ChannelKind.backroom or backroom.backroom_for_id is None:
        raise not_found()
    return await get_channel(session, actor, backroom.backroom_for_id)


async def reader_user_ids(session: AsyncSession, channel: Channel) -> set[uuid.UUID]:
    """Internal people who may read a channel. Used by the WebSocket fanout."""
    target = channel.backroom_for_id if channel.kind == ChannelKind.backroom else channel.id
    rows = await session.execute(select(ChannelMember.user_id).where(ChannelMember.channel_id == target))
    return set(rows.scalars())


async def channel_kind(session: AsyncSession, channel_id: uuid.UUID) -> ChannelKind | None:
    return (await session.execute(select(Channel.kind).where(Channel.id == channel_id))).scalar_one_or_none()


async def all_backrooms(session: AsyncSession, actor: UserActor) -> Sequence[Channel]:
    stmt = readable_channels(actor).where(Channel.kind == ChannelKind.backroom)
    return (await session.execute(stmt)).scalars().all()


async def is_member(session: AsyncSession, user_id: uuid.UUID, channel_id: uuid.UUID) -> bool:
    row = await session.execute(
        select(ChannelMember).where(ChannelMember.channel_id == channel_id, ChannelMember.user_id == user_id)
    )
    return row.scalar_one_or_none() is not None


async def channel_by_id_for_admin(session: AsyncSession, actor: UserActor, channel_id: uuid.UUID) -> Channel:
    """Admins manage membership of channels they are not in. Metadata only, no messages."""
    if not actor.is_admin:
        raise forbidden()
    ch = (
        await session.execute(select(Channel).where(Channel.id == channel_id, Channel.org_id == actor.org_id))
    ).scalar_one_or_none()
    if ch is None:
        raise not_found()
    return ch


async def all_channels_for_admin(session: AsyncSession, actor: UserActor) -> Sequence[Channel]:
    if not actor.is_admin:
        raise forbidden()
    stmt = select(Channel).where(Channel.org_id == actor.org_id, Channel.kind != ChannelKind.backroom)
    return (await session.execute(stmt.order_by(Channel.name))).scalars().all()


# ---------------------------------------------------------------- messages


def readable_messages(actor: Actor) -> Select:
    """SELECT message for every message the actor may read. All message reads start here."""
    stmt = select(Message).where(Message.channel_id.in_(readable_channel_ids(actor)))
    if isinstance(actor, AgentActor):
        # Belt and braces: even if the scope were wrong, no shared channel row comes back.
        internal = select(Channel.id).where(Channel.kind.in_(INTERNAL_KINDS))
        stmt = stmt.where(Message.channel_id.in_(internal))
    return stmt


async def get_message(session: AsyncSession, actor: Actor, message_id: uuid.UUID) -> Message:
    msg = (await session.execute(readable_messages(actor).where(Message.id == message_id))).scalar_one_or_none()
    if msg is None:
        raise not_found()
    return msg


async def channel_messages(
    session: AsyncSession, actor: Actor, channel_id: uuid.UUID, *, before=None, limit: int = 100
) -> list[Message]:
    stmt = readable_messages(actor).where(Message.channel_id == channel_id)
    if before is not None:
        stmt = stmt.where(Message.created_at < before)
    stmt = stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return list(reversed(rows))


async def messages_by_ids(session: AsyncSession, actor: Actor, ids: Sequence[uuid.UUID]) -> list[Message]:
    if not ids:
        return []
    stmt = readable_messages(actor).where(Message.id.in_(list(ids)))
    return list((await session.execute(stmt.order_by(Message.created_at))).scalars().all())


async def search_messages(session: AsyncSession, actor: Actor, query: str, *, channel_ids=None, limit: int = 20):
    from sqlalchemy import func

    ts = func.websearch_to_tsquery("simple", query)
    stmt = readable_messages(actor).where(Message.search.op("@@")(ts))
    if channel_ids is not None:
        stmt = stmt.where(Message.channel_id.in_(list(channel_ids)))
    stmt = stmt.order_by(func.ts_rank(Message.search, ts).desc(), Message.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def guest_authored_messages(session: AsyncSession, actor: SystemActor, guest_id: uuid.UUID) -> list[Message]:
    stmt = readable_messages(actor).where(Message.author_guest_id == guest_id).order_by(Message.created_at)
    return list((await session.execute(stmt)).scalars().all())


async def delete_messages_older_than(session: AsyncSession, actor: SystemActor, kinds, cutoff) -> int:
    ids = select(Channel.id).where(Channel.org_id == actor.org_id, Channel.kind.in_(kinds))
    res = await session.execute(delete(Message).where(Message.channel_id.in_(ids), Message.created_at < cutoff))
    return res.rowcount or 0


def assert_can_post(actor: Actor, channel: Channel) -> None:
    """Rule 2: only people write in shared channels."""
    if isinstance(actor, AgentActor):
        if channel.kind == ChannelKind.shared:
            raise forbidden("Agents cannot write in shared channels")
        if channel.id not in actor.scope_channel_ids:
            raise forbidden("Agent is not working in this channel")
        return
    if isinstance(actor, GuestActor):
        if actor.read_only or channel.kind != ChannelKind.shared or channel.id != actor.channel_id:
            raise forbidden()
        return
    if isinstance(actor, UserActor):
        return  # channel was loaded through readable_channels
    raise forbidden()


# ---------------------------------------------------------------- pulling


async def assert_can_pull(session: AsyncSession, actor: Actor, message_id: uuid.UUID) -> tuple[Message, Channel, Channel]:
    """Rule 3: only an internal person who can read the shared channel may pull from it."""
    if not isinstance(actor, UserActor):
        raise forbidden("Only people can pull messages into the backroom")
    msg = await get_message(session, actor, message_id)
    shared = await get_channel(session, actor, msg.channel_id)
    if shared.kind != ChannelKind.shared:
        raise HTTPException(status_code=400, detail="Only messages from shared channels can be pulled")
    backroom = await backroom_of(session, actor, shared)
    if backroom is None:
        raise forbidden()
    return msg, shared, backroom


async def pulls_for(session: AsyncSession, actor: UserActor, message_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Pull]:
    """Pull records for messages, keyed by original id and copy id. Internal people only."""
    if not message_ids:
        return {}
    readable = select(Message.id).where(Message.id.in_(list(message_ids))).where(
        Message.channel_id.in_(readable_channel_ids(actor))
    )
    stmt = select(Pull).where(or_(Pull.original_id.in_(readable), Pull.copy_id.in_(readable)))
    out: dict[uuid.UUID, Pull] = {}
    for p in (await session.execute(stmt)).scalars():
        out[p.original_id] = p
        out[p.copy_id] = p
    return out


async def existing_pull(session: AsyncSession, original_id: uuid.UUID) -> Pull | None:
    return (await session.execute(select(Pull).where(Pull.original_id == original_id))).scalar_one_or_none()


# ---------------------------------------------------------------- memory


def readable_memory(actor: Actor) -> Select:
    """Memory lives in internal channels only, so no guest ever reads it."""
    if isinstance(actor, GuestActor):
        return select(MemoryEntry).where(false())
    internal = select(Channel.id).where(Channel.kind.in_(INTERNAL_KINDS))
    return select(MemoryEntry).where(
        MemoryEntry.channel_id.in_(readable_channel_ids(actor)), MemoryEntry.channel_id.in_(internal)
    )


async def channel_memory(session: AsyncSession, actor: Actor, channel_id: uuid.UUID) -> list[MemoryEntry]:
    stmt = readable_memory(actor).where(MemoryEntry.channel_id == channel_id).order_by(MemoryEntry.created_at)
    return list((await session.execute(stmt)).scalars().all())


async def memory_in(session: AsyncSession, actor: Actor, channel_ids: Sequence[uuid.UUID]) -> list[MemoryEntry]:
    stmt = readable_memory(actor).where(MemoryEntry.channel_id.in_(list(channel_ids))).order_by(MemoryEntry.created_at)
    return list((await session.execute(stmt)).scalars().all())


async def get_memory(session: AsyncSession, actor: Actor, entry_id: uuid.UUID) -> MemoryEntry:
    e = (await session.execute(readable_memory(actor).where(MemoryEntry.id == entry_id))).scalar_one_or_none()
    if e is None:
        raise not_found()
    return e


async def memory_marks(session: AsyncSession, actor: UserActor, message_ids: Sequence[uuid.UUID]):
    if not message_ids:
        return []
    stmt = readable_memory(actor).where(MemoryEntry.source_message_id.in_(list(message_ids)))
    return list((await session.execute(stmt.order_by(MemoryEntry.created_at))).scalars().all())


async def memory_answered_by(session: AsyncSession, work_result_id, source_ids) -> list[MemoryEntry]:
    conds = [MemoryEntry.work_result_id == work_result_id]
    if source_ids:
        conds.append(MemoryEntry.source_message_id.in_(list(source_ids)))
    internal = select(Channel.id).where(Channel.kind.in_(INTERNAL_KINDS))
    stmt = select(MemoryEntry).where(or_(*conds), MemoryEntry.channel_id.in_(internal))
    return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------- guests


async def guest_for_channel(session: AsyncSession, actor: UserActor, guest_id: uuid.UUID) -> Guest:
    guest = await session.get(Guest, guest_id)
    if guest is None:
        raise not_found()
    await get_channel(session, actor, guest.channel_id)
    return guest


def guest_visible_channel(actor: GuestActor, channel: Channel) -> None:
    if channel.kind != ChannelKind.shared or channel.id != actor.channel_id:
        raise WallViolation("guest asked for a channel that is not their shared channel")


def assert_guest_payload_channel(kind: ChannelKind) -> None:
    """Rule 5: nothing from internal channels is ever serialized for a guest."""
    if kind != ChannelKind.shared:
        raise WallViolation("internal content addressed to a guest")


def assert_agent_context_channel(kind: ChannelKind | None) -> None:
    """Rule 1: nothing from shared channels reaches an LLM."""
    if kind not in INTERNAL_KINDS:
        raise WallViolation("shared channel content addressed to an agent")


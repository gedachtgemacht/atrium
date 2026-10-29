"""Publish changes over WebSocket. Recipients come from atrium.policy."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from .. import policy
from ..actors import SystemActor
from ..guest.schemas import GuestEvent
from ..guest.serialize import guest_message
from ..models import Channel, ChannelKind, Message
from ..serialize import messages_out


async def publish_message(state, session: AsyncSession, channel: Channel, msg: Message, *, event: str = "message.created"):
    sys = SystemActor(channel.org_id)
    msg = await policy.get_message(session, sys, msg.id)
    readers = await policy.reader_user_ids(session, channel)
    [out] = await messages_out(session, sys, [msg], partner_name=channel.partner_name, permissions=state_permissions(state))
    await state.hub.to_users(readers, {"type": event, "message": out.model_dump(mode="json")})
    if channel.kind == ChannelKind.shared and event == "message.created":
        payload = GuestEvent(type="message.created", message=guest_message(channel, msg))
        await state.hub.to_guests_of(channel.id, payload.model_dump(mode="json"))


async def to_readers(state, session: AsyncSession, channel: Channel, event: dict) -> None:
    """Internal events (work results, memory, agent status). Never sent to guests."""
    readers = await policy.reader_user_ids(session, channel)
    await state.hub.to_users(readers, event)


async def to_user(state, user_id: uuid.UUID, event: dict) -> None:
    await state.hub.to_users([user_id], event)


def state_permissions(state) -> dict:
    return getattr(state, "agent_permissions", {})

"""Publish changes over WebSocket. Recipients come from atrium.policy."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from .. import policy
from ..actors import SystemActor
from ..guest.schemas import GuestEvent
from ..guest.serialize import guest_message
from ..models import Channel, ChannelKind, Message
from ..serialize import messages_out


async def publish_message(
    state, session: AsyncSession, channel: Channel, msg: Message, *, event: str = "message.created", to_guests: bool | None = None
):
    """message.created goes to guests of a shared channel. message.updated only with to_guests=True (an edit),
    never for internal changes such as the "pulled into the backroom" marker."""
    sys = SystemActor(channel.org_id)
    msg = await policy.get_message(session, sys, msg.id)
    readers = await policy.reader_user_ids(session, channel)
    [out] = await messages_out(session, sys, [msg], partner_name=channel.partner_name, permissions=state_permissions(state))
    await state.hub.to_users(readers, {"type": event, "message": out.model_dump(mode="json")})
    if to_guests is None:
        to_guests = event == "message.created"
    if channel.kind == ChannelKind.shared and to_guests:
        payload = GuestEvent(type=event, message=guest_message(channel, msg))
        await state.hub.to_guests_of(channel.id, payload.model_dump(mode="json"))


async def publish_deleted(state, session: AsyncSession, channel: Channel, message_id) -> None:
    readers = await policy.reader_user_ids(session, channel)
    await state.hub.to_users(readers, {"type": "message.deleted", "channel_id": str(channel.id), "message_id": str(message_id)})
    if channel.kind == ChannelKind.shared:
        payload = GuestEvent(type="message.deleted", message_id=message_id)
        await state.hub.to_guests_of(channel.id, payload.model_dump(mode="json"))


async def to_readers(state, session: AsyncSession, channel: Channel, event: dict) -> None:
    """Internal events (work results, memory, agent status). Never sent to guests."""
    readers = await policy.reader_user_ids(session, channel)
    await state.hub.to_users(readers, event)


async def to_user(state, user_id: uuid.UUID, event: dict) -> None:
    await state.hub.to_users([user_id], event)


def state_permissions(state) -> dict:
    return getattr(state, "agent_permissions", {})

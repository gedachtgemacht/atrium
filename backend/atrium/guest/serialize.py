"""Build guest response objects. Only ever called with rows from the guest's shared channel."""

from .. import policy
from ..models import Attachment, Channel, Message
from ..serialize import initials
from .schemas import GuestAuthor, GuestFile, GuestMessage


def guest_author(m: Message) -> GuestAuthor:
    if m.author_guest is not None:
        g = m.author_guest
        return GuestAuthor(kind="guest", id=g.id, name=g.name or "Guest", initials=initials(g.name or "G"))
    if m.author_user is not None:
        u = m.author_user
        return GuestAuthor(kind="staff", id=u.id, name=u.name, initials=u.initials)
    if m.author_agent is not None:
        raise policy.WallViolation("agent authored message in a shared channel")
    return GuestAuthor(kind="staff", id=m.id, name="Former member", initials="?")


def guest_file(a: Attachment) -> GuestFile:
    return GuestFile(id=a.id, filename=a.filename, mime=a.mime, size=a.size, url=f"/g/api/files/{a.id}")


def guest_message(channel: Channel, m: Message) -> GuestMessage:
    policy.assert_guest_payload_channel(channel.kind)
    if m.channel_id != channel.id:
        raise policy.WallViolation("message from another channel")
    return GuestMessage(
        id=m.id, author=guest_author(m), body=m.body, created_at=m.created_at,
        attachments=[guest_file(a) for a in m.attachments],
    )

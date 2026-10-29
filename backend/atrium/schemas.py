"""Response schemas for internal people. Guests never get these; see atrium.guest.schemas."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AuthorOut(Out):
    kind: str  # user | guest | agent
    id: uuid.UUID | None
    name: str
    initials: str
    tone: str = ""
    label: str = ""


class AttachmentOut(Out):
    id: uuid.UUID
    filename: str
    mime: str
    size: int
    summary: str = ""
    url: str


class PullInfo(Out):
    original_id: uuid.UUID
    copy_id: uuid.UUID
    by_id: uuid.UUID | None
    by_name: str
    at: datetime


class MemoryMark(Out):
    id: uuid.UUID
    kind: str


class WorkResultOut(Out):
    id: uuid.UUID
    channel_id: uuid.UUID
    message_id: uuid.UUID | None
    kind: str
    title: str
    data: dict
    sources: list[str]
    status: str
    staged_by_id: uuid.UUID | None
    staged_by_name: str = ""
    sent_at: datetime | None
    permission: str = ""


class MessageOut(Out):
    id: uuid.UUID
    channel_id: uuid.UUID
    author: AuthorOut
    body: str
    created_at: datetime
    attachments: list[AttachmentOut] = []
    # On a customer message in the shared channel: who pulled it in.
    pulled: PullInfo | None = None
    # On the backroom copy: where it came from.
    pulled_from: PullInfo | None = None
    from_draft: bool = False
    memory_marks: list[MemoryMark] = []
    work_results: list[WorkResultOut] = []


class MemberOut(Out):
    kind: str  # user | guest
    id: uuid.UUID
    name: str
    initials: str
    tone: str = ""
    label: str = ""


class GuestInfoOut(Out):
    id: uuid.UUID
    name: str | None
    company: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    joined: bool


class ChannelOut(Out):
    id: uuid.UUID
    kind: str
    name: str
    description: str
    partner_name: str
    backroom_id: uuid.UUID | None = None
    backroom_for_id: uuid.UUID | None = None
    unread: int = 0
    members: list[MemberOut] = []
    guests: list[GuestInfoOut] = []
    room_name: str = ""


class MeOut(Out):
    id: uuid.UUID
    name: str
    initials: str
    tone: str
    email: str
    role_label: str
    is_admin: bool
    org_name: str
    server_location: str


class DraftOut(Out):
    id: uuid.UUID
    channel_id: uuid.UUID
    work_result_id: uuid.UUID | None
    agent_name: str = ""
    body: str
    status: str
    attachments: list[AttachmentOut] = []
    created_at: datetime


class MemoryOut(Out):
    id: uuid.UUID
    channel_id: uuid.UUID
    kind: str
    text: str
    owner_name: str
    due_label: str
    due_date: date | None
    source_message_id: uuid.UUID | None
    source_label: str = ""
    status: str
    done_at: datetime | None
    done_note: str
    created_at: datetime


class AgentOut(Out):
    id: uuid.UUID
    slug: str
    handle: str
    name: str
    initial: str
    description: str
    status: str = ""
    busy: bool = False
    waiting: int = 0


class AskSource(Out):
    kind: str  # message | memory
    id: uuid.UUID
    channel_id: uuid.UUID
    label: str


class AskOut(Out):
    question: str
    answer: str
    known: bool
    sources: list[AskSource]


class SearchHit(Out):
    message: MessageOut
    channel_name: str
    channel_kind: str


class RoomOut(Out):
    id: uuid.UUID
    name: str
    kind: str
    layout: str
    position: int
    channel_id: uuid.UUID | None

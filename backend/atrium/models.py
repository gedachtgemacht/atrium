"""Database tables.

There is deliberately no table for room presence, "last seen" or IP addresses.
Room presence lives in memory only (atrium.rooms.presence).
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Computed,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow
from .ids import uuid7


def _enum(e: type[enum.Enum]) -> Enum:
    return Enum(e, native_enum=False, length=24, values_callable=lambda x: [m.value for m in x])


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)


def fk(target: str, nullable: bool = False, ondelete: str = "CASCADE", index: bool = True) -> Mapped:
    return mapped_column(UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable, index=index)


class ChannelKind(str, enum.Enum):
    internal = "internal"
    backroom = "backroom"
    shared = "shared"


INTERNAL_KINDS = (ChannelKind.internal, ChannelKind.backroom)


class AuthorKind(str, enum.Enum):
    user = "user"
    guest = "guest"
    agent = "agent"


class WorkStatus(str, enum.Enum):
    internal = "internal"
    with_user = "with_user"
    sent = "sent"


class DraftStatus(str, enum.Enum):
    open = "open"
    sent = "sent"
    discarded = "discarded"


class MemoryKind(str, enum.Enum):
    decided = "decided"
    open = "open"
    committed = "committed"


class MemoryStatus(str, enum.Enum):
    active = "active"
    done = "done"


class RoomKind(str, enum.Enum):
    normal = "normal"
    quiet = "quiet"


class Organization(Base):
    __tablename__ = "organization"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(200))
    server_location: Mapped[str] = mapped_column(String(100), default="")
    interest_rate_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("6.00"))
    # {"shared_days": int|None, "backroom_days": int|None, "audit_days": int|None, "guest_days_after_expiry": int|None}
    retention: Mapped[dict] = mapped_column(JSONB, default=dict)
    llm_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class User(Base):
    __tablename__ = "user_account"
    id: Mapped[uuid.UUID] = pk()
    org_id: Mapped[uuid.UUID] = fk("organization.id")
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    initials: Mapped[str] = mapped_column(String(4))
    tone: Mapped[str] = mapped_column(String(9), default="#D6DEE6")
    role_label: Mapped[str] = mapped_column(String(100), default="")
    is_admin: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class UserSession(Base):
    __tablename__ = "user_session"
    id: Mapped[uuid.UUID] = pk()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = fk("user_account.id")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]


class Agent(Base):
    __tablename__ = "agent"
    id: Mapped[uuid.UUID] = pk()
    org_id: Mapped[uuid.UUID] = fk("organization.id")
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    handle: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(100))
    initial: Mapped[str] = mapped_column(String(2))
    is_active: Mapped[bool] = mapped_column(default=True)


class Channel(Base):
    __tablename__ = "channel"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'backroom') = (backroom_for_id IS NOT NULL)", name="backroom_link"
        ),
    )
    id: Mapped[uuid.UUID] = pk()
    org_id: Mapped[uuid.UUID] = fk("organization.id")
    kind: Mapped[ChannelKind] = mapped_column(_enum(ChannelKind))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    partner_name: Mapped[str] = mapped_column(String(200), default="")
    backroom_for_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channel.id", ondelete="CASCADE"), unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    backroom_for: Mapped["Channel | None"] = relationship(remote_side=[id], foreign_keys=[backroom_for_id])


class ChannelMember(Base):
    __tablename__ = "channel_member"
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channel.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class Guest(Base):
    __tablename__ = "guest"
    id: Mapped[uuid.UUID] = pk()
    channel_id: Mapped[uuid.UUID] = fk("channel.id")
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    company: Mapped[str] = mapped_column(String(200), default="")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    invited_by_id: Mapped[uuid.UUID | None] = fk("user_account.id", nullable=True, ondelete="SET NULL", index=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class GuestSession(Base):
    __tablename__ = "guest_session"
    id: Mapped[uuid.UUID] = pk()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    guest_id: Mapped[uuid.UUID] = fk("guest.id")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]


class Message(Base):
    __tablename__ = "message"
    __table_args__ = (
        CheckConstraint(
            "(author_user_id IS NOT NULL)::int + (author_guest_id IS NOT NULL)::int"
            " + (author_agent_id IS NOT NULL)::int = 1",
            name="one_author",
        ),
        Index("ix_message_channel_created", "channel_id", "created_at"),
        Index("ix_message_search", "search", postgresql_using="gin"),
    )
    id: Mapped[uuid.UUID] = pk()
    channel_id: Mapped[uuid.UUID] = fk("channel.id", index=False)
    author_kind: Mapped[AuthorKind] = mapped_column(_enum(AuthorKind))
    author_user_id: Mapped[uuid.UUID | None] = fk("user_account.id", nullable=True, ondelete="SET NULL")
    author_guest_id: Mapped[uuid.UUID | None] = fk("guest.id", nullable=True)
    author_agent_id: Mapped[uuid.UUID | None] = fk("agent.id", nullable=True, ondelete="SET NULL")
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    edited_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Set on the backroom copy of a pulled customer message.
    pulled_from_id: Mapped[uuid.UUID | None] = fk("message.id", nullable=True, ondelete="SET NULL")
    # Set when a person sent an agent draft. Internal only, never in guest schemas.
    from_draft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    search = mapped_column(TSVECTOR, Computed("to_tsvector('simple', coalesce(body, ''))", persisted=True))

    author_user: Mapped[User | None] = relationship(lazy="joined")
    author_guest: Mapped[Guest | None] = relationship(lazy="joined")
    author_agent: Mapped[Agent | None] = relationship(lazy="joined")
    attachments: Mapped[list["Attachment"]] = relationship(
        lazy="selectin", order_by="Attachment.created_at", foreign_keys="Attachment.message_id"
    )


class Attachment(Base):
    __tablename__ = "attachment"
    id: Mapped[uuid.UUID] = pk()
    message_id: Mapped[uuid.UUID | None] = fk("message.id", nullable=True)
    draft_id: Mapped[uuid.UUID | None] = fk("draft.id", nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(120))
    size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(String(300), default="")
    uploader_user_id: Mapped[uuid.UUID | None] = fk("user_account.id", nullable=True, ondelete="SET NULL", index=False)
    uploader_guest_id: Mapped[uuid.UUID | None] = fk("guest.id", nullable=True, index=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Pull(Base):
    """A customer message a person pulled into the backroom."""

    __tablename__ = "pull"
    id: Mapped[uuid.UUID] = pk()
    original_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("message.id", ondelete="CASCADE"), unique=True
    )
    copy_id: Mapped[uuid.UUID] = fk("message.id")
    pulled_by_id: Mapped[uuid.UUID | None] = fk("user_account.id", nullable=True, ondelete="SET NULL", index=False)
    pulled_at: Mapped[datetime] = mapped_column(default=utcnow)

    pulled_by: Mapped[User | None] = relationship(lazy="joined")


class AgentRun(Base):
    __tablename__ = "agent_run"
    id: Mapped[uuid.UUID] = pk()
    agent_id: Mapped[uuid.UUID] = fk("agent.id")
    channel_id: Mapped[uuid.UUID | None] = fk("channel.id", nullable=True)
    # mention | memory | ask | notes
    trigger: Mapped[str] = mapped_column(String(20))
    trigger_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    started_by_id: Mapped[uuid.UUID | None] = fk("user_account.id", nullable=True, ondelete="SET NULL", index=False)
    # running | done | failed | aborted
    status: Mapped[str] = mapped_column(String(12), default="running")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class WorkResult(Base):
    __tablename__ = "work_result"
    id: Mapped[uuid.UUID] = pk()
    channel_id: Mapped[uuid.UUID] = fk("channel.id")
    message_id: Mapped[uuid.UUID | None] = fk("message.id", nullable=True, ondelete="SET NULL")
    agent_id: Mapped[uuid.UUID | None] = fk("agent.id", nullable=True, ondelete="SET NULL", index=False)
    run_id: Mapped[uuid.UUID | None] = fk("agent_run.id", nullable=True, ondelete="SET NULL", index=False)
    # quote | payment_terms
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    sources: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    answers_message_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    status: Mapped[WorkStatus] = mapped_column(_enum(WorkStatus), default=WorkStatus.internal)
    staged_by_id: Mapped[uuid.UUID | None] = fk("user_account.id", nullable=True, ondelete="SET NULL", index=False)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Draft(Base):
    """Text and files an agent prepared, sitting in one person's composer of a shared channel."""

    __tablename__ = "draft"
    id: Mapped[uuid.UUID] = pk()
    owner_id: Mapped[uuid.UUID] = fk("user_account.id")
    channel_id: Mapped[uuid.UUID] = fk("channel.id")
    work_result_id: Mapped[uuid.UUID | None] = fk("work_result.id", nullable=True, ondelete="SET NULL")
    agent_id: Mapped[uuid.UUID | None] = fk("agent.id", nullable=True, ondelete="SET NULL", index=False)
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[DraftStatus] = mapped_column(_enum(DraftStatus), default=DraftStatus.open)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    sent_message_id: Mapped[uuid.UUID | None] = fk("message.id", nullable=True, ondelete="SET NULL", index=False)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)

    attachments: Mapped[list[Attachment]] = relationship(lazy="selectin", foreign_keys=[Attachment.draft_id])


class MemoryEntry(Base):
    __tablename__ = "memory_entry"
    id: Mapped[uuid.UUID] = pk()
    channel_id: Mapped[uuid.UUID] = fk("channel.id")
    kind: Mapped[MemoryKind] = mapped_column(_enum(MemoryKind))
    text: Mapped[str] = mapped_column(Text)
    owner_name: Mapped[str] = mapped_column(String(200), default="")
    owner_user_id: Mapped[uuid.UUID | None] = fk("user_account.id", nullable=True, ondelete="SET NULL", index=False)
    due_label: Mapped[str] = mapped_column(String(100), default="")
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    source_message_id: Mapped[uuid.UUID | None] = fk("message.id", nullable=True, ondelete="SET NULL")
    status: Mapped[MemoryStatus] = mapped_column(_enum(MemoryStatus), default=MemoryStatus.active)
    done_at: Mapped[datetime | None] = mapped_column(nullable=True)
    done_note: Mapped[str] = mapped_column(String(300), default="")
    work_result_id: Mapped[uuid.UUID | None] = fk("work_result.id", nullable=True, ondelete="SET NULL", index=False)
    created_by_kind: Mapped[AuthorKind] = mapped_column(_enum(AuthorKind), default=AuthorKind.agent)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    updated_by_id: Mapped[uuid.UUID | None] = fk("user_account.id", nullable=True, ondelete="SET NULL", index=False)


class LlmCall(Base):
    """One row per LLM request. Stores ids and metadata, never content."""

    __tablename__ = "llm_call"
    id: Mapped[uuid.UUID] = pk()
    run_id: Mapped[uuid.UUID | None] = fk("agent_run.id", nullable=True, ondelete="SET NULL")
    agent_id: Mapped[uuid.UUID | None] = fk("agent.id", nullable=True, ondelete="SET NULL", index=False)
    trigger: Mapped[str] = mapped_column(String(20))
    context_message_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    at: Mapped[datetime] = mapped_column(default=utcnow)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    ok: Mapped[bool] = mapped_column(default=True)


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (Index("ix_audit_at", "at"),)
    id: Mapped[uuid.UUID] = pk()
    org_id: Mapped[uuid.UUID] = fk("organization.id", index=False)
    at: Mapped[datetime] = mapped_column(default=utcnow)
    # user | guest | agent | system
    actor_kind: Mapped[str] = mapped_column(String(10))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(200), default="")
    action: Mapped[str] = mapped_column(String(40), index=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)


class ReadMarker(Base):
    __tablename__ = "read_marker"
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channel.id", ondelete="CASCADE"), primary_key=True
    )
    last_read_at: Mapped[datetime] = mapped_column(default=utcnow)


class Room(Base):
    """Room configuration only. Who is in a room is never stored."""

    __tablename__ = "room"
    __table_args__ = (UniqueConstraint("org_id", "name"),)
    id: Mapped[uuid.UUID] = pk()
    org_id: Mapped[uuid.UUID] = fk("organization.id", index=False)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[RoomKind] = mapped_column(_enum(RoomKind), default=RoomKind.normal)
    # CSS class for the floor plan: dispatch | sales | warehouse | quiet
    layout: Mapped[str] = mapped_column(String(30), default="")
    position: Mapped[int] = mapped_column(default=0)
    channel_id: Mapped[uuid.UUID | None] = fk("channel.id", nullable=True, ondelete="SET NULL", index=False)

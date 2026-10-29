import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import files, policy
from ..actors import SystemActor, UserActor
from ..db import utcnow
from ..deps import current_admin, get_session, get_state
from ..llm.client import available_providers
from ..models import (
    INTERNAL_KINDS,
    Attachment,
    AuditEvent,
    ChannelKind,
    ChannelMember,
    Guest,
    LlmCall,
    Message,
    Organization,
    User,
)
from ..security import hash_password
from ..serialize import initials
from ..services.audit import audit
from ..state import AppState

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AuditOut(BaseModel):
    id: uuid.UUID
    at: datetime
    actor_kind: str
    actor_name: str
    action: str
    subject_id: uuid.UUID | None
    details: dict


@router.get("/audit", response_model=list[AuditOut])
async def audit_log(action: str | None = None, before: datetime | None = None, limit: int = 100,
                    admin: UserActor = Depends(current_admin), session: AsyncSession = Depends(get_session)):
    stmt = select(AuditEvent).where(AuditEvent.org_id == admin.org_id)
    if action:
        stmt = stmt.where(AuditEvent.action.startswith(action))
    if before:
        stmt = stmt.where(AuditEvent.at < before)
    rows = (await session.execute(stmt.order_by(AuditEvent.at.desc()).limit(min(limit, 500)))).scalars()
    return [AuditOut(id=r.id, at=r.at, actor_kind=r.actor_kind, actor_name=r.actor_name, action=r.action,
                     subject_id=r.subject_id, details=r.details) for r in rows]


class SettingsOut(BaseModel):
    name: str
    server_location: str
    interest_rate_pct: Decimal
    retention: dict
    llm_provider: str | None
    llm_providers: list[str]
    default_llm_provider: str


class SettingsIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    server_location: str | None = Field(default=None, max_length=100)
    interest_rate_pct: Decimal | None = Field(default=None, ge=0, le=100)
    retention: dict | None = None
    llm_provider: str | None = None


RETENTION_KEYS = ("shared_days", "internal_days", "audit_days", "guest_days_after_expiry")


def settings_out(org: Organization, state: AppState) -> SettingsOut:
    return SettingsOut(name=org.name, server_location=org.server_location, interest_rate_pct=org.interest_rate_pct,
                       retention={k: (org.retention or {}).get(k) for k in RETENTION_KEYS}, llm_provider=org.llm_provider,
                       llm_providers=available_providers(state.settings), default_llm_provider=state.settings.llm_provider)


@router.get("/settings", response_model=SettingsOut)
async def get_settings(admin: UserActor = Depends(current_admin), session: AsyncSession = Depends(get_session),
                       state: AppState = Depends(get_state)):
    return settings_out(await session.get(Organization, admin.org_id), state)


@router.patch("/settings", response_model=SettingsOut)
async def patch_settings(body: SettingsIn, admin: UserActor = Depends(current_admin), session: AsyncSession = Depends(get_session),
                         state: AppState = Depends(get_state)):
    org = await session.get(Organization, admin.org_id)
    changes = body.model_dump(exclude_unset=True)
    if "retention" in changes:
        clean = {}
        for k in RETENTION_KEYS:
            v = (body.retention or {}).get(k)
            if v in (None, "", 0):
                clean[k] = None
            else:
                try:
                    clean[k] = max(1, int(v))
                except (TypeError, ValueError):
                    raise HTTPException(400, f"{k} must be a number of days")
        org.retention = clean
    if "llm_provider" in changes:
        if body.llm_provider and body.llm_provider not in available_providers(state.settings):
            raise HTTPException(400, "This provider isn't configured on the server")
        org.llm_provider = body.llm_provider or None
    for k in ("name", "server_location", "interest_rate_pct"):
        if k in changes and changes[k] is not None:
            setattr(org, k, changes[k])
    audit(session, org.id, admin, "settings.changed", fields=list(changes))
    await session.commit()
    return settings_out(org, state)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    initials: str
    role_label: str
    is_admin: bool
    is_active: bool


class UserIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=10, max_length=200)
    role_label: str = ""
    is_admin: bool = False


class UserPatch(BaseModel):
    name: str | None = None
    role_label: str | None = None
    is_admin: bool | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=200)


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, name=u.name, initials=u.initials, role_label=u.role_label, is_admin=u.is_admin,
                   is_active=u.is_active)


@router.get("/users", response_model=list[UserOut])
async def users(admin: UserActor = Depends(current_admin), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(User).where(User.org_id == admin.org_id).order_by(User.name))).scalars()
    return [user_out(u) for u in rows]


@router.post("/users", response_model=UserOut)
async def create_user(body: UserIn, admin: UserActor = Depends(current_admin), session: AsyncSession = Depends(get_session)):
    email = body.email.lower()
    if (await session.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise HTTPException(409, "This email already has an account")
    u = User(org_id=admin.org_id, email=email, password_hash=hash_password(body.password), name=body.name.strip(),
             initials=initials(body.name), role_label=body.role_label.strip(), is_admin=body.is_admin)
    session.add(u)
    await session.flush()
    audit(session, admin.org_id, admin, "user.created", subject_id=u.id)
    await session.commit()
    return user_out(u)


@router.patch("/users/{user_id}", response_model=UserOut)
async def patch_user(user_id: uuid.UUID, body: UserPatch, admin: UserActor = Depends(current_admin),
                     session: AsyncSession = Depends(get_session)):
    u = await session.get(User, user_id)
    if u is None or u.org_id != admin.org_id:
        raise policy.not_found()
    changes = body.model_dump(exclude_unset=True)
    if "password" in changes:
        u.password_hash = hash_password(changes.pop("password"))
    for k, v in changes.items():
        setattr(u, k, v)
    if "name" in changes:
        u.initials = initials(u.name)
    audit(session, admin.org_id, admin, "user.changed", subject_id=u.id, fields=list(body.model_dump(exclude_unset=True)))
    await session.commit()
    return user_out(u)


class AdminChannelOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    partner_name: str
    member_ids: list[uuid.UUID]


@router.get("/channels", response_model=list[AdminChannelOut])
async def channels(admin: UserActor = Depends(current_admin), session: AsyncSession = Depends(get_session)):
    """Channel metadata and members. Admins don't get to read messages of channels they aren't in."""
    out = []
    for ch in await policy.all_channels_for_admin(session, admin):
        members = (await session.execute(select(ChannelMember.user_id).where(ChannelMember.channel_id == ch.id))).scalars().all()
        out.append(AdminChannelOut(id=ch.id, kind=ch.kind.value, name=ch.name, partner_name=ch.partner_name, member_ids=list(members)))
    return out


class AdminGuestOut(BaseModel):
    id: uuid.UUID
    name: str | None
    company: str
    channel_id: uuid.UUID
    channel_name: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    message_count: int


@router.get("/guests", response_model=list[AdminGuestOut])
async def guests(admin: UserActor = Depends(current_admin), session: AsyncSession = Depends(get_session)):
    chans = {c.id: c for c in await policy.all_channels_for_admin(session, admin)}
    rows = (await session.execute(select(Guest).where(Guest.channel_id.in_(list(chans))).order_by(Guest.created_at.desc()))).scalars().all()
    counts = dict((await session.execute(
        select(Message.author_guest_id, func.count()).where(Message.author_guest_id.in_([g.id for g in rows])).group_by(Message.author_guest_id)
    )).all()) if rows else {}
    return [AdminGuestOut(id=g.id, name=g.name, company=g.company, channel_id=g.channel_id, channel_name=chans[g.channel_id].name,
                          created_at=g.created_at, expires_at=g.expires_at, revoked_at=g.revoked_at, message_count=counts.get(g.id, 0))
            for g in rows]


async def _admin_guest(session, admin: UserActor, guest_id) -> Guest:
    g = await session.get(Guest, guest_id)
    if g is None:
        raise policy.not_found()
    await policy.channel_by_id_for_admin(session, admin, g.channel_id)
    return g


@router.get("/guests/{guest_id}/export")
async def export_guest(guest_id: uuid.UUID, admin: UserActor = Depends(current_admin), session: AsyncSession = Depends(get_session)):
    """Everything stored about one guest (GDPR Art. 15 / 20)."""
    g = await _admin_guest(session, admin, guest_id)
    msgs = await policy.guest_authored_messages(session, SystemActor(admin.org_id), g.id)
    events = (await session.execute(
        select(AuditEvent).where(or_(AuditEvent.actor_id == g.id, AuditEvent.subject_id == g.id)).order_by(AuditEvent.at)
    )).scalars()
    audit(session, admin.org_id, admin, "guest.exported", subject_id=g.id)
    await session.commit()
    return {
        "guest": {"id": str(g.id), "name": g.name, "company": g.company, "created_at": g.created_at.isoformat(),
                  "expires_at": g.expires_at.isoformat(), "revoked_at": g.revoked_at.isoformat() if g.revoked_at else None},
        "messages": [
            {"id": str(m.id), "created_at": m.created_at.isoformat(), "body": m.body,
             "copy_in_backroom": m.pulled_from_id is not None, "files": [a.filename for a in m.attachments]}
            for m in msgs
        ],
        "events": [{"at": e.at.isoformat(), "action": e.action} for e in events],
    }


@router.delete("/guests/{guest_id}")
async def delete_guest(guest_id: uuid.UUID, admin: UserActor = Depends(current_admin), session: AsyncSession = Depends(get_session),
                       state: AppState = Depends(get_state)):
    """Delete a guest with their messages, the backroom copies of them and their files."""
    g = await _admin_guest(session, admin, guest_id)
    count = await erase_guest(state, session, SystemActor(admin.org_id), g)
    audit(session, admin.org_id, admin, "guest.deleted", subject_id=guest_id, messages=count)
    await session.commit()
    await state.hub.close_guest(guest_id)
    return {"ok": True, "messages": count}


async def erase_guest(state, session: AsyncSession, actor: SystemActor, g: Guest) -> int:
    msgs = await policy.guest_authored_messages(session, actor, g.id)
    keys = {a.storage_key for m in msgs for a in m.attachments}
    keys |= set((await session.execute(select(Attachment.storage_key).where(Attachment.uploader_guest_id == g.id))).scalars())
    await session.execute(delete(Attachment).where(Attachment.uploader_guest_id == g.id))
    await session.execute(
        update(AuditEvent).where(AuditEvent.actor_id == g.id).values(actor_name="Deleted guest", details={})
    )
    await session.delete(g)  # messages, sessions and attachment rows cascade
    await session.flush()
    for key in keys:
        still = (await session.execute(select(Attachment.id).where(Attachment.storage_key == key))).first()
        if still is None:
            files.remove(state.settings.upload_dir, key)
    return len(msgs)


@router.post("/retention/run")
async def run_retention(admin: UserActor = Depends(current_admin), state: AppState = Depends(get_state)):
    return await apply_retention(state)


async def apply_retention(state) -> dict:
    """Delete what is older than the configured retention. Nothing is deleted when a value is empty."""
    result = {}
    async with state.db.sessions() as session:
        for org in (await session.execute(select(Organization))).scalars().all():
            r = org.retention or {}
            actor = SystemActor(org.id)
            now = utcnow()
            if r.get("shared_days"):
                result["shared"] = await policy.delete_messages_older_than(session, actor, [ChannelKind.shared], now - timedelta(days=r["shared_days"]))
            if r.get("internal_days"):
                result["internal"] = await policy.delete_messages_older_than(session, actor, list(INTERNAL_KINDS), now - timedelta(days=r["internal_days"]))
            if r.get("audit_days"):
                cut = now - timedelta(days=r["audit_days"])
                res = await session.execute(delete(AuditEvent).where(AuditEvent.org_id == org.id, AuditEvent.at < cut))
                await session.execute(delete(LlmCall).where(LlmCall.at < cut))
                result["audit"] = res.rowcount or 0
            if r.get("guest_days_after_expiry"):
                cut = now - timedelta(days=r["guest_days_after_expiry"])
                old = (await session.execute(select(Guest).where(or_(Guest.expires_at < cut, Guest.revoked_at < cut)))).scalars().all()
                for g in old:
                    await erase_guest(state, session, actor, g)
                result["guests"] = len(old)
            if result:
                audit(session, org.id, actor, "retention.applied", **result)
        await session.commit()
    return result

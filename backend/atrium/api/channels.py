import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import files, policy
from ..actors import UserActor
from ..db import utcnow
from ..deps import current_user, get_session, get_state
from ..guest import preview
from ..models import (
    Attachment,
    Channel,
    ChannelKind,
    ChannelMember,
    Guest,
    GuestSession,
    Message,
    ReadMarker,
    Room,
    User,
)
from ..schemas import ChannelOut, GuestInfoOut, MemberOut, MessageOut, PersonOut
from ..security import hash_token, new_token
from ..serialize import attachment_out, initials, messages_out
from ..services import messages as svc
from ..services.audit import audit
from ..state import AppState

router = APIRouter(prefix="/api", tags=["channels"])


async def channel_out(session, actor: UserActor, ch: Channel, *, detail: bool = False) -> ChannelOut:
    out = ChannelOut(id=ch.id, kind=ch.kind.value, name=ch.name, description=ch.description,
                     partner_name=ch.partner_name, backroom_for_id=ch.backroom_for_id)
    if ch.kind == ChannelKind.shared:
        br = await policy.backroom_of(session, actor, ch)
        out.backroom_id = br.id if br else None
    marker = await session.get(ReadMarker, (actor.user_id, ch.id))
    since = marker.last_read_at if marker else datetime(1970, 1, 1, tzinfo=utcnow().tzinfo)
    unread = await session.execute(
        select(func.count()).select_from(
            policy.readable_messages(actor)
            .where(Message.channel_id == ch.id, Message.created_at > since)
            .where((Message.author_user_id.is_(None)) | (Message.author_user_id != actor.user_id))
            .subquery()
        )
    )
    out.unread = unread.scalar_one()
    if detail:
        target = ch.backroom_for_id if ch.kind == ChannelKind.backroom else ch.id
        users = (
            await session.execute(
                select(User).join(ChannelMember, ChannelMember.user_id == User.id).where(ChannelMember.channel_id == target).order_by(User.name)
            )
        ).scalars()
        out.members = [MemberOut(kind="user", id=u.id, name=u.name, initials=u.initials, tone=u.tone, label=u.role_label) for u in users]
        if ch.kind == ChannelKind.shared:
            guests = (await session.execute(select(Guest).where(Guest.channel_id == ch.id).order_by(Guest.created_at))).scalars().all()
            now = utcnow()
            out.guests = [
                GuestInfoOut(id=g.id, name=g.name, company=g.company, expires_at=g.expires_at, revoked_at=g.revoked_at,
                             created_at=g.created_at, joined=g.name is not None)
                for g in guests
            ]
            out.members += [
                MemberOut(kind="guest", id=g.id, name=g.name, initials=initials(g.name), label=g.company or ch.partner_name)
                for g in guests if g.name and g.revoked_at is None and g.expires_at > now
            ]
        room = (await session.execute(select(Room).where(Room.channel_id == ch.id))).scalar_one_or_none()
        out.room_name = room.name if room else ""
    return out


@router.get("/users", response_model=list[PersonOut])
async def people(actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Directory of colleagues, for avatars in rooms and channel member pickers."""
    rows = (await session.execute(select(User).where(User.org_id == actor.org_id, User.is_active.is_(True)).order_by(User.name))).scalars()
    return [PersonOut(id=u.id, name=u.name, initials=u.initials, tone=u.tone, role_label=u.role_label) for u in rows]


@router.get("/channels", response_model=list[ChannelOut])
async def list_channels(actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return [await channel_out(session, actor, ch) for ch in await policy.list_channels(session, actor)]


@router.get("/channels/{channel_id}", response_model=ChannelOut)
async def get_channel(channel_id: uuid.UUID, actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await channel_out(session, actor, await policy.get_channel(session, actor, channel_id), detail=True)


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = "internal"
    description: str = ""
    partner_name: str = ""
    member_ids: list[uuid.UUID] = []


@router.post("/channels", response_model=ChannelOut)
async def create_channel(body: ChannelIn, actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if body.kind not in ("internal", "shared"):
        raise HTTPException(400, "kind is internal or shared")
    ch = Channel(org_id=actor.org_id, kind=ChannelKind(body.kind), name=body.name.strip(), description=body.description,
                 partner_name=body.partner_name.strip())
    session.add(ch)
    await session.flush()
    if ch.kind == ChannelKind.shared:
        # Every shared channel has exactly one backroom, created in the same transaction.
        session.add(Channel(org_id=actor.org_id, kind=ChannelKind.backroom, name=f"Backroom {ch.name}",
                            partner_name=ch.partner_name, backroom_for_id=ch.id))
    org_users = set((await session.execute(select(User.id).where(User.org_id == actor.org_id))).scalars())
    for uid in {actor.user_id, *body.member_ids} & org_users:
        session.add(ChannelMember(channel_id=ch.id, user_id=uid))
    audit(session, actor.org_id, actor, "channel.created", subject_id=ch.id, kind=ch.kind.value)
    await session.commit()
    return await channel_out(session, actor, ch, detail=True)


class MembersIn(BaseModel):
    user_ids: list[uuid.UUID]


@router.post("/channels/{channel_id}/members", response_model=ChannelOut)
async def add_members(channel_id: uuid.UUID, body: MembersIn, actor: UserActor = Depends(current_user),
                      session: AsyncSession = Depends(get_session), state: AppState = Depends(get_state)):
    try:
        ch = await policy.get_channel(session, actor, channel_id)
    except HTTPException:
        ch = await policy.channel_by_id_for_admin(session, actor, channel_id)
    if ch.kind == ChannelKind.backroom:
        raise HTTPException(400, "Backroom members follow the shared channel")
    org_users = set((await session.execute(select(User.id).where(User.org_id == actor.org_id))).scalars())
    for uid in set(body.user_ids) & org_users:
        if not await policy.is_member(session, uid, ch.id):
            session.add(ChannelMember(channel_id=ch.id, user_id=uid))
    audit(session, actor.org_id, actor, "channel.members_added", subject_id=ch.id, user_ids=[str(u) for u in body.user_ids])
    await session.commit()
    await state.hub.to_users(body.user_ids, {"type": "channels.updated"})
    return await channel_out(session, actor, ch, detail=True)


@router.get("/channels/{channel_id}/messages", response_model=list[MessageOut])
async def list_messages(channel_id: uuid.UUID, before: datetime | None = None, actor: UserActor = Depends(current_user),
                        session: AsyncSession = Depends(get_session), state: AppState = Depends(get_state)):
    ch = await policy.get_channel(session, actor, channel_id)
    msgs = await policy.channel_messages(session, actor, ch.id, before=before)
    return await messages_out(session, actor, msgs, partner_name=ch.partner_name, permissions=state.agent_permissions)


class MessageIn(BaseModel):
    body: str = ""
    attachment_ids: list[uuid.UUID] = []
    # Agent drafts this message sends. The person is the author; the drafts only travel along.
    draft_ids: list[uuid.UUID] = []
    draft_id: uuid.UUID | None = None


@router.post("/channels/{channel_id}/messages", response_model=MessageOut)
async def post_message(channel_id: uuid.UUID, body: MessageIn, actor: UserActor = Depends(current_user),
                       session: AsyncSession = Depends(get_session), state: AppState = Depends(get_state)):
    ch = await policy.get_channel(session, actor, channel_id)
    msg = await svc.post_message(state, session, actor, ch, body.body, attachment_ids=body.attachment_ids,
                                 draft_ids=body.draft_ids + ([body.draft_id] if body.draft_id else []))
    msg = await policy.get_message(session, actor, msg.id)
    [out] = await messages_out(session, actor, [msg], partner_name=ch.partner_name, permissions=state.agent_permissions)
    return out


@router.post("/channels/{channel_id}/read")
async def mark_read(channel_id: uuid.UUID, actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session)):
    ch = await policy.get_channel(session, actor, channel_id)
    marker = await session.get(ReadMarker, (actor.user_id, ch.id))
    if marker is None:
        session.add(ReadMarker(user_id=actor.user_id, channel_id=ch.id))
    else:
        marker.last_read_at = utcnow()
    await session.commit()
    return {"ok": True}


class PullIn(BaseModel):
    note: str = ""


@router.post("/messages/{message_id}/pull", response_model=MessageOut)
async def pull(message_id: uuid.UUID, body: PullIn | None = None, actor: UserActor = Depends(current_user),
               session: AsyncSession = Depends(get_session), state: AppState = Depends(get_state)):
    copy = await svc.pull_message(state, session, actor, message_id, (body.note if body else ""))
    copy = await policy.get_message(session, actor, copy.id)
    [out] = await messages_out(session, actor, [copy], permissions=state.agent_permissions)
    return out


# ---------------------------------------------------------------- files


@router.post("/files")
async def upload(file: UploadFile, actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session),
                 state: AppState = Depends(get_state)):
    a = await store_upload(state, file, uploader_user_id=actor.user_id)
    session.add(a)
    await session.commit()
    return attachment_out(a)


async def store_upload(state: AppState, file: UploadFile, **owner) -> Attachment:
    limit = state.settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"Files can be up to {state.settings.max_upload_mb} MB")
    mime = (file.content_type or "application/octet-stream").split(";")[0]
    if mime not in files.ALLOWED_MIME:
        raise HTTPException(415, "This file type isn't supported")
    key, sha = files.store(state.settings.upload_dir, data)
    name = (file.filename or "file").replace("/", "_")[:255]
    return Attachment(filename=name, mime=mime, size=len(data), sha256=sha, storage_key=key, **owner)


@router.get("/files/{attachment_id}")
async def download(attachment_id: uuid.UUID, actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session),
                   state: AppState = Depends(get_state)):
    a = await session.get(Attachment, attachment_id)
    if a is None:
        raise policy.not_found()
    if a.message_id is not None:
        await policy.get_message(session, actor, a.message_id)
    elif a.draft_id is not None:
        await svc.get_draft(session, actor, a.draft_id)
    elif a.uploader_user_id != actor.user_id:
        raise policy.not_found()
    return FileResponse(files.path_for(state.settings.upload_dir, a.storage_key), media_type=a.mime, filename=a.filename)


# ---------------------------------------------------------------- guests


class InviteIn(BaseModel):
    name: str = ""
    company: str = ""
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class InviteOut(BaseModel):
    guest: GuestInfoOut
    link: str


@router.post("/channels/{channel_id}/guests", response_model=InviteOut)
async def invite(channel_id: uuid.UUID, body: InviteIn, actor: UserActor = Depends(current_user),
                 session: AsyncSession = Depends(get_session), state: AppState = Depends(get_state)):
    ch = await policy.get_channel(session, actor, channel_id)
    if ch.kind != ChannelKind.shared:
        raise HTTPException(400, "Guests can only join shared channels")
    token = new_token()
    days = body.expires_in_days or state.settings.guest_link_days
    g = Guest(channel_id=ch.id, name=None, company=body.company.strip(), token_hash=hash_token(token),
              expires_at=utcnow() + timedelta(days=days), invited_by_id=actor.user_id)
    session.add(g)
    await session.flush()
    audit(session, actor.org_id, actor, "guest.invited", subject_id=g.id, channel_id=ch.id, suggested_name=body.name.strip(),
          expires_at=g.expires_at.isoformat())
    await session.commit()
    link = f"{state.settings.base_url.rstrip('/')}/g/{token}"
    if body.name.strip():
        link += "#name=" + body.name.strip().replace(" ", "%20")
    info = GuestInfoOut(id=g.id, name=g.name, company=g.company, expires_at=g.expires_at, revoked_at=None, created_at=g.created_at, joined=False)
    return InviteOut(guest=info, link=link)


@router.delete("/guests/{guest_id}")
async def revoke(guest_id: uuid.UUID, actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session),
                 state: AppState = Depends(get_state)):
    g = await policy.guest_for_channel(session, actor, guest_id)
    if g.revoked_at is None:
        g.revoked_at = utcnow()
        from sqlalchemy import delete

        await session.execute(delete(GuestSession).where(GuestSession.guest_id == g.id))
        audit(session, actor.org_id, actor, "guest.revoked", subject_id=g.id, channel_id=g.channel_id)
        await session.commit()
    await state.hub.close_guest(g.id)
    return {"ok": True}


@router.post("/guests/{guest_id}/preview")
async def preview_token(guest_id: uuid.UUID, actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session)):
    g = await policy.guest_for_channel(session, actor, guest_id)
    return {"token": preview.issue(g.id), "expires_in": preview.TTL}

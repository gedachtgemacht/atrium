"""Guest API under /g. Every response model comes from atrium.guest.schemas."""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import files, policy
from ..actors import GuestActor
from ..db import utcnow
from ..deps import GUEST_COOKIE, csrf, current_guest, get_session, get_state
from ..models import Attachment, Channel, ChannelMember, Guest, GuestSession, Organization, User
from ..security import hash_token, new_token
from ..serialize import initials
from ..services import messages as svc
from ..services.audit import audit
from ..state import AppState
from .schemas import GuestAuthor, GuestChannel, GuestFile, GuestJoinInfo, GuestMe, GuestMessage
from .serialize import guest_file, guest_message

router = APIRouter(prefix="/g/api", tags=["guest"])

NOTICE = (
    "Only people from {org} write here. Messages are stored on their server{where}. "
    "{org} may work on single messages internally with AI."
)


async def _invite(session: AsyncSession, token: str) -> Guest:
    g = (await session.execute(select(Guest).where(Guest.token_hash == hash_token(token)))).scalar_one_or_none()
    if g is None or g.revoked_at is not None or g.expires_at <= utcnow():
        raise HTTPException(401, "This link is no longer valid")
    return g


async def _org(session: AsyncSession) -> Organization:
    return (await session.execute(select(Organization).limit(1))).scalar_one()


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


@router.post("/join-info", response_model=GuestJoinInfo, dependencies=[Depends(csrf)])
async def join_info(body: TokenIn, session: AsyncSession = Depends(get_session)):
    g = await _invite(session, body.token)
    org = await _org(session)
    return GuestJoinInfo(company_name=org.name, needs_name=g.name is None, suggested_name="")


class JoinIn(TokenIn):
    name: str = Field(default="", max_length=120)


@router.post("/session", response_model=GuestMe, dependencies=[Depends(csrf)])
async def join(body: JoinIn, response: Response, session: AsyncSession = Depends(get_session), state: AppState = Depends(get_state)):
    """The link is the credential. First open sets the name; later opens on any device reuse it."""
    g = await _invite(session, body.token)
    first = g.name is None
    if first:
        name = " ".join(body.name.split())
        if len(name) < 2:
            raise HTTPException(400, "Please enter your name")
        g.name = name
    token = new_token()
    expires = min(g.expires_at, utcnow() + timedelta(days=30))
    session.add(GuestSession(token_hash=hash_token(token), guest_id=g.id, expires_at=expires))
    actor = GuestActor(guest_id=g.id, channel_id=g.channel_id, name=g.name)
    ch = await _channel(session, actor)
    org = await _org(session)
    audit(session, org.id, actor, "guest.joined" if first else "guest.signed_in", subject_id=g.id, channel_id=ch.id)
    await session.commit()
    response.set_cookie(GUEST_COOKIE, token, httponly=True, samesite="lax", secure=state.settings.cookie_secure,
                        max_age=int((expires - utcnow()).total_seconds()), path="/g")
    if first:
        await _members_changed(state, session, ch)
    return GuestMe(id=g.id, name=g.name, company=g.company, preview=False)


@router.get("/me", response_model=GuestMe)
async def me(guest: GuestActor = Depends(current_guest), session: AsyncSession = Depends(get_session)):
    g = await session.get(Guest, guest.guest_id)
    return GuestMe(id=g.id, name=g.name or "Guest", company=g.company, preview=guest.read_only)


async def _members(session: AsyncSession, ch: Channel) -> list[GuestAuthor]:
    staff = (
        await session.execute(
            select(User).join(ChannelMember, ChannelMember.user_id == User.id).where(ChannelMember.channel_id == ch.id).order_by(User.name)
        )
    ).scalars()
    now = utcnow()
    guests = (
        await session.execute(
            select(Guest).where(Guest.channel_id == ch.id, Guest.name.is_not(None), Guest.revoked_at.is_(None), Guest.expires_at > now)
            .order_by(Guest.created_at)
        )
    ).scalars()
    return [GuestAuthor(kind="staff", id=u.id, name=u.name, initials=u.initials) for u in staff] + [
        GuestAuthor(kind="guest", id=g.id, name=g.name, initials=initials(g.name)) for g in guests
    ]


async def _channel(session: AsyncSession, guest: GuestActor) -> Channel:
    ch = await policy.get_channel(session, guest, guest.channel_id)
    policy.guest_visible_channel(guest, ch)
    return ch


async def _members_changed(state, session, ch: Channel) -> None:
    from .schemas import GuestEvent

    ev = GuestEvent(type="members.updated", members=await _members(session, ch))
    await state.hub.to_guests_of(ch.id, ev.model_dump(mode="json"))
    await state.hub.to_users(await policy.reader_user_ids(session, ch), {"type": "channels.updated"})


@router.get("/channel", response_model=GuestChannel)
async def channel(guest: GuestActor = Depends(current_guest), session: AsyncSession = Depends(get_session)):
    ch = await _channel(session, guest)
    org = await _org(session)
    where = f" in {org.server_location}" if org.server_location else ""
    return GuestChannel(company_name=org.name, partner_name=ch.partner_name, notice=NOTICE.format(org=org.name, where=where),
                        members=await _members(session, ch))


@router.get("/messages", response_model=list[GuestMessage])
async def messages(before: datetime | None = None, guest: GuestActor = Depends(current_guest), session: AsyncSession = Depends(get_session)):
    ch = await _channel(session, guest)
    rows = await policy.channel_messages(session, guest, ch.id, before=before)
    return [guest_message(ch, m) for m in rows]


class GuestMessageIn(BaseModel):
    body: str = ""
    attachment_ids: list[uuid.UUID] = []


@router.post("/messages", response_model=GuestMessage)
async def post(body: GuestMessageIn, guest: GuestActor = Depends(current_guest), session: AsyncSession = Depends(get_session),
               state: AppState = Depends(get_state)):
    ch = await _channel(session, guest)
    msg = await svc.post_message(state, session, guest, ch, body.body, attachment_ids=body.attachment_ids)
    return guest_message(ch, await policy.get_message(session, guest, msg.id))


@router.post("/files", response_model=GuestFile)
async def upload(file: UploadFile, guest: GuestActor = Depends(current_guest), session: AsyncSession = Depends(get_session),
                 state: AppState = Depends(get_state)):
    from ..api.channels import store_upload

    a = await store_upload(state, file, uploader_guest_id=guest.guest_id)
    session.add(a)
    await session.commit()
    return guest_file(a)


@router.get("/files/{attachment_id}")
async def download(attachment_id: uuid.UUID, guest: GuestActor = Depends(current_guest), session: AsyncSession = Depends(get_session),
                   state: AppState = Depends(get_state)):
    a = await session.get(Attachment, attachment_id)
    if a is None:
        raise policy.not_found()
    if a.message_id is not None:
        msg = await policy.get_message(session, guest, a.message_id)  # only messages in the guest's shared channel
        if msg.channel_id != guest.channel_id:
            raise policy.not_found()
    elif a.uploader_guest_id != guest.guest_id:
        raise policy.not_found()  # draft files and other people's uploads
    return FileResponse(files.path_for(state.settings.upload_dir, a.storage_key), media_type=a.mime, filename=a.filename)

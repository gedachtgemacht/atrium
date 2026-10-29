"""FastAPI dependencies: database session, internal user, guest."""

from collections.abc import AsyncIterator
from datetime import timedelta

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .actors import GuestActor, UserActor
from .db import utcnow
from .models import Guest, GuestSession, User, UserSession
from .security import hash_token
from .state import AppState

USER_COOKIE = "atrium_session"
GUEST_COOKIE = "atrium_guest"


def get_state(request: Request) -> AppState:
    return request.app.state.atrium


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.atrium.db.sessions() as s:
        yield s


def csrf(request: Request, x_requested_with: str | None = Header(default=None)) -> None:
    """State changing requests must come from our own frontend (custom header, SameSite cookie)."""
    if request.method not in ("GET", "HEAD", "OPTIONS") and x_requested_with != "atrium":
        raise HTTPException(403, "Missing X-Requested-With header")


async def user_from_token(session: AsyncSession, token: str | None) -> tuple[UserActor, User] | None:
    if not token:
        return None
    row = (
        await session.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == hash_token(token), UserSession.expires_at > utcnow(), User.is_active.is_(True))
        )
    ).first()
    if row is None:
        return None
    _, user = row
    return UserActor(user_id=user.id, org_id=user.org_id, name=user.name, is_admin=user.is_admin), user


async def current_user(
    session: AsyncSession = Depends(get_session),
    atrium_session: str | None = Cookie(default=None),
    _: None = Depends(csrf),
) -> UserActor:
    found = await user_from_token(session, atrium_session)
    if found is None:
        raise HTTPException(401, "Not signed in")
    return found[0]


async def current_admin(user: UserActor = Depends(current_user)) -> UserActor:
    if not user.is_admin:
        raise HTTPException(403, "Admins only")
    return user


async def guest_from_token(session: AsyncSession, token: str | None) -> GuestActor | None:
    """Guest cookie session, or a preview token ("View as Sarah", read only)."""
    if not token:
        return None
    now = utcnow()
    row = (
        await session.execute(
            select(GuestSession, Guest)
            .join(Guest, Guest.id == GuestSession.guest_id)
            .where(GuestSession.token_hash == hash_token(token), GuestSession.expires_at > now)
        )
    ).first()
    if row is not None:
        gs, guest = row
        if guest.revoked_at is None and guest.expires_at > now and guest.name:
            return GuestActor(guest_id=guest.id, channel_id=guest.channel_id, name=guest.name)
        return None
    from .guest.preview import resolve_preview

    return await resolve_preview(session, token)


async def current_guest(
    request: Request,
    session: AsyncSession = Depends(get_session),
    atrium_guest: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    _: None = Depends(csrf),
) -> GuestActor:
    token = atrium_guest
    if authorization and authorization.lower().startswith("preview "):
        token = authorization[8:].strip()
    guest = await guest_from_token(session, token)
    if guest is None:
        raise HTTPException(401, "This link is no longer valid")
    if guest.read_only and request.method not in ("GET", "HEAD"):
        raise HTTPException(403, "Preview is read only")
    return guest


def session_expiry(days: int):
    return utcnow() + timedelta(days=days)

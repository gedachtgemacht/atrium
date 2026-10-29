from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..actors import UserActor
from ..deps import USER_COOKIE, csrf, current_user, get_session, get_state, session_expiry
from ..models import Organization, User, UserSession
from ..schemas import MeOut
from ..security import hash_token, new_token, verify_password
from ..state import AppState

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login", response_model=MeOut, dependencies=[Depends(csrf)])
async def login(body: LoginIn, response: Response, session: AsyncSession = Depends(get_session), state: AppState = Depends(get_state)):
    user = (await session.execute(select(User).where(User.email == body.email.strip().lower()))).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(user.password_hash, body.password):
        raise HTTPException(401, "Email or password is wrong")
    token = new_token()
    session.add(UserSession(token_hash=hash_token(token), user_id=user.id, expires_at=session_expiry(state.settings.session_days)))
    await session.commit()
    response.set_cookie(USER_COOKIE, token, httponly=True, samesite="lax", secure=state.settings.cookie_secure,
                        max_age=state.settings.session_days * 86400, path="/")
    return await me_out(session, user)


@router.post("/logout", dependencies=[Depends(csrf)])
async def logout(response: Response, atrium_session: str | None = Cookie(default=None), session: AsyncSession = Depends(get_session)):
    if atrium_session:
        await session.execute(delete(UserSession).where(UserSession.token_hash == hash_token(atrium_session)))
        await session.commit()
    response.delete_cookie(USER_COOKIE, path="/")
    return {"ok": True}


async def me_out(session: AsyncSession, user: User) -> MeOut:
    org = await session.get(Organization, user.org_id)
    return MeOut(id=user.id, name=user.name, initials=user.initials, tone=user.tone, email=user.email,
                 role_label=user.role_label, is_admin=user.is_admin, org_name=org.name, server_location=org.server_location,
                 locale=user.locale, language=user.locale or org.language, org_language=org.language,
                 notify_email=user.notify_email)


me_router = APIRouter(prefix="/api", tags=["me"])


class PrefsIn(BaseModel):
    locale: str | None = None
    notify_email: bool | None = None


@me_router.patch("/me", response_model=MeOut, dependencies=[Depends(csrf)])
async def prefs(body: PrefsIn, actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session)):
    from ..i18n import LANGUAGES

    user = await session.get(User, actor.user_id)
    if body.locale is not None:
        user.locale = body.locale if body.locale in LANGUAGES else ""
    if body.notify_email is not None:
        user.notify_email = body.notify_email
    await session.commit()
    return await me_out(session, user)


@me_router.get("/me", response_model=MeOut)
async def me(actor: UserActor = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await me_out(session, await session.get(User, actor.user_id))

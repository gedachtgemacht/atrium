"""WebSockets. /ws for people, /g/ws for guests. Room presence travels only here, never over HTTP."""

import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..deps import GUEST_COOKIE, USER_COOKIE, guest_from_token, user_from_token
from ..models import Room
from ..realtime.hub import Connection
from ..rooms.livekit import access_token

router = APIRouter()


def _same_origin(ws: WebSocket, state) -> bool:
    origin = ws.headers.get("origin")
    if not origin:
        return True
    host = ws.headers.get("host", "")
    return origin.split("://", 1)[-1] == host or origin.rstrip("/") == state.settings.base_url.rstrip("/")


@router.websocket("/ws")
async def user_socket(ws: WebSocket):
    state = ws.app.state.atrium
    if not _same_origin(ws, state):
        await ws.close(code=4403)
        return
    async with state.db.sessions() as session:
        found = await user_from_token(session, ws.cookies.get(USER_COOKIE))
    if found is None:
        await ws.close(code=4401)
        return
    actor, user = found
    await ws.accept()
    conn = Connection(ws=ws, actor=actor)
    first = actor.user_id not in state.hub.users
    state.hub.add(conn)
    presence = state.presence
    await conn.send(presence.snapshot(state.hub.online_user_ids()))
    if first:
        await broadcast_presence(state)
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                room = presence.room_of(actor.user_id)
                if room is not None:
                    person = room.people.get(actor.user_id)
                    if person and not person.muted:
                        state.notes.feed(room.id, actor.user_id, actor.name, msg["bytes"])
                continue
            try:
                data = json.loads(msg.get("text") or "{}")
            except ValueError:
                continue
            await handle(state, conn, user, data)
    except WebSocketDisconnect:
        pass
    finally:
        state.hub.remove(conn)
        if actor.user_id not in state.hub.users:
            left = presence.leave(actor.user_id)
            if left is not None:
                await after_leave(state, left)
            await broadcast_presence(state)


async def broadcast_presence(state) -> None:
    await state.hub.to_all_users(state.presence.snapshot(state.hub.online_user_ids()))


async def after_leave(state, room) -> None:
    if not room.people and room.notes_by_id:
        room.notes_by_id, room.notes_by_name = None, ""
        state.tasks.spawn(state.notes.stop(room.id), name="notes:stop")


async def handle(state, conn: Connection, user, data: dict) -> None:
    kind = data.get("type")
    presence = state.presence
    actor = conn.actor
    if kind == "ping":
        await conn.send({"type": "pong"})
    elif kind == "room.join":
        try:
            room_id = uuid.UUID(str(data.get("room_id")))
            target = presence.rooms[room_id]
        except (ValueError, KeyError):
            await conn.send({"type": "error", "detail": "No such room"})
            return
        if target.members_only and not await may_enter(state, actor.user_id, target.channel_id):
            await conn.send({"type": "error", "detail": "Only members of this room's channel can go in"})
            return
        left, room = presence.join(actor.user_id, actor.name, room_id)
        if left is not None and left.id != room.id:
            await after_leave(state, left)
        await broadcast_presence(state)
        s = state.settings
        if room.kind == "normal" and s.livekit_url and s.livekit_api_key:
            token = access_token(s.livekit_api_key, s.livekit_api_secret, identity=str(actor.user_id), name=actor.name, room=f"atrium-{room.id}")
            await conn.send({"type": "room.voice", "room_id": str(room.id), "url": s.livekit_url, "token": token})
        else:
            await conn.send({"type": "room.voice", "room_id": str(room.id), "url": "", "token": ""})
    elif kind == "room.leave":
        left = presence.leave(actor.user_id)
        if left is not None:
            await after_leave(state, left)
        await broadcast_presence(state)
    elif kind == "room.mute":
        presence.set_muted(actor.user_id, bool(data.get("muted")))
        await broadcast_presence(state)
    elif kind == "room.notes":
        room = presence.room_of(actor.user_id)
        if room is None or room.kind != "normal" or room.channel_id is None:
            return
        if data.get("on"):
            if not room.notes_by_id:
                room.notes_by_id, room.notes_by_name = actor.user_id, actor.name
                state.notes.start(room.id, actor.name, await colleague_names(state, actor.org_id),
                                  room_name=room.name, channel_id=room.channel_id)
        elif room.notes_by_id:
            room.notes_by_id, room.notes_by_name = None, ""
            state.tasks.spawn(state.notes.stop(room.id), name="notes:stop")
        await broadcast_presence(state)


async def may_enter(state, user_id, channel_id) -> bool:
    from .. import policy

    if channel_id is None:
        return False
    async with state.db.sessions() as session:
        return await policy.is_member(session, user_id, channel_id)


async def colleague_names(state, org_id) -> list[str]:
    from ..models import User

    async with state.db.sessions() as session:
        rows = await session.execute(select(User.name).where(User.org_id == org_id, User.is_active.is_(True)).limit(200))
        return list(rows.scalars())


async def load_rooms(state):
    async with state.db.sessions() as session:
        return state.presence.configure((await session.execute(select(Room))).scalars().all())


@router.websocket("/g/ws")
async def guest_socket(ws: WebSocket):
    state = ws.app.state.atrium
    if not _same_origin(ws, state):
        await ws.close(code=4403)
        return
    token = ws.cookies.get(GUEST_COOKIE)
    preview = ws.query_params.get("preview")
    async with state.db.sessions() as session:
        guest = await guest_from_token(session, preview or token)
    if guest is None:
        await ws.close(code=4401)
        return
    await ws.accept()
    conn = Connection(ws=ws, actor=guest)
    state.hub.add(conn)
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            # Guests only listen. Anything they send over the socket is ignored.
    except WebSocketDisconnect:
        pass
    finally:
        state.hub.remove(conn)

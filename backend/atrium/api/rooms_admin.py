"""Floor plans and rooms. Admins shape them to the company: floors or sites, rooms on a grid,
talk rooms, quiet rooms, one hallway, rooms only a department can enter.

Only configuration lives here. Who is in a room stays in memory (atrium.rooms.presence).
"""

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import policy
from ..actors import UserActor
from ..deps import current_admin, get_session, get_state
from ..models import ChannelKind, ChannelMember, Organization, Room, RoomKind
from ..schemas import FloorOut, RoomOut, RoomsOut
from ..services.audit import audit
from ..state import AppState

router = APIRouter(prefix="/api/admin", tags=["rooms"])

MAX_COLUMNS = 6
MAX_ROWS = 12


def floors_of(org: Organization) -> list[dict]:
    return org.floors or [{"id": "main", "name": "Office", "columns": 2}]


async def rooms_out(session: AsyncSession, actor: UserActor) -> RoomsOut:
    org = await session.get(Organization, actor.org_id)
    rows = (await session.execute(select(Room).where(Room.org_id == actor.org_id).order_by(Room.floor_id, Room.row, Room.col))).scalars().all()
    channels = {c.id: c for c in await policy.all_channels_for_admin(session, actor)} if actor.is_admin else {
        c.id: c for c in await policy.list_channels(session, actor)}
    mine = set((await session.execute(select(ChannelMember.channel_id).where(ChannelMember.user_id == actor.user_id))).scalars())
    out = []
    for r in rows:
        ch = channels.get(r.channel_id)
        out.append(RoomOut(
            id=r.id, name=r.name, kind=r.kind.value, floor_id=r.floor_id, col=r.col, row=r.row, col_span=r.col_span,
            row_span=r.row_span, channel_id=r.channel_id, channel_name=ch.name if ch else "", members_only=r.members_only,
            can_enter=(not r.members_only) or (r.channel_id in mine),
        ))
    return RoomsOut(floors=[FloorOut(**f) for f in floors_of(org)], rooms=out)


class FloorIn(BaseModel):
    id: str = Field(default="", max_length=40)
    name: str = Field(min_length=1, max_length=100)
    columns: int = Field(ge=1, le=MAX_COLUMNS)


class FloorsIn(BaseModel):
    floors: list[FloorIn] = Field(min_length=1, max_length=20)


class RoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str = "normal"
    floor_id: str = "main"
    col: int = Field(default=0, ge=0, lt=MAX_COLUMNS)
    row: int = Field(default=0, ge=0, lt=MAX_ROWS)
    col_span: int = Field(default=1, ge=1, le=MAX_COLUMNS)
    row_span: int = Field(default=1, ge=1, le=4)
    channel_id: uuid.UUID | None = None
    members_only: bool = False


def slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "floor"
    s, n = base, 2
    while s in taken:
        s, n = f"{base}-{n}", n + 1
    return s


async def _validate(session: AsyncSession, actor: UserActor, org: Organization, body: RoomIn, room_id=None) -> None:
    floors = {f["id"]: f for f in floors_of(org)}
    floor = floors.get(body.floor_id)
    if floor is None:
        raise HTTPException(400, "That floor doesn't exist")
    if body.col + body.col_span > floor["columns"]:
        raise HTTPException(400, f"The room doesn't fit: {floor['name']} has {floor['columns']} columns")
    try:
        kind = RoomKind(body.kind)
    except ValueError:
        raise HTTPException(400, "kind is normal, quiet or hallway")
    if kind == RoomKind.hallway and (body.channel_id or body.members_only):
        raise HTTPException(400, "The hallway has no channel and is open to everybody")
    if kind == RoomKind.quiet and body.channel_id:
        raise HTTPException(400, "A quiet room has no notes, so it needs no channel")
    if body.members_only and not body.channel_id:
        raise HTTPException(400, "Pick the channel whose members may enter")
    if body.channel_id:
        ch = await policy.channel_by_id_for_admin(session, actor, body.channel_id)
        if ch.kind != ChannelKind.internal:
            raise HTTPException(400, "Room notes go to an internal channel, never to a customer channel")
    others = (await session.execute(select(Room).where(Room.org_id == org.id))).scalars().all()
    for r in others:
        if r.id == room_id:
            continue
        if kind == RoomKind.hallway and r.kind == RoomKind.hallway:
            raise HTTPException(400, f"There is already a hallway ({r.name})")
        if r.name.lower() == body.name.strip().lower():
            raise HTTPException(400, "Another room has this name")
        if r.floor_id == body.floor_id and not (
            body.col + body.col_span <= r.col or r.col + r.col_span <= body.col
            or body.row + body.row_span <= r.row or r.row + r.row_span <= body.row
        ):
            raise HTTPException(400, f"That spot overlaps {r.name}")


@router.get("/rooms", response_model=RoomsOut)
async def admin_rooms(admin: UserActor = Depends(current_admin), session: AsyncSession = Depends(get_session)):
    return await rooms_out(session, admin)


@router.put("/floors", response_model=RoomsOut)
async def put_floors(body: FloorsIn, admin: UserActor = Depends(current_admin), session: AsyncSession = Depends(get_session),
                     state: AppState = Depends(get_state)):
    org = await session.get(Organization, admin.org_id)
    taken: set[str] = set()
    floors = []
    for f in body.floors:
        fid = f.id or slug(f.name, taken | {x["id"] for x in floors_of(org)})
        if fid in taken:
            raise HTTPException(400, "Two floors share an id")
        taken.add(fid)
        floors.append({"id": fid, "name": f.name.strip(), "columns": f.columns})
    rooms = (await session.execute(select(Room).where(Room.org_id == org.id))).scalars().all()
    widths = {f["id"]: f["columns"] for f in floors}
    for r in rooms:
        if r.floor_id not in widths:
            raise HTTPException(400, f"Move or delete the rooms on that floor first ({r.name})")
        if r.col + r.col_span > widths[r.floor_id]:
            raise HTTPException(400, f"{r.name} wouldn't fit any more. Move it first")
    org.floors = floors
    audit(session, org.id, admin, "rooms.floors_changed", floors=[f["name"] for f in floors])
    await session.commit()
    await rooms_changed(state)
    return await rooms_out(session, admin)


@router.post("/rooms", response_model=RoomsOut)
async def create_room(body: RoomIn, admin: UserActor = Depends(current_admin), session: AsyncSession = Depends(get_session),
                      state: AppState = Depends(get_state)):
    org = await session.get(Organization, admin.org_id)
    await _validate(session, admin, org, body)
    r = Room(org_id=org.id, **(body.model_dump() | {"name": body.name.strip(), "kind": RoomKind(body.kind)}))
    session.add(r)
    await session.flush()
    audit(session, org.id, admin, "rooms.created", subject_id=r.id, name=r.name)
    await session.commit()
    await rooms_changed(state)
    return await rooms_out(session, admin)


@router.put("/rooms/{room_id}", response_model=RoomsOut)
async def update_room(room_id: uuid.UUID, body: RoomIn, admin: UserActor = Depends(current_admin),
                      session: AsyncSession = Depends(get_session), state: AppState = Depends(get_state)):
    org = await session.get(Organization, admin.org_id)
    r = await session.get(Room, room_id)
    if r is None or r.org_id != org.id:
        raise policy.not_found()
    await _validate(session, admin, org, body, room_id=r.id)
    for k, v in (body.model_dump() | {"name": body.name.strip(), "kind": RoomKind(body.kind)}).items():
        setattr(r, k, v)
    audit(session, org.id, admin, "rooms.changed", subject_id=r.id, name=r.name)
    await session.commit()
    await rooms_changed(state)
    return await rooms_out(session, admin)


@router.delete("/rooms/{room_id}", response_model=RoomsOut)
async def delete_room(room_id: uuid.UUID, admin: UserActor = Depends(current_admin), session: AsyncSession = Depends(get_session),
                      state: AppState = Depends(get_state)):
    r = await session.get(Room, room_id)
    if r is None or r.org_id != admin.org_id:
        raise policy.not_found()
    await session.delete(r)
    audit(session, admin.org_id, admin, "rooms.deleted", subject_id=room_id, name=r.name)
    await session.commit()
    await rooms_changed(state)
    return await rooms_out(session, admin)


async def rooms_changed(state) -> None:
    """Reload the plan into presence. People in a deleted room land in the hallway; running notes there end."""
    from .ws import broadcast_presence, load_rooms

    removed = await load_rooms(state)
    for room in removed:
        if room.notes_by_id:
            state.tasks.spawn(state.notes.stop(room.id), name="notes:stop")
    await state.hub.to_all_users({"type": "rooms.updated"})
    await broadcast_presence(state)

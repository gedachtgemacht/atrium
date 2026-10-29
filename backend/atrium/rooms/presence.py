"""Who is in which room. In memory only.

Nothing in this module touches the database or a logger with a person and a
room together. When the process restarts, everybody is back in the hallway.
"""

import uuid
from dataclasses import dataclass, field


@dataclass
class Person:
    user_id: uuid.UUID
    name: str
    muted: bool = False


@dataclass
class RoomState:
    id: uuid.UUID
    name: str
    kind: str
    channel_id: uuid.UUID | None
    members_only: bool = False
    people: dict[uuid.UUID, Person] = field(default_factory=dict)
    notes_by_id: uuid.UUID | None = None
    notes_by_name: str = ""


class Presence:
    def __init__(self):
        self.rooms: dict[uuid.UUID, RoomState] = {}
        self.where: dict[uuid.UUID, uuid.UUID] = {}

    def configure(self, rooms) -> list[RoomState]:
        """Apply the floor plan. The hallway is not a room you are "in". Returns rooms that are gone."""
        wanted = {r.id: r for r in rooms if r.kind.value != "hallway"}
        removed = []
        for rid in list(self.rooms):
            if rid not in wanted:
                gone = self.rooms.pop(rid)
                for uid in list(gone.people):
                    self.where.pop(uid, None)
                removed.append(gone)
        for r in wanted.values():
            st = self.rooms.get(r.id)
            if st is None:
                self.rooms[r.id] = RoomState(id=r.id, name=r.name, kind=r.kind.value, channel_id=r.channel_id,
                                             members_only=r.members_only)
            else:
                st.name, st.channel_id, st.members_only = r.name, r.channel_id, r.members_only
                if st.kind != r.kind.value:
                    st.kind = r.kind.value
                    st.notes_by_id, st.notes_by_name = None, ""
        return removed

    def room_of(self, user_id: uuid.UUID) -> RoomState | None:
        rid = self.where.get(user_id)
        return self.rooms.get(rid) if rid else None

    def join(self, user_id: uuid.UUID, name: str, room_id: uuid.UUID) -> tuple[RoomState | None, RoomState]:
        """Returns (room left, room joined)."""
        room = self.rooms.get(room_id)
        if room is None:
            raise KeyError("no such room")
        left = self.leave(user_id)
        room.people[user_id] = Person(user_id=user_id, name=name, muted=(room.kind == "quiet"))
        self.where[user_id] = room.id
        return left, room

    def leave(self, user_id: uuid.UUID) -> RoomState | None:
        rid = self.where.pop(user_id, None)
        if rid is None:
            return None
        room = self.rooms[rid]
        room.people.pop(user_id, None)
        return room

    def set_muted(self, user_id: uuid.UUID, muted: bool) -> RoomState | None:
        room = self.room_of(user_id)
        if room and user_id in room.people:
            room.people[user_id].muted = muted
        return room

    def rooms_with_notes(self) -> list[str]:
        return [r.name for r in self.rooms.values() if r.notes_by_id]

    def snapshot(self, online: set[uuid.UUID]) -> dict:
        return {
            "type": "presence.state",
            "online": [str(u) for u in online],
            "rooms": [
                {
                    "id": str(r.id),
                    "people": [{"user_id": str(p.user_id), "muted": p.muted} for p in r.people.values()],
                    "notes_by_id": str(r.notes_by_id) if r.notes_by_id else None,
                    "notes_by_name": r.notes_by_name,
                }
                for r in self.rooms.values()
            ],
        }

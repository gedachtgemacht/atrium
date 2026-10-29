"""WebSocket fanout. Recipients are always decided by atrium.policy before anything is sent."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

from ..actors import GuestActor, UserActor

log = logging.getLogger("atrium.hub")


@dataclass(eq=False)
class Connection:
    ws: WebSocket
    actor: UserActor | GuestActor
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, event: dict) -> None:
        async with self.lock:
            await self.ws.send_json(event)


class Hub:
    def __init__(self):
        self.users: dict[uuid.UUID, set[Connection]] = {}
        self.guests: dict[uuid.UUID, set[Connection]] = {}

    def add(self, conn: Connection) -> None:
        if isinstance(conn.actor, UserActor):
            self.users.setdefault(conn.actor.user_id, set()).add(conn)
        else:
            self.guests.setdefault(conn.actor.guest_id, set()).add(conn)

    def remove(self, conn: Connection) -> None:
        bucket = self.users if isinstance(conn.actor, UserActor) else self.guests
        key = conn.actor.user_id if isinstance(conn.actor, UserActor) else conn.actor.guest_id
        conns = bucket.get(key)
        if conns:
            conns.discard(conn)
            if not conns:
                bucket.pop(key, None)

    def online_user_ids(self) -> set[uuid.UUID]:
        return set(self.users)

    async def _send(self, conns, event: dict) -> None:
        for c in list(conns):
            try:
                await c.send(event)
            except Exception:
                self.remove(c)

    async def to_users(self, user_ids, event: dict) -> None:
        for uid in set(user_ids):
            await self._send(self.users.get(uid, ()), event)

    async def to_all_users(self, event: dict) -> None:
        await self.to_users(list(self.users), event)

    async def to_guests_of(self, channel_id: uuid.UUID, event: dict) -> None:
        """Only for payloads built from atrium.guest.schemas."""
        for conns in list(self.guests.values()):
            await self._send([c for c in conns if c.actor.channel_id == channel_id], event)

    async def close_guest(self, guest_id: uuid.UUID) -> None:
        for c in list(self.guests.get(guest_id, ())):
            try:
                await c.ws.close(code=4401)
            except Exception:
                pass
            self.remove(c)

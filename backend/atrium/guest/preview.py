"""Preview tokens for "View as {guest}". Short lived, read only, kept in memory.

The preview loads the real guest app against the real guest API with this
token, so it shows exactly what the guest gets.
"""

import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..actors import GuestActor
from ..models import Guest
from ..security import hash_token, new_token

TTL = 600
_tokens: dict[str, tuple[uuid.UUID, float]] = {}


def issue(guest_id: uuid.UUID) -> str:
    now = time.monotonic()
    for k, (_, exp) in list(_tokens.items()):
        if exp < now:
            _tokens.pop(k, None)
    token = "pv_" + new_token()
    _tokens[hash_token(token)] = (guest_id, now + TTL)
    return token


async def resolve_preview(session: AsyncSession, token: str) -> GuestActor | None:
    if not token.startswith("pv_"):
        return None
    found = _tokens.get(hash_token(token))
    if found is None or found[1] < time.monotonic():
        return None
    guest = await session.get(Guest, found[0])
    if guest is None or guest.revoked_at is not None:
        return None
    return GuestActor(guest_id=guest.id, channel_id=guest.channel_id, name=guest.name or "Guest", read_only=True)

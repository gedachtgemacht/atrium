"""Notifications.

People who have Atrium open get a "notify" event over their socket (the browser shows it).
People who are offline get one email after a short delay, collecting everything since.
Guests get an email only if they gave an address and asked for it.

Emails never contain message text: who wrote where, and a link. The content stays on the server.
Pending notifications live in memory only; nothing about who was online is stored.
"""

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select

from . import mail, policy
from .db import utcnow
from .i18n import t
from .models import ChannelKind, Guest, GuestSession, Message, Organization, User
from .security import hash_token, new_token

log = logging.getLogger("atrium.notify")

MENTION = re.compile(r"(?<![\w@])@([A-Za-zÀ-ÿ][\w.-]{1,59})")


@dataclass
class Item:
    kind: str  # mention | customer | agent | staff
    who: str
    where: str
    channel_id: uuid.UUID


@dataclass
class Pending:
    items: list[Item] = field(default_factory=list)
    task: asyncio.Task | None = None


def mentioned_users(body: str, users: list[User]) -> list[User]:
    """@Tom or @TomBecker or @tom.becker. A first name only counts if it is unique."""
    words = {w.lower().rstrip(".") for w in MENTION.findall(body)}
    if not words:
        return []
    firsts: dict[str, list[User]] = {}
    for u in users:
        firsts.setdefault(u.name.split(" ")[0].lower(), []).append(u)
    out = []
    for u in users:
        full = u.name.lower()
        keys = {full.replace(" ", ""), full.replace(" ", "."), full.replace(" ", "_")}
        first = u.name.split(" ")[0].lower()
        if words & keys or (first in words and len(firsts[first]) == 1):
            out.append(u)
    return out


class Notifier:
    def __init__(self, state):
        self.state = state
        self.users: dict[uuid.UUID, Pending] = {}
        self.guests: dict[uuid.UUID, Pending] = {}

    def _where(self, channel) -> str:
        return f"#{channel.name}" if channel.kind == ChannelKind.internal else channel.name

    async def on_message(self, session, channel, msg: Message, *, started_by: uuid.UUID | None = None) -> None:
        try:
            await self._on_message(session, channel, msg, started_by)
        except Exception:
            log.exception("notification failed")

    async def _on_message(self, session, channel, msg: Message, started_by) -> None:
        readers = await policy.reader_user_ids(session, channel)
        author_user = msg.author_user_id
        who = (msg.author_user.name if msg.author_user else msg.author_guest.name if msg.author_guest
               else msg.author_agent.name if msg.author_agent else "")
        where = self._where(channel)
        targets: dict[uuid.UUID, Item] = {}

        if msg.author_kind.value != "agent":
            users = (await session.execute(select(User).where(User.id.in_(readers), User.is_active.is_(True)))).scalars().all()
            for u in mentioned_users(msg.body, list(users)):
                if u.id != author_user:
                    targets[u.id] = Item("mention", who, where, channel.id)
        if channel.kind == ChannelKind.shared and msg.author_guest_id:
            for uid in readers:
                targets.setdefault(uid, Item("customer", who, where, channel.id))
        if msg.author_agent_id and started_by and started_by in readers:
            targets.setdefault(started_by, Item("agent", who, where, channel.id))

        snippet = msg.body[:140]
        for uid, item in targets.items():
            if uid in self.state.hub.users:
                await self.state.hub.to_users([uid], {
                    "type": "notify", "kind": item.kind, "who": item.who, "where": item.where,
                    "channel_id": str(channel.id), "message_id": str(msg.id), "body": snippet,
                })
            else:
                self._queue(self.users, uid, item, self.state.settings.notify_delay_seconds, self._mail_user)

        if channel.kind == ChannelKind.shared and msg.author_user_id:
            guests = (await session.execute(
                select(Guest.id).where(Guest.channel_id == channel.id, Guest.notify.is_(True), Guest.email.is_not(None),
                                       Guest.revoked_at.is_(None), Guest.expires_at > utcnow())
            )).scalars().all()
            for gid in guests:
                if gid not in self.state.hub.guests:
                    self._queue(self.guests, gid, Item("staff", who, where, channel.id),
                                self.state.settings.guest_notify_delay_seconds, self._mail_guest)

    def _queue(self, table, key, item: Item, delay: int, sender) -> None:
        p = table.setdefault(key, Pending())
        p.items.append(item)
        if p.task is None or p.task.done():

            async def later():
                await asyncio.sleep(delay)
                pending = table.pop(key, None)
                if pending and pending.items:
                    await sender(key, pending.items)

            p.task = self.state.tasks.spawn(later(), name="notify")

    def online(self, user_id: uuid.UUID) -> None:
        """Someone came back before the email went out: they'll see it in the app."""
        p = self.users.pop(user_id, None)
        if p and p.task:
            p.task.cancel()

    def guest_online(self, guest_id: uuid.UUID) -> None:
        p = self.guests.pop(guest_id, None)
        if p and p.task:
            p.task.cancel()

    async def _mail_user(self, user_id: uuid.UUID, items: list[Item]) -> None:
        if user_id in self.state.hub.users:
            return
        s = self.state.settings
        async with self.state.db.sessions() as session:
            u = await session.get(User, user_id)
            if u is None or not u.is_active or not u.notify_email:
                return
            org = await session.get(Organization, u.org_id)
        language = u.locale or org.language
        lines = [t(language, f"mail.user.{i.kind}", who=i.who, where=i.where) for i in items]
        lines = list(dict.fromkeys(lines))
        first = items[0]
        link = f"{s.base_url.rstrip('/')}/#/c/{first.channel_id}"
        subject = (t(language, "mail.user.subject.one", who=first.who, where=first.where) if len(lines) == 1
                   else t(language, "mail.user.subject.many", n=len(lines)))
        body = "\n".join(lines) + "\n\n" + t(language, "mail.user.open", link=link) + "\n\n" + t(language, "mail.footer", org=org.name)
        await mail.send(s, mail.build(s, u.email, subject, body))

    async def _mail_guest(self, guest_id: uuid.UUID, items: list[Item]) -> None:
        if guest_id in self.state.hub.guests:
            return
        s = self.state.settings
        async with self.state.db.sessions() as session:
            g = await session.get(Guest, guest_id)
            if g is None or not g.notify or not g.email or g.revoked_at is not None or g.expires_at <= utcnow():
                return
            org = (await session.execute(select(Organization).limit(1))).scalar_one()
            # A fresh sign in link, so the email works on any device. Valid 7 days, never longer than the invite.
            token = new_token()
            session.add(GuestSession(token_hash=hash_token(token), guest_id=g.id,
                                     expires_at=min(g.expires_at, utcnow() + timedelta(days=7))))
            unsub = new_token()
            g.unsubscribe_hash = hash_token(unsub)
            await session.commit()
        language = g.locale or org.language
        base = s.base_url.rstrip("/")
        who = items[-1].who
        body = (t(language, "mail.guest.body", name=(g.name or "").split(" ")[0], who=who, org=org.name, link=f"{base}/g/#login={token}")
                + "\n\n" + t(language, "mail.guest.unsub", link=f"{base}/g/api/unsubscribe/{unsub}"))
        await mail.send(s, mail.build(s, g.email, t(language, "mail.guest.subject", org=org.name), body,
                                      unsubscribe=f"{base}/g/api/unsubscribe/{unsub}"))

"""Demo data: Kessler Logistik and their customer Hollmann Bau.

    python -m atrium.seed            # only if the database is empty
    python -m atrium.seed --reset    # wipe everything first

Prints the sign in data and the guest links.
"""

import argparse
import asyncio
import os
from datetime import datetime, timedelta

from sqlalchemy import select, text

from .config import get_settings
from .db import Base, Database, utcnow
from .models import (
    AuthorKind,
    Channel,
    ChannelKind,
    ChannelMember,
    Guest,
    Message,
    Organization,
    Room,
    RoomKind,
    User,
)
from .security import hash_password, hash_token, new_token

PEOPLE = [
    # first, last, role, tone, admin
    ("Lena", "Kraft", "Sales", "#CFE0F0", True),
    ("Tom", "Becker", "Dispatch", "#D3E4C8", False),
    ("Aylin", "Demir", "Dispatch", "#EBD2DD", False),
    ("Jonas", "Wirth", "Dispatch", "#E4DCC6", False),
    ("Mia", "Schulz", "Sales", "#CFE2E2", False),
    ("Kai", "Brenner", "Warehouse", "#E7D8BF", False),
    ("Sven", "Albers", "Warehouse", "#D8D4EC", False),
    ("Ole", "Martens", "Accounting", "#DCE3EC", False),
]


def migrate() -> None:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    here = Path(__file__).resolve().parents[1]
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "migrations"))
    command.upgrade(cfg, "head")


def at(day: datetime, hhmm: str) -> datetime:
    h, m = hhmm.split(":")
    return day.replace(hour=int(h), minute=int(m), second=0, microsecond=0)


async def seed(db: Database, *, password: str, base_url: str, reset: bool = False, use_alembic: bool = True) -> dict:
    if reset:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    if use_alembic:
        await asyncio.to_thread(migrate)
    else:
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with db.sessions() as s:
        if (await s.execute(select(Organization))).first():
            return {}
        org = Organization(name="Kessler Logistik", server_location="Frankfurt", retention={})
        s.add(org)
        await s.flush()

        users: dict[str, User] = {}
        for first, last, role, tone, admin in PEOPLE:
            u = User(org_id=org.id, email=f"{first.lower()}@kessler.example", password_hash=hash_password(password),
                     name=f"{first} {last}", initials=(first[0] + last[0]).upper(), tone=tone, role_label=role, is_admin=admin)
            s.add(u)
            users[first] = u
        await s.flush()

        def channel(name, kind=ChannelKind.internal, members=(), **kw) -> Channel:
            ch = Channel(org_id=org.id, kind=kind, name=name, **kw)
            s.add(ch)
            return ch

        everyone = list(users)
        dispatch = channel("dispatch", description="Tours, trucks and carriers")
        warehouse = channel("warehouse", description="Warehouse and loading")
        sales = channel("sales", description="Customers and quotes")
        news = channel("announcements", description="News for everybody")
        hollmann = channel("Hollmann Bau", ChannelKind.shared, partner_name="Hollmann Bau",
                           description="Customer channel with Hollmann Bau GmbH. Sarah and Jan are here by link, without an account.")
        await s.flush()
        backroom = channel("Backroom Hollmann Bau", ChannelKind.backroom, partner_name="Hollmann Bau", backroom_for_id=hollmann.id)
        await s.flush()
        membership = {
            dispatch: ["Tom", "Aylin", "Jonas", "Lena"],
            warehouse: ["Kai", "Sven", "Tom"],
            sales: ["Lena", "Mia", "Ole"],
            news: everyone,
            hollmann: ["Lena", "Tom"],
        }
        for ch, names in membership.items():
            for n in names:
                s.add(ChannelMember(channel_id=ch.id, user_id=users[n].id))

        for pos, (name, kind, layout, ch) in enumerate([
            ("Dispatch", RoomKind.normal, "dispatch", dispatch),
            ("Sales corner", RoomKind.normal, "sales", sales),
            ("Warehouse office", RoomKind.normal, "warehouse", warehouse),
            ("Quiet room", RoomKind.quiet, "quiet", None),
        ]):
            s.add(Room(org_id=org.id, name=name, kind=kind, layout=layout, position=pos, channel_id=ch.id if ch else None))

        links = {}
        guests = {}
        for gname in ("Sarah Hollmann", "Jan Petersen"):
            token = new_token()
            g = Guest(channel_id=hollmann.id, name=gname, company="Hollmann Bau", token_hash=hash_token(token),
                      expires_at=utcnow() + timedelta(days=90), invited_by_id=users["Lena"].id)
            s.add(g)
            guests[gname.split()[0]] = g
            links[gname] = f"{base_url.rstrip('/')}/g/{token}"
        await s.flush()

        today = utcnow().astimezone().replace(tzinfo=None)
        day = datetime(today.year, today.month, today.day).astimezone()

        def msg(ch, when, body, user=None, guest=None):
            m = Message(channel_id=ch.id, body=body, created_at=at(day, when))
            if user:
                m.author_kind, m.author_user_id = AuthorKind.user, users[user].id
            else:
                m.author_kind, m.author_guest_id = AuthorKind.guest, guests[guest].id
            s.add(m)

        msg(hollmann, "09:12", "Good morning! For 2027 we'd like 40 loads a month from January. Same routes as this year, plus our new site in Erfurt. Can you get us a quote by Friday?", guest="Sarah")
        msg(hollmann, "09:24", "Hi Sarah, thanks! We'll work it out, the quote comes by Friday.", user="Lena")
        msg(hollmann, "10:02", "One more thing: would 45 day payment terms work too?", guest="Sarah")
        msg(dispatch, "08:40", "Tomorrow's tours are up. Two trucks short on Thursday, I'm asking the pool.", user="Tom")
        msg(dispatch, "08:52", "I can take the Hamm tour on Thursday.", user="Aylin")
        msg(warehouse, "07:55", "Gate 3 is free again.", user="Kai")
        msg(news, "08:00", "The new loading schedule applies from Monday.", user="Ole")
        await s.commit()
        return {"password": password, "emails": [u.email for u in users.values()], "links": links}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--json", help="also write the result (password, emails, guest links) to this file")
    args = ap.parse_args()
    settings = get_settings()
    password = os.environ.get("ATRIUM_SEED_PASSWORD", "atrium-demo")

    async def run():
        db = Database(settings.database_url)
        try:
            out = await seed(db, password=password, base_url=settings.base_url, reset=args.reset)
        finally:
            await db.dispose()
        if not out:
            print("Database already has data. Use --reset to start over.")
            return
        if args.json:
            import json

            with open(args.json, "w") as f:
                json.dump(out, f)
        print(f"Signed in as anyone below with password {out['password']!r}:")
        for e in out["emails"]:
            print("  ", e)
        print("Guest links:")
        for name, link in out["links"].items():
            print(f"   {name}: {link}")

    asyncio.run(run())


if __name__ == "__main__":
    main()

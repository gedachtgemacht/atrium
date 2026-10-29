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
    # first, last, role key, tone, admin
    ("Lena", "Kraft", "sales", "#CFE0F0", True),
    ("Tom", "Becker", "dispatch", "#D3E4C8", False),
    ("Aylin", "Demir", "dispatch", "#EBD2DD", False),
    ("Jonas", "Wirth", "dispatch", "#E4DCC6", False),
    ("Mia", "Schulz", "sales", "#CFE2E2", False),
    ("Kai", "Brenner", "warehouse", "#E7D8BF", False),
    ("Sven", "Albers", "warehouse", "#D8D4EC", False),
    ("Ole", "Martens", "accounting", "#DCE3EC", False),
]

# Demo texts. The German ones follow docs/mockup.html.
DEMO = {
    "en": {
        "roles": {"sales": "Sales", "dispatch": "Dispatch", "warehouse": "Warehouse", "accounting": "Accounting"},
        "channels": {
            "dispatch": ("dispatch", "Tours, trucks and carriers"),
            "warehouse": ("warehouse", "Warehouse and loading"),
            "sales": ("sales", "Customers and quotes"),
            "news": ("announcements", "News for everybody"),
        },
        "shared_description": "Customer channel with Hollmann Bau GmbH. Sarah and Jan are here by link, without an account.",
        "backroom": "Backroom Hollmann Bau",
        "floor": "Dortmund office",
        "rooms": {"dispatch": "Dispatch", "sales": "Sales corner", "warehouse": "Warehouse office", "quiet": "Quiet room", "hallway": "Hallway"},
        "messages": [
            ("hollmann", "09:12", "Sarah", "Good morning! For 2027 we'd like 40 loads a month from January. Same routes as this year, plus our new site in Erfurt. Can you get us a quote by Friday?"),
            ("hollmann", "09:24", "Lena", "Hi Sarah, thanks! We'll work it out, the quote comes by Friday."),
            ("hollmann", "10:02", "Sarah", "One more thing: would 45 day payment terms work too?"),
            ("dispatch", "08:40", "Tom", "Tomorrow's tours are up. Two trucks short on Thursday, I'm asking the pool."),
            ("dispatch", "08:52", "Aylin", "I can take the Hamm tour on Thursday."),
            ("warehouse", "07:55", "Kai", "Gate 3 is free again."),
            ("news", "08:00", "Ole", "The new loading schedule applies from Monday."),
        ],
    },
    "de": {
        "roles": {"sales": "Vertrieb", "dispatch": "Dispo", "warehouse": "Lager", "accounting": "Buchhaltung"},
        "channels": {
            "dispatch": ("dispo", "Touren, LKW und Frächter"),
            "warehouse": ("lager", "Lager und Verladung"),
            "sales": ("vertrieb", "Kunden und Angebote"),
            "news": ("ankündigungen", "Neuigkeiten für alle"),
        },
        "shared_description": "Kundenkanal mit Hollmann Bau GmbH. Sarah und Jan sind per Link dabei, ohne Konto.",
        "backroom": "Hinterzimmer Hollmann Bau",
        "floor": "Büro Dortmund",
        "rooms": {"dispatch": "Dispo", "sales": "Vertriebsecke", "warehouse": "Lagerbüro", "quiet": "Ruheraum", "hallway": "Flur"},
        "messages": [
            ("hollmann", "09:12", "Sarah", "Guten Morgen! Für 2027 hätten wir gern 40 Ladungen im Monat ab Januar. Gleiche Strecken wie dieses Jahr, plus unser neuer Standort in Erfurt. Schafft ihr ein Angebot bis Freitag?"),
            ("hollmann", "09:24", "Lena", "Hallo Sarah, danke dir! Wir rechnen das durch, das Angebot kommt bis Freitag."),
            ("hollmann", "10:02", "Sarah", "Noch was: Ginge auch ein Zahlungsziel von 45 Tagen?"),
            ("dispatch", "08:40", "Tom", "Die Touren für morgen stehen. Donnerstag fehlen zwei LKW, ich frage im Frachtpool."),
            ("dispatch", "08:52", "Aylin", "Ich kann am Donnerstag die Tour nach Hamm fahren."),
            ("warehouse", "07:55", "Kai", "Tor 3 ist wieder frei."),
            ("news", "08:00", "Ole", "Ab Montag gilt der neue Verladeplan."),
        ],
    },
}


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


async def seed(db: Database, *, password: str, base_url: str, reset: bool = False, use_alembic: bool = True,
               language: str = "en") -> dict:
    T = DEMO[language if language in DEMO else "en"]
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
        org = Organization(name="Kessler Logistik", server_location="Frankfurt", retention={}, language=language if language in DEMO else "en")
        s.add(org)
        await s.flush()

        users: dict[str, User] = {}
        for first, last, role, tone, admin in PEOPLE:
            u = User(org_id=org.id, email=f"{first.lower()}@kessler.example", password_hash=hash_password(password),
                     name=f"{first} {last}", initials=(first[0] + last[0]).upper(), tone=tone, role_label=T["roles"][role], is_admin=admin)
            s.add(u)
            users[first] = u
        await s.flush()

        def channel(name, kind=ChannelKind.internal, members=(), **kw) -> Channel:
            ch = Channel(org_id=org.id, kind=kind, name=name, **kw)
            s.add(ch)
            return ch

        everyone = list(users)
        C = T["channels"]
        dispatch = channel(C["dispatch"][0], description=C["dispatch"][1])
        warehouse = channel(C["warehouse"][0], description=C["warehouse"][1])
        sales = channel(C["sales"][0], description=C["sales"][1])
        news = channel(C["news"][0], description=C["news"][1])
        hollmann = channel("Hollmann Bau", ChannelKind.shared, partner_name="Hollmann Bau", description=T["shared_description"])
        await s.flush()
        backroom = channel(T["backroom"], ChannelKind.backroom, partner_name="Hollmann Bau", backroom_for_id=hollmann.id)
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

        org.floors = [{"id": "main", "name": T["floor"], "columns": 2}]
        R = T["rooms"]
        for name, kind, (col, row, cs), ch in [
            (R["dispatch"], RoomKind.normal, (0, 0, 2), dispatch),
            (R["sales"], RoomKind.normal, (0, 1, 1), sales),
            (R["warehouse"], RoomKind.normal, (1, 1, 1), warehouse),
            (R["quiet"], RoomKind.quiet, (0, 2, 1), None),
            (R["hallway"], RoomKind.hallway, (1, 2, 1), None),
        ]:
            s.add(Room(org_id=org.id, name=name, kind=kind, floor_id="main", col=col, row=row, col_span=cs,
                       channel_id=ch.id if ch else None))

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

        where = {"hollmann": hollmann, "dispatch": dispatch, "warehouse": warehouse, "news": news, "sales": sales}
        for ch, when, who, body in T["messages"]:
            if who in guests:
                msg(where[ch], when, body, guest=who)
            else:
                msg(where[ch], when, body, user=who)
        await s.commit()
        return {"password": password, "emails": [u.email for u in users.values()], "links": links}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--json", help="also write the result (password, emails, guest links) to this file")
    ap.add_argument("--language", default="en", choices=sorted(DEMO), help="language of the demo company and its messages")
    args = ap.parse_args()
    settings = get_settings()
    password = os.environ.get("ATRIUM_SEED_PASSWORD", "atrium-demo")

    async def run():
        db = Database(settings.database_url)
        try:
            out = await seed(db, password=password, base_url=settings.base_url, reset=args.reset, language=args.language)
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

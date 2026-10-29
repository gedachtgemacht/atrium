"""Small admin commands.

    python -m atrium.cli create-admin --org "Kessler Logistik" --email lena@example.com --name "Lena Kraft"

Asks for the password. Creates the organization on first use.
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from .config import get_settings
from .db import Database
from .models import Organization, User
from .security import hash_password
from .seed import migrate
from .serialize import initials


async def create_admin(org_name: str, location: str, email: str, name: str, password: str) -> None:
    await asyncio.to_thread(migrate)
    db = Database(get_settings().database_url)
    try:
        async with db.sessions() as s:
            org = (await s.execute(select(Organization).limit(1))).scalar_one_or_none()
            if org is None:
                org = Organization(name=org_name, server_location=location, retention={})
                s.add(org)
                await s.flush()
            if (await s.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none():
                sys.exit(f"{email} already has an account")
            s.add(User(org_id=org.id, email=email.lower(), password_hash=hash_password(password), name=name,
                       initials=initials(name), is_admin=True))
            await s.commit()
        from .agents.config import load_agents
        from .agents.runner import sync_agents
        from .state import AppState

        state = AppState(settings=get_settings(), db=db, llm=None, agents=load_agents(get_settings().agents_dir))
        async with db.sessions() as s:
            await sync_agents(state, s)
    finally:
        await db.dispose()
    print(f"Admin {email} created for {org.name}.")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m atrium.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ca = sub.add_parser("create-admin")
    ca.add_argument("--org", required=True, help="Company name, used when the organization doesn't exist yet")
    ca.add_argument("--location", default="", help="Server location shown to guests, e.g. Frankfurt")
    ca.add_argument("--email", required=True)
    ca.add_argument("--name", required=True)
    args = ap.parse_args()
    password = getpass.getpass("Password (10+ characters): ")
    if len(password) < 10:
        sys.exit("Password is too short")
    asyncio.run(create_admin(args.org, args.location, args.email, args.name, password))


if __name__ == "__main__":
    main()

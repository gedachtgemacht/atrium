"""Stage for README screenshots: a fresh demo company, the mockup flow played through the real API,
and colleagues sitting in rooms. The LLM answers are scripted so the pictures are the same every time;
everything else (pulling, tools, quote maths, memory, presence) is the real app.

    cd backend && uv run python ../tools/screenshots/stage.py --language en   # serves on :8030 until stopped

Needs the database atrium_shots (see README, Develop).
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx
import uvicorn
import websockets

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from atrium.config import Settings  # noqa: E402
from atrium.db import Database  # noqa: E402
from atrium.llm.base import LLMResponse, ToolCall  # noqa: E402
from atrium.llm.providers.fake import FakeProvider  # noqa: E402
from atrium.main import create_app  # noqa: E402
from atrium.rooms.notes import FakeTranscriber  # noqa: E402
from atrium.seed import seed  # noqa: E402

PORT = 8030
BASE = f"http://127.0.0.1:{PORT}"
DB = "postgresql+psycopg://atrium:atrium@127.0.0.1:55432/atrium_shots"
PASSWORD = "atrium-demo"

TEXT = {
    "en": {
        "mention": "@QuoteAgent please price this: 40 loads a month, routes from 2026 plus Erfurt, prices 2026 plus 3 %.",
        "pay_note": "@QuoteAgent can you work out the payment terms?",
        "tom": "Erfurt works. Two carriers from the pool run it Tuesdays and Thursdays. I'll confirm both by Thursday.",
        "agent_quote": "The draft is ready. Have a look at Erfurt before it goes out.",
        "agent_pay": "I worked out the payment terms.",
        "mem": {
            "request": ("committed", "Quote to Sarah by Friday", "Lena", "by Friday"),
            "markup": ("decided", "Prices 2027 are prices 2026 plus 3 %", "Lena", ""),
            "tom1": ("decided", "Erfurt runs with the pool, Tuesdays and Thursdays", "Tom", ""),
            "tom2": ("committed", "Confirm both carriers for Erfurt", "Tom", "by Thursday"),
            "pay": ("open", "45 day payment terms for Hollmann?", "", ""),
        },
        "ask_sarah": "She wants 40 loads a month from January, same routes plus Erfurt, and a quote by Friday. She also asks about 45 day payment terms.",
        "keys": {"request": "40 loads", "markup": "plus 3", "tom": "Tuesdays", "pay": "payment terms"},
    },
    "de": {
        "mention": "@QuoteAgent rechne das bitte: 40 Ladungen im Monat, Strecken von 2026 plus Erfurt, Preise 2026 plus 3 %.",
        "pay_note": "@QuoteAgent rechnest du das Zahlungsziel durch?",
        "tom": "Erfurt passt. Zwei Frächter aus dem Frachtpool fahren die Strecke dienstags und donnerstags. Ich bestätige beide bis Donnerstag.",
        "agent_quote": "Entwurf steht. Schau dir Erfurt an, bevor er rausgeht.",
        "agent_pay": "Ich hab das Zahlungsziel durchgerechnet.",
        "mem": {
            "request": ("committed", "Angebot an Sarah bis Freitag", "Lena", "bis Freitag"),
            "markup": ("decided", "Preise 2027 sind die Preise 2026 plus 3 %", "Lena", ""),
            "tom1": ("decided", "Erfurt fährt der Frachtpool, dienstags und donnerstags", "Tom", ""),
            "tom2": ("committed", "Beide Frächter für Erfurt bestätigen", "Tom", "bis Donnerstag"),
            "pay": ("open", "Zahlungsziel 45 Tage für Hollmann?", "", ""),
        },
        "ask_sarah": "Sarah will ab Januar 40 Ladungen im Monat, gleiche Strecken plus Erfurt, Angebot bis Freitag. Außerdem fragt sie nach 45 Tagen Zahlungsziel.",
        "keys": {"request": "40 Ladungen", "markup": "plus 3", "tom": "dienstags", "pay": "Zahlungsziel"},
    },
}


def labels(text: str, needle: str, people_only: bool = False) -> list[str]:
    out = []
    for l in text.splitlines():
        if l.startswith("[m") and needle.lower() in l.lower() and not (people_only and "@QuoteAgent" in l):
            out.append(l[1:l.index("]")])
    return out


def script_for(T):
    K = T["keys"]

    def script(system, turns, tools):
        names = {t.name for t in tools}
        text = turns[0].text
        rounds = sum(1 for t in turns if t.role == "assistant")
        if rounds and "create_quote" not in names:
            return LLMResponse(text="", tool_calls=[])
        if "record_memory" in names:
            entries = []
            for key, needle, people in (("request", K["request"], False), ("markup", K["markup"], False), ("pay", K["pay"], True)):
                for l in labels(text, needle, people)[:1]:
                    kind, t, owner, due = T["mem"][key]
                    entries.append({"kind": kind, "text": t, "owner": owner, "due": due, "source": l})
            for l in labels(text, K["tom"])[:1]:
                for key in ("tom1", "tom2"):
                    kind, t, owner, due = T["mem"][key]
                    entries.append({"kind": kind, "text": t, "owner": owner, "due": due, "source": l})
            return LLMResponse(text="", tool_calls=[ToolCall("r", "record_memory", {"entries": entries, "resolve": []})])
        if "answer" in names:
            q = text.rsplit("Question:", 1)[-1].lower()
            if "sarah" in q:
                src = labels(text, K["request"])[:1] + labels(text, K["pay"])[:1]
                return LLMResponse(text="", tool_calls=[ToolCall("a", "answer", {"text": T["ask_sarah"], "known": True, "sources": src})])
            return LLMResponse(text="", tool_calls=[ToolCall("a", "answer", {"text": "", "known": False, "sources": []})])
        if "create_quote" in names:
            trigger = text.rsplit("You were mentioned in", 1)[-1]
            ref = trigger.split(".")[0].strip()
            line = next((l for l in text.splitlines() if l.startswith(f"[{ref}]")), "")
            if K["pay"].lower() in line.lower():
                if rounds == 0:
                    src = [l for l in labels(text, K["pay"]) if l != ref][-1:]
                    return LLMResponse(text="", tool_calls=[ToolCall("p", "calculate_payment_terms", {
                        "current_days": 30, "requested_days": 45, "answers": src, "greeting_name": "Sarah"})])
                return LLMResponse(text=T["agent_pay"], tool_calls=[])
            if rounds == 0:
                return LLMResponse(text="", tool_calls=[ToolCall("c", "contract_terms", {"customer": "Hollmann Bau"})])
            if rounds == 1:
                return LLMResponse(text="", tool_calls=[ToolCall("q", "create_quote", {
                    "customer": "Hollmann Bau", "year": 2027, "markup_pct": 3, "loads_per_month": 40, "new_destinations": ["Erfurt"],
                    "first_month": "2027-01", "answers": labels(text, K["request"])[:1], "greeting_name": "Sarah"})])
            return LLMResponse(text=T["agent_quote"], tool_calls=[])
        return LLMResponse(text="", tool_calls=[])

    return script


class Who:
    def __init__(self, client: httpx.AsyncClient, cookie: str):
        self.c, self.cookie = client, cookie

    async def req(self, method, url, **kw):
        r = await self.c.request(method, BASE + url, headers={"Cookie": self.cookie, "X-Requested-With": "atrium"}, **kw)
        r.raise_for_status()
        return r.json()


async def login(c, first):
    r = await c.post(BASE + "/api/auth/login", json={"email": f"{first}@kessler.example", "password": PASSWORD},
                     headers={"X-Requested-With": "atrium"})
    r.raise_for_status()
    return Who(c, f"atrium_session={r.cookies['atrium_session']}")


async def idle(state):
    for _ in range(200):
        await asyncio.sleep(0.05)
        if not [t for t in state.tasks._tasks if not t.done() and not (t.get_name() or "").startswith("notify")]:
            return


async def play(app, T, out: Path):
    state = app.state.atrium
    async with httpx.AsyncClient(timeout=60) as c:
        lena = await login(c, "lena")
        tom = await login(c, "tom")
        chans = {ch["name"]: ch for ch in await lena.req("GET", "/api/channels")}
        shared = chans["Hollmann Bau"]
        msgs = await lena.req("GET", f"/api/channels/{shared['id']}/messages")
        request = next(m for m in msgs if T["keys"]["request"] in m["body"])
        await lena.req("POST", f"/api/messages/{request['id']}/pull", json={"note": T["mention"]})
        await idle(state)
        await tom.req("POST", f"/api/channels/{shared['backroom_id']}/messages", json={"body": T["tom"]})
        await idle(state)
        # Put the morning together the way the mockup tells it: everything within the last hour or so,
        # so the live steps of the video continue naturally. shoot sets the browser clock to the morning.
        from sqlalchemy import text

        async with state.db.sessions() as s:
            async def at(mid, minutes):
                await s.execute(text("UPDATE message SET created_at = now() - make_interval(mins => :m) WHERE id = :i"), {"m": minutes, "i": mid})

            shared_rows = (await s.execute(text("SELECT id FROM message WHERE channel_id = :c ORDER BY created_at"), {"c": shared["id"]})).scalars().all()
            for mid, m in zip(shared_rows, [82, 70, 30]):
                await at(mid, m)
            back_rows = (await s.execute(text("SELECT id FROM message WHERE channel_id = :b ORDER BY created_at"), {"b": shared["backroom_id"]})).scalars().all()
            for mid, m in zip(back_rows, [75, 74, 73, 60]):
                await at(mid, m)
            await s.execute(text("UPDATE pull SET pulled_at = now() - interval '75 minutes'"))
            await s.execute(text("UPDATE memory_entry SET created_at = now() - interval '72 minutes'"))
            others = (await s.execute(text("SELECT id FROM message WHERE channel_id NOT IN (:c, :b) ORDER BY created_at"),
                                      {"c": shared["id"], "b": shared["backroom_id"]})).scalars().all()
            for i, mid in enumerate(others):
                await at(mid, 120 - i * 8)
            await s.commit()
        out.write_text(json.dumps({"shared": shared["id"], "backroom": shared["backroom_id"]}))


async def presence(state):
    """Colleagues sitting in rooms, as in the mockup. Held open while the screenshots run."""
    cookies = {}
    async with httpx.AsyncClient() as c:
        for first in ("tom", "aylin", "jonas", "mia", "kai", "sven", "ole"):
            cookies[first] = (await login(c, first)).cookie
    rooms = {r["name"]: r for r in (await (await login(httpx.AsyncClient(), "lena")).req("GET", "/api/rooms"))["rooms"]}
    names = list(rooms)
    talk = [r for r in names if rooms[r]["kind"] == "normal"]
    quiet = next(r for r in names if rooms[r]["kind"] == "quiet")
    plan = {"tom": talk[0], "aylin": talk[0], "jonas": talk[0], "mia": talk[1], "kai": talk[2], "sven": talk[2], "ole": quiet}
    socks = []
    for who, room in plan.items():
        ws = await websockets.connect(f"ws://127.0.0.1:{PORT}/ws", additional_headers={"Cookie": cookies[who]})
        await ws.recv()
        await ws.send(json.dumps({"type": "room.join", "room_id": rooms[room]["id"]}))
        if who == "tom":
            await ws.send(json.dumps({"type": "room.notes", "on": True}))
        socks.append(ws)

    async def drain(ws):
        try:
            async for _ in ws:
                pass
        except Exception:
            pass

    for ws in socks:
        asyncio.create_task(drain(ws))
    return socks


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--language", default="en", choices=["en", "de"])
    args = ap.parse_args()
    T = TEXT[args.language]
    data = Path("/tmp/atrium-shots")
    settings = Settings(database_url=DB, base_url=f"http://localhost:{PORT}", data_dir=data, llm_provider="fake",
                        anthropic_api_key="", openai_compat_base_url="", livekit_url="", whisper_model="fake",
                        smtp_host="", notify_delay_seconds=3600)
    (data / "ready").unlink(missing_ok=True)
    db = Database(DB)
    seeded = await seed(db, password=PASSWORD, base_url=settings.base_url, reset=True, use_alembic=False, language=args.language)
    await db.dispose()
    provider = FakeProvider()
    provider.script = script_for(T)
    app = create_app(settings, provider=provider, transcriber=FakeTranscriber(), background=False)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning", access_log=False))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    app.state.atrium.memory_delay = 0.2
    await play(app, T, data / "stage.json")
    stage = json.loads((data / "stage.json").read_text()) | {"links": seeded["links"], "language": args.language}
    (data / "stage.json").write_text(json.dumps(stage))
    await presence(app.state.atrium)
    (data / "ready").write_text("ok")
    print("stage ready on", BASE, flush=True)
    await task


if __name__ == "__main__":
    asyncio.run(main())

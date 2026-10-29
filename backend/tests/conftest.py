"""Test setup.

Tests never run against real credentials: every LLM key is cleared, the LLM is
a scripted fake that records payloads, and outgoing network connections other
than to the local test database are refused.
"""

import asyncio
import json
import os
import socket
import uuid

import pytest

for key in list(os.environ):
    if key.startswith("ATRIUM_") or key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(key)
os.environ["ATRIUM_DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://atrium:atrium@127.0.0.1:55432/atrium_test"
)
os.environ["ATRIUM_LLM_PROVIDER"] = "fake"
os.environ["ATRIUM_WHISPER_MODEL"] = "fake"

_real_connect = socket.socket.connect


def _guarded_connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, str) and (host.startswith("127.") or host in ("localhost", "::1") or host.startswith("/")):
        return _real_connect(self, address)
    raise RuntimeError(f"Tests may not open network connections ({address!r})")


socket.socket.connect = _guarded_connect

from fastapi.testclient import TestClient  # noqa: E402

from atrium.config import Settings  # noqa: E402
from atrium.db import Database  # noqa: E402
from atrium.llm.base import LLMResponse, ToolCall  # noqa: E402
from atrium.llm.providers.fake import FakeProvider  # noqa: E402
from atrium.main import create_app  # noqa: E402
from atrium.rooms.notes import FakeTranscriber  # noqa: E402
from atrium.seed import seed  # noqa: E402

PASSWORD = "test-password-123"


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, llm_provider="fake", anthropic_api_key="", whisper_model="fake",
                    frontend_dist=tmp_path / "nofrontend")


@pytest.fixture
def seeded(settings):
    async def run():
        db = Database(settings.database_url)
        try:
            return await seed(db, password=PASSWORD, base_url="http://testserver", reset=True, use_alembic=False)
        finally:
            await db.dispose()

    return asyncio.run(run())


@pytest.fixture
def llm():
    p = FakeProvider()
    p.script = default_script
    return p


@pytest.fixture
def app(settings, seeded, llm):
    application = create_app(settings, provider=llm, transcriber=FakeTranscriber(), background=False)
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        app.state.atrium.memory_delay = 0.0
        yield c


class Who:
    """Requests as one identity, with its own cookie, on the shared TestClient."""

    def __init__(self, client: TestClient, cookie: str):
        self.c = client
        self.cookie = cookie

    def _req(self, method, url, **kw):
        headers = kw.pop("headers", {}) | {"Cookie": self.cookie, "X-Requested-With": "atrium"}
        self.c.cookies.clear()
        r = self.c.request(method, url, headers=headers, **kw)
        self.c.cookies.clear()
        return r

    def get(self, url, **kw):
        return self._req("GET", url, **kw)

    def post(self, url, **kw):
        return self._req("POST", url, **kw)

    def patch(self, url, **kw):
        return self._req("PATCH", url, **kw)

    def delete(self, url, **kw):
        return self._req("DELETE", url, **kw)

    def ws(self, url):
        self.c.cookies.clear()
        return self.c.websocket_connect(url, headers={"Cookie": self.cookie})


def login(client: TestClient, first: str) -> Who:
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": f"{first}@kessler.example", "password": PASSWORD},
                    headers={"X-Requested-With": "atrium"})
    assert r.status_code == 200, r.text
    token = r.cookies.get("atrium_session")
    client.cookies.clear()
    return Who(client, f"atrium_session={token}")


def guest(client: TestClient, link: str, name: str = "") -> Who:
    token = link.rsplit("/", 1)[-1].split("#")[0]
    client.cookies.clear()
    r = client.post("/g/api/session", json={"token": token, "name": name}, headers={"X-Requested-With": "atrium"})
    assert r.status_code == 200, r.text
    cookie = r.cookies.get("atrium_guest")
    client.cookies.clear()
    return Who(client, f"atrium_guest={cookie}")


@pytest.fixture
def lena(client):
    return login(client, "lena")


@pytest.fixture
def tom(client):
    return login(client, "tom")


@pytest.fixture
def sarah(client, seeded):
    return guest(client, seeded["links"]["Sarah Hollmann"])


def channels(who: Who) -> dict:
    return {c["name"]: c for c in who.get("/api/channels").json()}


def drain(client: TestClient) -> None:
    client.portal.call(client.app.state.atrium.tasks.drain)


def db_call(client: TestClient, fn):
    """Run async fn(session) inside the app's event loop."""

    async def run():
        async with client.app.state.atrium.db.sessions() as s:
            return await fn(s)

    return client.portal.call(run)


# ---------------------------------------------------------------- scripted LLM


def _user_text(turns) -> str:
    return turns[0].text if turns else ""


def _labels(text: str, needle: str) -> list[str]:
    out = []
    for line in text.splitlines():
        if line.startswith("[m") and needle.lower() in line.lower():
            out.append(line[1:line.index("]")])
    return out


def _rounds(turns) -> int:
    return sum(1 for t in turns if t.role == "assistant")


def default_script(system, turns, tools):
    names = {t.name for t in tools}
    text = _user_text(turns)
    n = _rounds(turns)
    if "record_memory" in names:
        if n:
            return LLMResponse(text="", tool_calls=[])
        entries = []
        for label in _labels(text, "by friday"):
            entries.append({"kind": "committed", "text": "Quote to Sarah by Friday", "owner": "Lena", "due": "by Friday", "source": label})
        for label in _labels(text, "payment terms"):
            entries.append({"kind": "open", "text": "45 day payment terms for Hollmann?", "source": label})
        for label in _labels(text, "plus 3"):
            entries.append({"kind": "decided", "text": "Prices 2027 are prices 2026 plus 3 %", "owner": "Lena", "source": label})
        return LLMResponse(text="", tool_calls=[ToolCall("c1", "record_memory", {"entries": entries, "resolve": []})])
    if "answer" in names:
        if n:
            return LLMResponse(text="", tool_calls=[])
        q = text.rsplit("Question:", 1)[-1].lower()
        hits = [l for l in _labels(text, "erfurt")] if "erfurt" in q else []
        if hits:
            return LLMResponse(text="", tool_calls=[ToolCall("a1", "answer", {"text": "Yes, with help from the pool.", "known": True, "sources": hits[:1]})])
        return LLMResponse(text="", tool_calls=[ToolCall("a1", "answer", {"text": "No idea.", "known": False, "sources": []})])
    if "create_quote" in names:
        if "payment terms" in text.lower() and "calculate" in text.lower():
            if n == 0:
                src = [l for l in _labels(text, "payment terms") if l in _labels(text, "(customer)")]
                return LLMResponse(text="", tool_calls=[ToolCall("p1", "calculate_payment_terms", {
                    "current_days": 30, "requested_days": 45, "answers": src[-1:], "greeting_name": "Sarah"})])
            return LLMResponse(text="I worked out the payment terms.", tool_calls=[])
        if n == 0:
            return LLMResponse(text="", tool_calls=[ToolCall("t1", "contract_terms", {"customer": "Hollmann Bau"}),
                                                     ToolCall("t2", "erp_prices", {"routes": [{"origin": "Dortmund", "destination": "Erfurt"}]})])
        if n == 1:
            src = _labels(text, "40 loads")
            return LLMResponse(text="", tool_calls=[ToolCall("t3", "create_quote", {
                "customer": "Hollmann Bau GmbH", "year": 2027, "markup_pct": 3, "first_month": "2027-01",
                "loads_per_month": 40, "new_destinations": ["Erfurt"],
                "answers": [l for l in src if l][:1], "greeting_name": "Sarah Hollmann"})])
        return LLMResponse(text="The draft is ready. Check Erfurt before it goes out.", tool_calls=[])
    return LLMResponse(text="Summary: Tours for tomorrow are set.", tool_calls=[])


def payloads(llm_or_calls) -> str:
    calls = llm_or_calls.calls if isinstance(llm_or_calls, FakeProvider) else llm_or_calls
    return "\n".join(json.dumps(c, default=str, ensure_ascii=False) for c in calls)


def uid(v) -> uuid.UUID:
    return uuid.UUID(str(v))

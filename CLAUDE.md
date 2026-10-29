# Atrium

Self hosted team chat for companies. Customers and partners join shared channels by link; AI agents work only in an internal backroom next to them. Architecture and decisions: `docs/PLAN.md`. Visual reference (a starting point, not a pixel spec): `docs/mockup.html`.

## The wall: not negotiable

These rules are enforced in the backend, never only in the UI.

1. Agents cannot read shared channels. On every path: message API, search, WebSocket, memory, "Ask the backroom" and the context of LLM calls.
2. Only people write in shared channels. The API rejects agent messages there (403).
3. A customer message reaches the backroom only when an internal person actively pulls it in. That creates a copy in the backroom and an audit entry (who, when, which message).
4. Agents only create drafts. A draft lands in one person's composer in the shared channel. It is sent only by that person's click, and the message has that person as author.
5. Guests see nothing internal: no backroom, no agents, no drafts, no "pulled into the backroom" marker, no internal origin of a message. Guests have their own response schemas (`backend/atrium/guest/schemas.py`), not the internal schemas with fields hidden.
6. Rooms store no presence. Who was in which room when is never stored or logged. Notes run only when someone in the room turns them on, everyone in the room sees that, and without notes nothing is recorded.
7. Every LLM call is logged: agent, trigger, which message ids were in the context, provider, time.

### Where the wall lives in the code

- Access rules live only in `backend/atrium/policy.py`. Every read path (REST, search, WebSocket fanout, memory, ask, agent context) builds its queries from there. No access logic in routes or services.
- The LLM client takes context only as a `BuiltContext` from `backend/atrium/llm/context.py` (`ContextBuilder`). The builder accepts only messages from internal channels inside the agent's scope and raises `WallViolation` otherwise.
- Provider specific code (Anthropic, OpenAI compatible) lives only in `backend/atrium/llm/providers/`.
- Room presence lives only in memory (`backend/atrium/rooms/presence.py`) and travels only over the WebSocket. No table, no log line, no HTTP route for joining.
- The guest frontend (`frontend/src/guest/`) is a separate bundle and must not import anything from `frontend/src/app/`.

### Mandatory wall tests (`backend/tests/wall/`)

- Canary test: `KANARIE-7f3a` in the shared channel, then every agent path. The fake LLM records all payloads; the text must not show up anywhere. Only after a person pulls it in may it appear.
- An agent writing into a shared channel gets 403.
- No route of the guest API returns internal fields or backroom content.
- After a room visit no record of the presence exists.
- Access rules live in one place (AST check).

These tests are never weakened, skipped, marked `xfail` or rewritten to get something green. If one fails, the code is wrong, not the test. Every new read path or agent trigger gets an entry in the canary test.

## Running and testing

- Backend: `cd backend && uv run pytest` (needs the local Postgres from the README; tests use the `atrium_test` database).
- End to end: `cd frontend && npx playwright test` (uses the `atrium_e2e` database and the fake LLM).
- Tests never run against real credentials. `tests/conftest.py` clears all LLM keys and blocks outgoing network; the LLM is always the fake provider.

## Conventions

- UI text in English: short, casual, addressing the reader as "you", no dashes.
- Shapes: circle = person, dashed circle = guest, square = agent.
- No tracking, no analytics, no external scripts or CDNs. Fonts are bundled.
- Keep dependencies few; justify each new one in `docs/PLAN.md`.
- License: AGPL-3.0-or-later.

# Atrium: plan and decisions

Status 2026-10-29: phases 1 to 6 built. This file records the architecture, the decisions behind it and what is still open.

## Product decisions

| # | Question | Decision |
|---|---|---|
| F1 | Federation chips in the mockup | Removed. The top bar shows "Your server, {location}" only. |
| F2 | Who sees a backroom | The internal members of its shared channel. Admins add people via Admin → Channels. |
| F3 | Does pulling start an agent | No. Pulling only feeds the memory. The pull form has an optional note; `@QuoteAgent` in that note starts the agent. |
| F4 | Guest links | One personal link per guest, valid 90 days by default (set per invite), usable on several devices. The name is set on first open. Revoking ends all sessions at once. |
| F5 | Several companies in one channel | Allowed. Each guest has an optional company. |
| F6 | Guest uploads | Allowed: PDF, images, text, CSV, docx, xlsx, up to 20 MB. |
| F7 | Agents in ordinary internal channels | Allowed (e.g. `@QuoteAgent` in #sales), never in shared channels. An agent run only sees the one channel it was started in. |
| F8 | Memory scope | Per backroom. "Ask the backroom" in the tab asks that backroom; the top bar asks all backrooms you're in. |
| F9 | Search field in the top bar | Two things, separated: full text search over everything you may read (people may read customer channels), plus "Ask the backroom", which only knows backrooms and memory. |
| F10 | Room notes and names | The summary names who turned notes on and who promised what. No list of attendees, no join or leave times. |
| F11 | Quiet room | Anyone can go quiet themselves. Clicking it as a visitor shows a hint to write instead. |
| F12 | Invoice agent | Left out. The rail shows only agents that have a YAML file. |
| F13 | License | AGPL-3.0-or-later. |
| F15 | Rooms for other company structures | Admins edit the floor plans under Admin → Rooms: several floors or sites, rooms on a grid (column, row, width, height), kinds talk room, quiet room and one hallway. A talk room may have a channel for its notes; without one it has no notes. "Only members" limits a room to that channel's members (a department's own room). Deleting a room sends anyone inside to the hallway and finishes running notes. |
| F14 | Editing and deleting | People and guests edit and delete their own messages; the other side sees the change live, edits are marked "edited". Backroom copies are snapshots and can't be edited. When a guest deletes a message, its backroom copy is deleted too. People can remove agent messages in internal channels. |

## Architecture

```
backend/atrium/
  policy.py          the wall: every read query starts here
  actors.py          UserActor | GuestActor | AgentActor | SystemActor
  models.py          SQLAlchemy 2 tables (no presence table)
  api/               internal REST + /ws
  guest/             guest REST under /g/api, own schemas, /g/ws, preview tokens
  llm/               provider neutral types, ContextBuilder, audited client, providers/
  agents/            YAML config, tool loop, tools (adapters + mocks)
  memory/            extraction, ask the backroom
  rooms/             in-memory presence, LiveKit tokens, notes + faster-whisper
  services/          posting, pulling, drafts, events, audit
frontend/src/
  app/               internal SPA
  guest/             guest SPA (separate bundle, imports nothing from app/)
  lib/               shared: api client, avatar, icons, formatting
agents/*.yaml        agent definitions and their allowed tools
deploy/              compose, Caddy, LiveKit config
```

Technical decisions:

- **One process, one uvicorn worker.** Presence and the WebSocket hub live in memory; more workers would need shared state, which is exactly what presence must not have. Enough for one company with a few hundred people. If it ever needs more: Postgres LISTEN/NOTIFY for messages, presence stays on one process.
- **Background work as asyncio tasks** in the same process (agent runs, memory extraction, transcription). Runs are rows in `agent_run`; on startup leftover running rows are marked aborted.
- **Two frontend entry points** from one Vite project. The guest bundle contains no code for backroom, agents or drafts (checked: no such strings in the built guest files).
- **Own small router** (hash routes) instead of a router library.
- **Postgres full text search** (`simple` config, generated `tsvector` column). No search server, no vector database.
- **Guest links are opaque 256 bit tokens**; the database stores only their SHA-256 with expiry and revocation. This replaces a signed link: revocation needs a database lookup anyway, and a leaked database holds no working links.
- **Sessions** are random tokens in HttpOnly SameSite=Lax cookies (`/` for people, `/g` for guests). State changing requests need `X-Requested-With: atrium` as CSRF guard. WebSockets check the origin.
- **Agents get deterministic tools.** The quote tool builds lines from the contract and prices them from the ERP and dispatch; the model only extracts parameters (customer, loads, new sites, markup). Sources on the card come from the tools that actually ran. This keeps small self hosted models usable.
- **"Ask the backroom" never guesses**: an answer without a valid source (a message label or memory id from its own context) is replaced by "I don't know that …".
- **Room notes**: while notes are on, each browser sends its own microphone audio (16 kHz PCM) over its WebSocket. Audio and transcript stay in memory; when notes go off the notes agent writes a summary into the room's channel and both are dropped. This avoids a LiveKit recording bot and LiveKit egress.
- **Logs**: uvicorn access log off, log level warning, Caddy access log discarded, LiveKit at `warn` without webhooks.

## The wall in the code

- `policy.readable_channel_ids(actor)` and `policy.readable_messages(actor)` are the only way to select channels and messages. An AST test fails if any other module selects `Channel`, `Message`, `Pull` or `MemoryEntry`.
- Agents: scope is the one channel of the run; only `internal` and `backroom` kinds; a second filter on kind in `readable_messages`.
- `ContextBuilder.add_messages` re-checks scope and channel kind and raises `WallViolation` for shared content. `LLMClient.complete` only accepts a `BuiltContext`, and writes `llm_call` + audit for every call (agent, trigger, context message ids, provider, model, time; never content).
- Pulling: `assert_can_pull` (person, member of the shared channel); a copy with `pulled_from_id`, a `pull` row and a `message.pulled` audit event.
- Drafts: an agent result becomes a `draft` owned by the person who clicks "Move to customer channel". Sending is a normal message by that person with `draft_ids`; the attachments move over, the work result and linked memory entries are closed, `draft.sent` is audited (including whether the text was edited).
- Guests: `guest/schemas.py` inherits nothing from `schemas.py` and forbids extra fields; `guest/serialize.py` refuses agent authors and non shared channels.

## Data model

`organization` (name, server location, interest rate, retention, LLM provider) · `user_account` · `user_session` · `agent` (rows for authorship; tools come from YAML) · `channel` (kind internal | backroom | shared, `backroom_for_id` unique, check constraint) · `channel_member` · `guest` (name, company, token hash, expiry, revoked) · `guest_session` · `message` (exactly one author, `pulled_from_id`, `from_draft_id`, `search`) · `attachment` (files on disk, rows point to storage keys) · `pull` · `agent_run` · `work_result` (kind, data, sources, `answers_message_ids`, status internal | with_user | sent) · `draft` · `memory_entry` (decided | open | committed, source message, status, done note) · `llm_call` · `audit_event` · `read_marker` (unread counters, people only) · `room` (configuration only: floor, grid cell and span, kind, notes channel, members only). Floors live in `organization.floors`.

Deliberately absent: presence, "last seen", IP addresses, read receipts for guests.

## API

Internal (`/api`, cookie): `auth/login|logout`, `me`, `users`, `channels` (list, create, detail, members), `channels/{id}/messages` (list, post with `attachment_ids` and `draft_ids`), `channels/{id}/read`, `messages/{id}/pull`, `files` (upload, download), `channels/{id}/guests` (invite), `guests/{id}` (revoke), `guests/{id}/preview`, `drafts` (list, patch, discard, remove attachment), `work-results/{id}` (edit prices), `work-results/{id}/stage`, `channels/{id}/memory`, `memory/{id}`, `ask`, `search`, `agents`, `rooms` (floors and rooms), `admin/*` (audit, settings, users, channels, guests export and delete, retention, `rooms`, `floors`), `ws`.

Guest (`/g/api`, own cookie or `Authorization: Preview …`): `join-info`, `session`, `me`, `channel`, `messages`, `files`, plus `/g/ws`.

WebSocket messages from the client: `room.join`, `room.leave`, `room.mute`, `room.notes`, `ping`, binary audio frames while notes are on.

## Dependencies

Backend: fastapi, uvicorn[standard] (websockets), sqlalchemy[asyncio], alembic, psycopg[binary] (async driver), pydantic-settings (typed ENV), argon2-cffi (password hashing), python-multipart (uploads, required by FastAPI forms), anthropic (default provider), httpx (OpenAI compatible endpoint, tests), pyyaml (agent files), weasyprint (quote PDF). Optional extra `notes`: faster-whisper, numpy. Dev: pytest. LiveKit tokens are signed with the standard library instead of `livekit-api`.

Frontend: svelte, vite, typescript, @sveltejs/vite-plugin-svelte, svelte-check, @playwright/test, livekit-client (WebRTC voice, loaded only when someone joins a room).

Run time: postgres:17, livekit-server, caddy.

## Verified

- Backend: 30 pytest tests including the wall tests.
- Browsers: 7 Playwright tests (live chat, pull invisible to guests, preview, invite, rooms, live edits and deletions, an admin building a new site with a members only room).
- Voice: `E2E_LIVEKIT_URL=ws://localhost:7880 npx playwright test e2e/voice.spec.ts` puts three browsers with fake microphones in one room over a local LiveKit server: all connect, each plays the other two, speakers show, mute shows, leaving drops out.
- Notes: a browser with a recorded sentence as microphone, notes on and off, local faster-whisper, summary by Qwen 3.6 in #dispatch. Colleagues' names go to whisper as a hint and to the notes agent for spelling.
- With Qwen 3.6 35B through Ollama: quote, memory, ask the backroom.

## Open

- Real Claude models not tested (no API key on the dev machine).
- Room notes need microphone permission; on a phone the browser stops audio when the screen locks.
- No i18n yet; UI strings are inline English.

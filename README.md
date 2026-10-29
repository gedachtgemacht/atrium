# Atrium

Self hosted team chat for companies, as an alternative to Teams and Slack, with one big difference: customers and partners join **shared channels** by link, and **AI agents work only in an internal backroom** next to them. No agent can read a customer channel or send anything to a customer. On top: rooms you drop into like on Discord, and a memory that keeps decisions, open questions and promises.

License: AGPL-3.0-or-later.

## How it works

- **Shared channel + backroom.** Every shared channel has exactly one backroom. Guests see the channel, never the backroom.
- **Pull in.** A person pulls a single customer message into the backroom. That makes a copy and an audit entry. Agents only ever see that copy.
- **Agents draft, people send.** Mention `@QuoteAgent` in the backroom. Its result is a card (lines, total, note, sources, reasoning). "Move to customer channel" puts text and PDF into *your* composer. It goes out only when you press Send, as your message.
- **Memory.** Decisions, open questions and promises are extracted from the backroom, each with its source. People can edit or delete entries. Promises and questions close when the matching draft is sent. "Ask the backroom" answers only from backroom and memory, always with a source, and says so when it doesn't know.
- **Rooms.** A floor plan with live presence and voice over LiveKit. Presence is never stored or logged. Notes run only when someone in the room turns them on; everyone sees it; audio is transcribed locally with faster-whisper and never stored.
- **The wall** is enforced in the backend and covered by tests that must never be weakened. See [CLAUDE.md](CLAUDE.md) and [docs/PLAN.md](docs/PLAN.md).

## Run it on a server

Needs Docker with Compose (or Podman with podman-compose), a domain pointing to the server, and ports 80, 443, 7881/tcp and 50000–50100/udp open.

```sh
git clone <this repo> atrium && cd atrium
cp .env.example .env          # set ATRIUM_DOMAIN, POSTGRES_PASSWORD, the LLM key, the LiveKit secret
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
```

Create the first account (or load the demo data):

```sh
# demo company with eight people and the customer Hollmann Bau
docker compose -f deploy/docker-compose.yml exec app python -m atrium.seed
```

The seed prints the sign-in emails (password `atrium-demo`, or set `ATRIUM_SEED_PASSWORD`) and two guest links.

For a real installation start empty and create the first admin; everything else happens under **Admin**:

```sh
docker compose -f deploy/docker-compose.yml exec app python -m atrium.cli create-admin \
  --org "Your Company" --location Frankfurt --email you@example.com --name "Your Name"
```

### Language model

Set in `.env`; admins can switch between configured providers under **Admin → Settings**.

- Anthropic API (default): `ATRIUM_LLM_PROVIDER=anthropic`, `ATRIUM_ANTHROPIC_API_KEY`, `ATRIUM_LLM_MODEL`.
- Self hosted, OpenAI compatible (vLLM, Ollama, llama.cpp server): `ATRIUM_LLM_PROVIDER=openai_compat`, `ATRIUM_OPENAI_COMPAT_BASE_URL`, `ATRIUM_OPENAI_COMPAT_MODEL`. For thinking models set `ATRIUM_OPENAI_COMPAT_REASONING=none` to keep answers fast.

Every LLM call shows up in **Admin → Audit log** with the agent, trigger, the ids of the messages in its context, provider and time.

### Agents

Agents are YAML files in `agents/`. The `tools` list is all an agent can use. The tools in `backend/atrium/agents/tools/` talk to company systems through adapters (`ErpAdapter`, `DispatchAdapter`, `ContractsAdapter`); V1 ships mocks with demo data. Replace them in `atrium/state.py` with adapters to your own systems.

### Operation

- **Backup:** the database and the `data` volume (uploads, generated PDFs, whisper models).
  ```sh
  docker compose -f deploy/docker-compose.yml exec db pg_dump -U atrium atrium | gzip > atrium-$(date +%F).sql.gz
  docker run --rm -v atrium_data:/data -v "$PWD":/out alpine tar czf /out/atrium-data-$(date +%F).tgz -C /data uploads
  ```
  Restore: `gunzip -c dump.sql.gz | docker compose … exec -T db psql -U atrium atrium`, and unpack the archive into the volume.
- **Updates:** `git pull && docker compose -f deploy/docker-compose.yml --env-file .env up -d --build`. Migrations run on start.
- **Retention:** Admin → Settings. Customer channels, internal channels, audit log and expired guests each get their own number of days. Runs daily; "Apply retention now" runs it at once.
- **Guest data:** Admin → Guests exports everything stored about a guest as JSON, or deletes the guest with their messages, backroom copies and files.
- **Logs:** the app, Caddy and LiveKit are configured not to log requests, so no log ties a person to a room.
- **Scale:** the app runs as a single process on purpose (presence lives in memory). That covers one company with a few hundred people.

## Develop

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 20+, Postgres 17.

```sh
podman run -d --name atrium-pg -e POSTGRES_USER=atrium -e POSTGRES_PASSWORD=atrium -e POSTGRES_DB=atrium -p 127.0.0.1:55432:5432 docker.io/library/postgres:17
podman exec atrium-pg psql -U atrium -c "CREATE DATABASE atrium_test" -c "CREATE DATABASE atrium_e2e"
podman run -d --name atrium-livekit --network host docker.io/livekit/livekit-server:v1.9 --dev --bind 127.0.0.1   # optional, voice

cd backend && uv sync --extra notes && uv run python -m atrium.seed --reset
uv run uvicorn atrium.main:app --reload --no-access-log        # http://localhost:8000
cd ../frontend && npm install && npm run dev                   # http://localhost:5173 with hot reload
```

`.env` in the repository root (see `.env.example`); for local voice use `ATRIUM_LIVEKIT_URL=ws://localhost:7880`, key `devkey`, secret `secret`. For a local model, Ollama works: `ATRIUM_LLM_PROVIDER=openai_compat`, `ATRIUM_OPENAI_COMPAT_BASE_URL=http://127.0.0.1:11434/v1`.

Tests:

```sh
cd backend && uv run pytest            # unit, flow and wall tests
cd frontend && npx playwright test     # end to end in real browsers
cd frontend && npm run check           # types
```

The wall tests in `backend/tests/wall/` are never weakened or skipped.

## Try the mockup flow

Sign in as `lena@kessler.example`, open **Hollmann Bau**, and open Sarah's guest link in a private window.

1. Sarah writes in her window; it shows up live for Lena.
2. At Sarah's first message: **Pull into backroom**, note `@QuoteAgent please price this: 40 loads a month, routes from 2026 plus Erfurt, prices 2026 plus 3 %.` The quote card shows Hamm €412, Münster €468, Erfurt new at €1,190, €23,488 a month.
3. **Change prices**, then **Move to customer channel**: text and PDF land in Lena's composer. **Send**. Sarah sees it as Lena's message.
4. Pull Sarah's payment terms question with `@QuoteAgent calculate the payment terms`. The card works out 45 instead of 30 days with the interest rate from the settings; **Draft a reply in the customer channel**.
5. **Memory** tab: the promise and the question are crossed out once the drafts are sent. Ask "What does Sarah want?".
6. **View as Sarah**: the real guest app, read only, without any trace of the backroom.
7. Rooms: click **Dispatch** in two browsers and talk; **Notes on** makes the notes agent appear as a square and, when switched off, posts a summary in #dispatch.

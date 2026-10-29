# Atrium: Plan

Stand 2026-10-29. Grundlage: Auftrag + `docs/mockup.html` (als Ansatz). Wartet auf OK.

## 1. Was das Mockup zeigt

Drei Spalten: links Räume (Grundriss) und Kanäle, Mitte der geteilte Kanal, rechts das Hinterzimmer mit den Tabs Arbeit und Gedächtnis. Unter 1180 px wird das Hinterzimmer zur Schublade, unter 760 px auch die linke Leiste.

Klickpfade, die das Mockup durchspielt:

| Pfad | Ablauf |
|---|---|
| Raum betreten | Klick auf Raum, eigener Kreis wandert hinein, Leiste "Du bist in …" mit Stumm, Notizen an/aus, Raum verlassen |
| Ruheraum | nicht betretbar, Hinweis "Ole arbeitet konzentriert. Schreib ihm lieber …" |
| Notizen | an/aus im Raum, Grundriss zeigt "Notizen an, von …", Protokollagent erscheint als Quadrat, Agentenliste zeigt "Schreibt mit in: …" |
| Reinholen | "Ins Hinterzimmer holen" an Sarahs Frage, Marke "Von dir ins Hinterzimmer geholt", Kopie als Karte im Hinterzimmer, dann rechnet der Agent das Zahlungsziel, Gedächtnis bekommt eine offene Frage |
| Angebot | Arbeitskarte mit Positionen, Summe, Hinweis, Quellen, Begründung, Berechtigungszeile; Preise ändern rechnet die Summe neu |
| Übernehmen | "In den Kundenkanal übernehmen": Text und PDF-Anhang im Nachrichtenfeld, Feld blinkt kurz, Status "Bei Lena"; Anhang entfernbar |
| Senden | Nachricht erscheint als Lena mit PDF, Karte "Gesendet", Zusage im Gedächtnis durchgestrichen, Agentenstatus "Fertig" |
| Zahlungsziel | "Antwort im Kundenkanal entwerfen" legt Text ins Feld, nach dem Senden ist die offene Frage erledigt |
| Gedächtnis | Entschieden / Offen / Zugesagt, Klick springt zur Quelle und lässt sie aufleuchten |
| Frag das Hinterzimmer | vier Beispielfragen, Antwort mit "Quelle zeigen", ehrliche Grenze: "Den Kundenkanal lese ich nicht mit …" |
| Suche oben | "Fragen oder suchen" leitet die Frage ins Gedächtnis-Tab |
| Als Sarah ansehen | Gast-Ansicht mit Banner "Vorschau", anderer Kopf, anderer Hinweis unter dem Feld, Entwurf wird solange weggelegt |

Was ich übernehme: die Tokens aus `:root` (hell, dunkel, `data-theme`), Schriften Bricolage Grotesque und Hanken Grotesk (beide OFL, liegen lokal als woff2), Formsprache Kreis/gestrichelt/Quadrat, Texte und Tonfall, Breakpoints.

Was ich anders mache als das Mockup:

- Die Gast-Ansicht ist eine eigene App mit eigener API, nicht dieselbe Seite mit `body.guest`. Die Vorschau lädt genau diese App.
- "Föderiert" und "Brandt Baustoffe, auf ihrem eigenen Server" fallen weg (Föderation ist nicht in V1), siehe Frage F1.

## 2. Architektur

```
atrium/
  backend/          FastAPI-App (Python 3.12)
    atrium/
      policy.py     einzige Stelle für Zugriffsregeln
      models/       SQLAlchemy 2
      api/          interne REST-Routen + WebSocket
      guest/        Gast-API: eigene Routen, eigene Schemas, eigener WebSocket
      llm/          Interface, ContextBuilder, Provider (anthropic, openai_compat, fake)
      agents/       Runner (Tool-Calling-Schleife), Werkzeug-Adapter + Mocks
      memory/       Extraktion, Frag das Hinterzimmer
      rooms/        Anwesenheit im Speicher, LiveKit-Token, Notizen
      realtime/     Hub: verteilt Ereignisse pro Verbindung durch die Policy
    migrations/     Alembic
    tests/          pytest, tests/wall/ = Pflicht-Tests
  frontend/         Svelte 5 + Vite + TS, zwei Einstiege: app.html (intern), guest.html (Gast)
  agents/*.yaml     Agenten-Definitionen und erlaubte Werkzeuge
  deploy/           docker-compose.yml, Caddyfile, livekit.yaml
  docs/
```

Entscheidungen, jeweils kurz begründet:

- **Ein Prozess, ein uvicorn-Worker.** Raum-Anwesenheit und der WebSocket-Hub leben im Speicher. Mit mehreren Workern bräuchte die Anwesenheit einen geteilten Speicher, und genau den wollen wir nicht. Für die Größe (eine Firma, bis einige hundert Leute) reicht ein asyncio-Prozess. Wenn es später mehr braucht: Postgres LISTEN/NOTIFY für Nachrichten, Anwesenheit bleibt an einem Prozess.
- **Hintergrundarbeit als asyncio-Tasks im selben Prozess** (Agentenläufe, Gedächtnis-Extraktion, PDF). Kein Celery, kein Redis. Läufe landen vorher als Datensatz `agent_run`, damit ein Neustart sie wieder aufnehmen oder als abgebrochen markieren kann.
- **Zwei Frontend-Einstiege aus einem Vite-Projekt.** Das Gast-Bundle enthält keinen Code für Hinterzimmer, Agenten oder Entwürfe. Ein Gast kann also nicht mal im JavaScript sehen, wie das Hinterzimmer aussieht. Gemeinsam sind nur CSS-Tokens und Grundbausteine (Avatar, Nachricht, Nachrichtenfeld).
- **Eigener kleiner Router** in Svelte statt einer Router-Bibliothek. Es gibt eine Handvoll Ansichten.
- **Caddy als Reverse Proxy** im Compose (TLS automatisch, eine Datei Konfiguration). Für lokal optional.
- **Suche über Postgres-Volltext** (`german`-Konfiguration, `tsvector`-Spalte). Kein Elasticsearch, keine Vektor-DB. Frag das Hinterzimmer nutzt dieselbe Suche plus Gedächtnis als Kandidaten, das LLM wählt und zitiert.

### 2.1 Die Wand im Code

**Akteure.** Jede Anfrage und jede WebSocket-Verbindung hat genau einen Akteur: `UserActor`, `GuestActor` oder `AgentActor`. Routen bekommen ihn über eine FastAPI-Dependency. Interne Routen akzeptieren nur `UserActor`, Gast-Routen nur `GuestActor`, Agenten haben gar keine HTTP-Routen, sie laufen nur im Prozess.

**policy.py** liefert:

- `readable_channels(actor) -> Select`: SQL-Filter. Agent: nur Kanäle mit `kind in (internal, backroom)` und nur der Kanal, in dem der Lauf gestartet wurde. Gast: nur sein einer geteilter Kanal. Nutzer: Kanäle, in denen er Mitglied ist.
- `readable_messages(actor) -> Select`: baut auf dem Kanal-Filter auf. Jede Nachrichtenabfrage im Code startet hier, auch Suche, Gedächtnis und Frag das Hinterzimmer.
- `assert_can_post(actor, channel)`: Agent in `shared` → 403. Gast nur in seinem Kanal.
- `assert_can_pull(actor, message)`: nur Nutzer, die Nachricht muss in einem geteilten Kanal liegen, in dem er Mitglied ist.
- `event_visible(actor, event) -> bool`: Filter im WebSocket-Hub. Ereignisse aus dem Hinterzimmer gehen nie an Gast-Verbindungen, Ereignisse aus geteilten Kanälen nie an Agenten.

Ein Test prüft per AST, dass außerhalb von `policy.py` niemand direkt `select(Message)` oder `select(Channel)` baut.

**ContextBuilder.** Der LLM-Client hat nur eine Methode `complete(ctx: BuiltContext, tools)`. `BuiltContext` entsteht nur über `ContextBuilder.add_message(msg)`, der `msg.channel.kind` prüft und bei `shared` `WallViolation` wirft. Werkzeug-Ergebnisse (ERP, Dispo) und Gedächtnis-Einträge gehen über eigene `add_*`-Methoden, Gedächtnis-Einträge tragen ihre Quell-Nachricht und werden ebenfalls geprüft. Der Builder sammelt die Nachrichten-IDs, die im LLM-Protokoll landen.

**Reinholen** erzeugt eine neue Nachricht im Hinterzimmer mit `pulled_from_id` und Text und Autor des Originals als Kopie. Das Original bleibt im geteilten Kanal und für Agenten unlesbar. Die Kopie ist eine normale Hinterzimmer-Nachricht.

**Gast-Schemas** liegen in `guest/schemas.py` und erben von nichts aus den internen Schemas. Gast-Nachrichten haben nur `id, author{name, initials, kind: guest|staff}, body, attachments, created_at`. Kein `pulled`, kein `draft_id`, keine Agenten-IDs. Interne Mitarbeiter heißen für den Gast "Kessler Logistik" statt "Vertrieb".

**Logs.** uvicorn-Access-Log ist aus. Die App loggt keine Pfade mit Personen- oder Raumbezug. LiveKit läuft mit Log-Level `warn`, ohne Webhooks, ohne Egress.

### 2.2 Agenten

`agents/angebot.yaml` (Beispiel):

```yaml
slug: angebotsagent
name: Angebotsagent
initial: A
tools: [erp.preise, dispo.kapazitaet, vertraege.konditionen, ergebnis.angebot, ergebnis.zahlungsziel]
system: |
  Du rechnest Angebote für {firma}. ...
```

Ablauf bei `@Angebotsagent` im Hinterzimmer: `agent_run` anlegen, ContextBuilder mit den letzten Hinterzimmer-Nachrichten dieses Kanals und dem Gedächtnis dieses Kanals, dann die Tool-Calling-Schleife (höchstens 8 Runden). Ein Werkzeug, das nicht in der YAML steht, gibt es für den Agenten nicht: der Runner reicht es nicht ans LLM durch und lehnt den Aufruf ab, falls das Modell ihn trotzdem versucht. Das Ergebnis ist eine Agenten-Nachricht im Hinterzimmer plus ein `work_result` (strukturiert, z. B. Positionen).

Werkzeuge sind Adapter mit Interface und Mock: `ErpAdapter.preise(strecken)`, `DispoAdapter.kapazitaet(strecke, monat)`, `VertragsAdapter.konditionen(kunde)`. Die Mocks liefern die Zahlen aus dem Mockup.

### 2.3 LLM-Anbieter

`llm/providers/anthropic.py` (offizielles SDK), `openai_compat.py` (direkt über httpx, kein openai-SDK nötig), `fake.py` (für Tests, zeichnet Payloads auf, antwortet nach Skript). Auswahl über `LLM_PROVIDER`, Modell über `LLM_MODEL` (Standard `claude-sonnet-5-5`), Key über `ANTHROPIC_API_KEY` bzw. `OPENAI_COMPAT_BASE_URL` + `OPENAI_COMPAT_API_KEY`. In Phase 6 lässt sich der Anbieter auf der Admin-Seite wählen, Keys bleiben in der ENV.

### 2.4 Räume und Sprache (ab Phase 5)

Raumliste ist Konfiguration (Name, Art normal/ruhig, Position im Grundriss, zugehöriger interner Kanal für Notizen). Anwesenheit ist ein Dict im Prozess, verteilt über den WebSocket. Betreten und Verlassen laufen als WebSocket-Nachricht, nicht als HTTP-Route. Der Backend-Prozess stellt LiveKit-Tokens aus. Der Protokollagent ist ein LiveKit-Teilnehmer, der nur bei eingeschalteten Notizen beitritt, Audio im Speicher an faster-whisper gibt und am Ende eine Zusammenfassung in den internen Kanal des Raums schreibt. Rohaudio und Rohtranskript werden nicht gespeichert.

## 3. Datenmodell

IDs als UUIDv7 (sortierbar, nicht erratbar). Zeiten in UTC.

| Tabelle | Felder (Auswahl) | Hinweis |
|---|---|---|
| `organization` | name, server_location ("Frankfurt"), interest_rate, retention (jsonb), llm_provider | eine Organisation pro Installation in V1 |
| `user` | email, password_hash (argon2), name, initials, tone, role_label ("Vertrieb"), is_admin | |
| `user_session` | token_hash, user_id, expires_at | Cookie HttpOnly, SameSite=Lax |
| `agent` | slug, name, initial | Werkzeuge kommen aus der YAML, nicht aus der DB |
| `channel` | kind `internal`/`backroom`/`shared`, name, partner_name, backroom_for_id (unique) | Check: jeder `shared` hat genau ein `backroom`, beide in derselben Transaktion angelegt |
| `channel_member` | channel_id, user_id | nur interne Nutzer |
| `guest` | channel_id, name (leer bis zum ersten Öffnen), company, token_hash, expires_at, revoked_at, invited_by | keine E-Mail |
| `guest_session` | token_hash, guest_id, expires_at | Widerruf des Gasts löscht alle Sitzungen |
| `message` | channel_id, author_user_id / author_guest_id / author_agent_id (genau eins), body, created_at, edited_at, pulled_from_id, from_draft_id, search (tsvector) | |
| `attachment` | owner (message_id oder draft_id), filename, mime, size, sha256, path | Dateien im Volume, nicht in der DB |
| `pull` | original_id, copy_id, pulled_by, pulled_at | unique(original_id), zweites Reinholen zeigt auf die Kopie |
| `work_result` | channel_id, message_id, agent_id, kind (`angebot`, `zahlungsziel`), data (jsonb), status `intern`/`bei_nutzer`/`gesendet` | Preise ändern = PATCH auf data |
| `draft` | owner_user_id, shared_channel_id, work_result_id, agent_id, body, status `offen`/`gesendet`/`verworfen`, sent_message_id | |
| `memory_entry` | channel_id, kind `entschieden`/`offen`/`zugesagt`, text, owner_user_id, due (Datum) + due_label ("bis Freitag"), source_message_id, status `aktiv`/`erledigt`, done_by_draft_id, created_by (agent/user) | |
| `agent_run` | agent_id, channel_id, trigger (`mention`/`memory`/`ask`/`notes`), trigger_message_id, status | |
| `llm_call` | agent_id, run_id, trigger, context_message_ids (uuid[]), provider, model, at, tokens_in/out | speichert keine Inhalte |
| `audit_event` | at, actor, action, subject_ids, details (jsonb) | Reinholen, Entwurf erstellt/gesendet/verworfen, Gast eingeladen/beigetreten/widerrufen/exportiert/gelöscht, LLM-Aufruf (Verweis auf `llm_call`) |
| `read_marker` | user_id, channel_id, last_read_id | für die Zähler in der Leiste, nur interne Nutzer |
| `room` | name, kind `normal`/`ruhig`, grid_area, channel_id | Konfiguration, keine Anwesenheit |

Bewusst nicht da: Anwesenheit, "zuletzt online", Lesebestätigungen für Gäste, IP-Adressen.

Gedächtnis "erledigt": Wird ein Entwurf gesendet, setzt der Server alle Einträge auf erledigt, die an seinem `work_result` oder an der Quell-Nachricht hängen, aus der das Ergebnis entstand. Die Extraktion verknüpft dafür offene Fragen und Zusagen mit dem passenden Arbeitsergebnis. Das ersetzt den Trick im Mockup, der nach "45" im Text sucht.

## 4. API-Skizze

Intern (`/api`, Cookie-Sitzung):

```
POST   /api/auth/login | /api/auth/logout        GET /api/me
GET    /api/channels                             (inkl. backroom_id bei geteilten)
GET    /api/channels/{id}/messages?before=
POST   /api/channels/{id}/messages               {body, draft_id?}  sendet ggf. den Entwurf
POST   /api/messages/{id}/pull                   → Kopie + Audit
GET    /api/channels/{id}/guests                 POST (Einladung → Link)
DELETE /api/guests/{id}                          Widerruf
POST   /api/guests/{id}/preview                  kurzlebiges Lese-Token für "Als Sarah ansehen"
GET    /api/drafts?channel=                      PATCH /api/drafts/{id}  DELETE (verwerfen)
PATCH  /api/work-results/{id}                    Preise ändern
POST   /api/work-results/{id}/stage              → Entwurf mit PDF im eigenen Nachrichtenfeld
GET    /api/channels/{id}/memory                 PATCH|DELETE /api/memory/{id}
POST   /api/ask                                  {channel_id?, question} → {answer, sources[]}
GET    /api/search?q=                            Volltext über alles, was der Nutzer lesen darf
GET    /api/rooms                                POST /api/rooms/{id}/token (LiveKit)
GET    /api/admin/audit  /settings  /guests/{id}/export  DELETE /api/admin/guests/{id}
WS     /ws
```

Gast (`/g`, eigene Sitzung):

```
GET    /g/{token}                    liefert guest.html
POST   /g/api/session                {token, name?} → Sitzung
GET    /g/api/channel                Kanal, Firma, Hinweistext, Mitglieder
GET    /g/api/messages?before=       POST /g/api/messages
POST   /g/api/attachments
WS     /g/ws
```

Vorschau: `guest.html` im iframe mit dem Vorschau-Token. Das Token gilt 10 Minuten, nur lesend, läuft durch genau dieselben Gast-Routen und Schemas.

## 5. Abhängigkeiten

Backend:

| Paket | Warum |
|---|---|
| fastapi, uvicorn[standard] | gesetzt; `standard` bringt websockets mit |
| sqlalchemy 2, alembic, psycopg[binary] | gesetzt; psycopg 3 kann async |
| pydantic-settings | ENV-Konfiguration typisiert, kommt aus dem FastAPI-Umfeld |
| argon2-cffi | Passwort-Hashing, Stand der Technik, keine eigene Krypto |
| anthropic | Standard-Anbieter |
| httpx | OpenAI-kompatibler Endpunkt und Test-Client in einem |
| pyyaml | `agents/*.yaml` |
| weasyprint | PDF (Phase 3, gesetzt) |
| livekit-api, livekit (rtc) | Tokens und Protokollagent als Teilnehmer (Phase 5) |
| faster-whisper | Transkription (Phase 6, gesetzt) |
| pytest, pytest-asyncio | Tests |

Frontend: svelte, vite, typescript, @sveltejs/vite-plugin-svelte, @playwright/test. Sonst nichts.

Betrieb: postgres:17, livekit/livekit-server, caddy. Gast-Links werden aus opaken 256-Bit-Zufallstokens gebaut, in der DB liegt nur der Hash mit Ablaufdatum und Widerruf. Das ist der "signierte Link" aus dem Auftrag, nur ohne Signaturschlüssel, weil wir für den Widerruf sowieso in die DB schauen.

Lokal: Python 3.12 über uv, Postgres als Podman-Container. Die Compose-Datei läuft mit Docker Compose und podman-compose.

## 6. Tests

- `tests/wall/test_kanarie.py`: legt `KANARIE-7f3a` als Sarah-Nachricht an, löst Erwähnung, Gedächtnis-Extraktion, Frag das Hinterzimmer, globale Frage oben und (ab Phase 5/6) Raumnotizen aus. Prüft alle Payloads des Fake-Clients und zusätzlich die `llm_call.context_message_ids`. Zweiter Teil: Lena holt die Nachricht rein, danach darf die Kanarie im Kontext stehen, aber nur mit der ID der Kopie.
- `test_agent_post_shared.py`: Agent schreibt in den geteilten Kanal → 403, auch über den Runner-Pfad, nicht nur über die Route.
- `test_guest_api.py`: ruft jede Route unter `/g` automatisch auf (aus dem Router generiert, damit neue Routen automatisch dabei sind), legt vorher Hinterzimmer-Inhalte mit einer zweiten Kanarie an und prüft: keine verbotenen Felder (`pulled`, `draft`, `agent`, `backroom`, `role_label`, …), keine Hinterzimmer-Texte. Dasselbe für den Gast-WebSocket.
- `test_presence.py`: Raum betreten, reden, Notizen aus, verlassen. Danach Vergleich der gesamten DB (alle Tabellen, Zeilenzahlen und Inhalte) und der erfassten Logs: kein Raum-Personen-Bezug.
- `conftest.py`: LLM-Keys leer, ausgehendes Netz gesperrt (socket-Patch), eigene Test-DB.
- Playwright ab Phase 1: Lena und Sarah in zwei Browser-Kontexten chatten live; ab Phase 2 der Ablauf Reinholen, Übernehmen, Senden, Vorschau.

## 7. Phase 1 konkret

1. Gerüst: Backend, Frontend, Compose, Alembic, Seed-Skript.
2. Login, Sitzung, `/api/me`.
3. Kanäle, Nachrichten, WebSocket-Hub mit Policy-Filter.
4. Geteilter Kanal + Hinterzimmer (Anlage in einer Transaktion).
5. Gast-Einladung, Gast-Beitritt mit Namen, Gast-App mit Hinweistext, Widerruf.
6. `policy.py`, `ContextBuilder`, Fake-Agent, alle vier Wand-Tests (Raum-Test zunächst gegen die Anwesenheits-Schicht ohne LiveKit).
7. Seed: Kessler Logistik, Lena, Tom, Aylin, Jonas, Mia, Kai, Sven, Ole, Kanäle #dispo #lager #vertrieb #ankündigungen, Hollmann Bau mit Sarah und Jan, die Nachrichten aus dem Mockup.

## 8. Offene Fragen an dich

Produktfragen, jeweils mit meinem Vorschlag:

- **F1 Föderation im Mockup.** "Föderiert" und "Brandt Baustoffe, auf ihrem eigenen Server" passen nicht zu V1. Vorschlag: beides raus, der Chip oben zeigt nur "Euer Server, {Ort}".
- **F2 Wer sieht das Hinterzimmer?** Vorschlag: die internen Mitglieder des geteilten Kanals, nicht automatisch alle Mitarbeiter. Admins können sich hinzufügen.
- **F3 Löst Reinholen einen Agenten aus?** Im Mockup rechnet der Agent nach dem Reinholen sofort los, im Auftrag startet nur eine @-Erwähnung. Vorschlag: Reinholen startet nur die Gedächtnis-Extraktion. Beim Reinholen gibt es ein optionales Feld "Notiz fürs Hinterzimmer", in das man `@Angebotsagent` schreiben kann. Dann sind es zwei Klicks statt einer, und kein Agent läuft, ohne dass ein Mensch es wollte.
- **F4 Gast-Link.** Vorschlag: ein persönlicher Link pro Gast. Er gilt bis zum Ablauf auf beliebig vielen Geräten, der Name wird beim ersten Öffnen festgelegt. Ablauf standardmäßig 90 Tage, beim Einladen änderbar. Widerruf beendet alle Sitzungen sofort. Alternative: Einmal-Link, dann braucht jedes neue Gerät einen neuen Link.
- **F5 Gäste aus mehreren Firmen in einem Kanal?** "Frachtpool, 6 Firmen" spricht dafür. Vorschlag: ja, jeder Gast hat ein optionales Feld Firma. Der Kanal hat einen Partnernamen für die Anzeige.
- **F6 Dürfen Gäste Dateien hochladen?** Vorschlag: ja, PDF und Bilder bis 20 MB.
- **F7 Agenten in normalen internen Kanälen.** Der Auftrag sagt "nur im Hinterzimmer", der Protokollagent schreibt aber in den internen Kanal des Raums. Vorschlag: Agenten dürfen in allen internen Kanälen arbeiten (also auch #dispo), nie in geteilten. Der ContextBuilder nimmt dann alle internen Kanäle an, aber immer nur den einen Kanal, in dem der Lauf gestartet wurde.
- **F8 Gedächtnis pro Kanal oder für die ganze Firma?** Vorschlag: pro Hinterzimmer bzw. internem Kanal. "Frag das Hinterzimmer" im Tab fragt das aktuelle, die Frage oben im Kopf fragt alle Hinterzimmer, in denen du Mitglied bist.
- **F9 Suchfeld oben.** Menschen dürfen geteilte Kanäle lesen, die KI nicht. Vorschlag: Das Feld macht beides getrennt. Oben stehen Volltext-Treffer aus allem, was du lesen darfst. Darunter steht "Frag das Hinterzimmer" mit der KI-Antwort, die nur Hinterzimmer und Gedächtnis kennt.
- **F10 Raumnotizen und Namen.** Eine Zusammenfassung mit "Tom sagte …" verrät, wer im Raum war. Wenn Notizen an sind, wissen das alle, insofern ist das gewollt. Vorschlag: Die Zusammenfassung nennt, wer die Notizen eingeschaltet hat, und Zusagen mit Namen ("Tom bestätigt die Frächter"). Sie enthält aber keine Teilnehmerliste und keine Uhrzeiten von Kommen und Gehen.
- **F11 Ruheraum.** Ole sitzt drin, andere kommen nicht rein. Vorschlag: Jeder kann sich selbst in den Ruheraum setzen (Status "konzentriert", kein Ton). Andere bekommen den Hinweis zum Schreiben.
- **F12 Rechnungsagent.** Steht im Mockup, aber in keiner Phase. Vorschlag: In V1 weglassen, die Leiste zeigt nur Agenten mit YAML-Datei.
- **F13 Lizenz.** Vorschlag: AGPL-3.0, damit niemand Atrium als geschlossenen Dienst weiterverkauft, ohne die Änderungen offenzulegen. Alternative: Apache-2.0, wenn Firmen es möglichst frei einbauen sollen.

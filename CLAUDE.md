# Atrium

Selbst gehostete Firmen-Kollaboration. Kunden und Partner sind per Link in geteilten Kanälen dabei, KI-Agenten arbeiten nur im internen Hinterzimmer daneben. Plan und Architektur: `docs/PLAN.md`. Gestaltungsvorlage (Ansatz, nicht Pixelvorgabe): `docs/mockup.html`.

## Die Wand: nicht verhandelbar

Diese Regeln werden im Backend erzwungen, nie nur in der UI.

1. Agenten haben keinen Lesezugriff auf geteilte Kanäle. Das gilt für jeden Weg: Nachrichten-API, Suche, WebSocket, Gedächtnis, "Frag das Hinterzimmer" und den Kontext für LLM-Aufrufe.
2. In geteilten Kanälen schreiben nur Menschen. Die API lehnt Nachrichten von Agenten dort ab (403).
3. Eine Kundennachricht kommt nur ins Hinterzimmer, wenn ein interner Mensch sie aktiv reinholt. Das erzeugt eine Kopie im Hinterzimmer und einen Audit-Eintrag (wer, wann, welche Nachricht).
4. Agenten erzeugen nur Entwürfe. Ein Entwurf landet im Nachrichtenfeld eines Menschen im geteilten Kanal. Gesendet wird er nur durch dessen Klick, und die Nachricht hat diesen Menschen als Autor.
5. Gäste sehen nichts Internes: kein Hinterzimmer, keine Agenten, keine Entwürfe, keinen Hinweis "ins Hinterzimmer geholt", keine interne Herkunft einer Nachricht. Gäste haben eigene Antwort-Schemas (`backend/atrium/guest/schemas.py`), nicht dieselben Schemas mit ausgeblendeten Feldern.
6. Räume speichern keine Anwesenheit. Wer wann in welchem Raum war, wird nirgends gespeichert oder geloggt. Notizen laufen nur, wenn jemand im Raum sie einschaltet. Alle im Raum sehen das, und ohne Notizen wird nichts aufgezeichnet.
7. Jeder LLM-Aufruf wird protokolliert: Agent, Auslöser, welche Nachrichten-IDs im Kontext waren, Anbieter, Zeitpunkt.

### Wo die Wand im Code steht

- Zugriffsregeln stehen nur in `backend/atrium/policy.py`. Jeder Lesepfad (REST, Suche, WebSocket-Fanout, Gedächtnis, Frag-das-Hinterzimmer, Agenten-Kontext) geht über die Query-Filter und Prüfungen dort. Keine eigene Zugriffslogik in Routen oder Services.
- Der LLM-Client nimmt Kontext nur als `BuiltContext` aus `backend/atrium/llm/context.py` (`ContextBuilder`). Der Builder nimmt ausschließlich Nachrichten aus internen Kanälen an und wirft sonst `WallViolation`.
- Anbieter-Logik (Anthropic, OpenAI-kompatibel) liegt nur in `backend/atrium/llm/providers/`.
- Raum-Anwesenheit lebt nur im Speicher (`backend/atrium/rooms/presence.py`). Kein Datenbankobjekt, kein Log-Eintrag, keine HTTP-Route mit Raum und Person im Pfad.

### Pflicht-Tests der Wand (`backend/tests/wall/`)

- Kanarien-Test: `KANARIE-7f3a` im geteilten Kanal, danach jeder Agenten-Pfad. Der Fake-LLM-Client zeichnet alle Payloads auf, der Text darf nirgends auftauchen. Erst nach dem Reinholen durch einen Menschen darf er auftauchen.
- Agent schreibt in geteilten Kanal: 403.
- Keine Route der Gast-API liefert interne Felder oder Hinterzimmer-Inhalte.
- Nach einem Raumbesuch existiert kein Datensatz über die Anwesenheit.

Diese Tests werden nie abgeschwächt, übersprungen, mit `xfail` markiert oder umgebaut, um etwas grün zu bekommen. Schlägt einer fehl, ist der Code falsch, nicht der Test. Neue Lesepfade oder Agenten-Auslöser bekommen einen Eintrag im Kanarien-Test.

## Tests

- Tests laufen nie gegen echte Zugangsdaten. `conftest.py` leert alle LLM-Keys und sperrt ausgehendes Netz. LLM nur über den Fake-Client.
- Backend: `pytest` gegen eine eigene Test-Datenbank. Frontend-Abläufe: Playwright.

## Konventionen

- UI-Texte auf Deutsch, kurz, Du-Form, keine Gedankenstriche.
- Formsprache: Kreis = Mensch, gestrichelter Kreis = Gast, Quadrat = Agent.
- Kein Tracking, keine Analytics, keine externen Skripte oder CDNs. Schriften liegen lokal.
- Abhängigkeiten klein halten, jede neue in `docs/PLAN.md` begründen.

"""Server side texts in the organization's language: emails, notes, tool output, customer drafts.

The UI has its own dictionaries in frontend/src/lib/i18n. Keep the tone: short, casual, no dashes.
"""

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "mail.footer": "You get this because you're in {org}'s Atrium. Change it under Settings.",
        "mail.user.subject.one": "{who} in {where}",
        "mail.user.subject.many": "{n} new things in Atrium",
        "mail.user.mention": "{who} mentioned you in {where}.",
        "mail.user.customer": "{who} wrote in the customer channel {where}.",
        "mail.user.agent": "{who} finished your request in {where}.",
        "mail.user.open": "Open Atrium: {link}",
        "mail.guest.subject": "New message from {org}",
        "mail.guest.body": "Hi {name},\n\n{who} from {org} wrote in your shared channel.\n\nOpen it here: {link}\nThe link signs you in for 7 days.",
        "mail.guest.unsub": "No more emails: {link}",
        "notes.header": "Notes from {room}, switched on by {who}",
        "ask.dont_know": "I don't know that. I don't read the customer channel, I only see what you pull into the backroom.",
        "ask.no_model": "I can't answer right now because the language model isn't reachable.",
        "agent.no_model": "I couldn't reach the language model, so nothing was calculated. Try again in a moment.",
        "quote.draft": "{hi} here's our quote for {year}.{new} The details are in the document.",
        "quote.hi": "Hi {name},",
        "quote.hi_plain": "Hi,",
        "quote.new_one": " {places} is now included.",
        "quote.new_many": " {places} are now included.",
        "quote.and": "and",
        "quote.reason_known": "{places}: contract prices {year} from the ERP, plus {markup} % as requested.",
        "quote.reason_new": "{place} has no price yet. Calculated with about {km} km one way, our standard rate per km",
        "quote.reason_sub": " and {pct} % on top for the loads with the subcontractor.",
        "quote.reason_capacity": "Dispatch shows {free} free slots a month on the route from {month}.",
        "quote.note_sub": "Our own trucks can do {own} of the {loads} loads to {place} in the first month. A subcontractor runs the other {sub}, that's already priced in.",
        "quote.note_volume": "The customer asked for {wanted} loads a month, the contract routes alone already have more. Check the volumes.",
        "quote.title": "Quote {customer} {year}",
        "quote.pdf": "Quote {year} {customer}.pdf",
        "quote.summary": "{n} routes, {loads} loads, {total} a month",
        "src.erp": "Prices from the ERP",
        "src.dispatch": "Capacity from dispatch",
        "src.contract": "Terms from the contract {year}",
        "src.quote": "Revenue from the quote draft",
        "src.rate": "Interest rate from the settings",
        "pay.title": "{req} instead of {cur} days",
        "pay.later": "Customer pays on average",
        "pay.later_v": "{days} days later",
        "pay.outstanding": "Extra outstanding",
        "pay.cost": "Cost at {rate} % interest",
        "pay.cost_v": "about {amount} a year",
        "pay.share": "Share of revenue",
        "pay.about": "about {v}",
        "pay.note": "Suggestion: {req} days for {pct} % higher prices. Or {cur} days, then the quote stays as it is.",
        "pay.draft": "{hi} {req} days works if prices go up by {pct} %. With {cur} days the quote stays as it is. Which works better for you?",
        "guest.notice": "Only people from {org} write here. Messages are stored on their server{where}. {org} may work on single messages internally with AI.",
        "guest.where": " in {place}",
        "mem.answered_by": "Answered, sent by {name}",
        "mem.done_by": "Done, sent by {name}",
        "mem.marked_done": "Marked done by {name}",
        "language_name": "English",
    },
    "de": {
        "mail.footer": "Du bekommst das, weil du im Atrium von {org} bist. Ändern kannst du das unter Einstellungen.",
        "mail.user.subject.one": "{who} in {where}",
        "mail.user.subject.many": "{n} Neuigkeiten im Atrium",
        "mail.user.mention": "{who} hat dich in {where} erwähnt.",
        "mail.user.customer": "{who} hat im Kundenkanal {where} geschrieben.",
        "mail.user.agent": "{who} ist mit deinem Auftrag in {where} fertig.",
        "mail.user.open": "Atrium öffnen: {link}",
        "mail.guest.subject": "Neue Nachricht von {org}",
        "mail.guest.body": "Hallo {name},\n\n{who} von {org} hat in eurem gemeinsamen Kanal geschrieben.\n\nHier geht es zum Kanal: {link}\nDer Link meldet dich für 7 Tage an.",
        "mail.guest.unsub": "Keine E-Mails mehr: {link}",
        "notes.header": "Notizen aus {room}, eingeschaltet von {who}",
        "ask.dont_know": "Dazu weiß ich nichts. Den Kundenkanal lese ich nicht mit, ich sehe nur, was ihr ins Hinterzimmer holt.",
        "ask.no_model": "Ich kann gerade nicht antworten, das Sprachmodell ist nicht erreichbar.",
        "agent.no_model": "Ich habe das Sprachmodell nicht erreicht, deshalb ist nichts gerechnet. Versuch es gleich noch mal.",
        "quote.draft": "{hi} hier unser Angebot für {year}.{new} Die Details stehen im Dokument.",
        "quote.hi": "Hallo {name},",
        "quote.hi_plain": "Hallo,",
        "quote.new_one": " {places} ist neu dabei.",
        "quote.new_many": " {places} sind neu dabei.",
        "quote.and": "und",
        "quote.reason_known": "{places}: Vertragspreise {year} aus dem ERP, plus {markup} % wie gewünscht.",
        "quote.reason_new": "{place} hat noch keinen Preis. Gerechnet mit rund {km} km einfach, unserem Standardsatz pro Kilometer",
        "quote.reason_sub": " und {pct} % Aufschlag für die Ladungen beim Subunternehmer.",
        "quote.reason_capacity": "Die Dispo zeigt ab {month} {free} freie Plätze im Monat auf der Strecke.",
        "quote.note_sub": "Unsere eigenen LKW schaffen im ersten Monat {own} der {loads} Ladungen nach {place}. Die anderen {sub} fährt ein Subunternehmer, das ist im Preis schon drin.",
        "quote.note_volume": "Der Kunde will {wanted} Ladungen im Monat, die Vertragsstrecken allein haben schon mehr. Prüf die Mengen.",
        "quote.title": "Angebot {customer} {year}",
        "quote.pdf": "Angebot {year} {customer}.pdf",
        "quote.summary": "{n} Strecken, {loads} Ladungen, {total} im Monat",
        "src.erp": "Preise aus dem ERP",
        "src.dispatch": "Kapazität aus der Dispo",
        "src.contract": "Konditionen aus dem Vertrag {year}",
        "src.quote": "Umsatz aus dem Angebotsentwurf",
        "src.rate": "Zinssatz aus den Einstellungen",
        "pay.title": "{req} statt {cur} Tage",
        "pay.later": "Kunde zahlt im Schnitt",
        "pay.later_v": "{days} Tage später",
        "pay.outstanding": "Länger offen",
        "pay.cost": "Kosten bei {rate} % Zins",
        "pay.cost_v": "rund {amount} im Jahr",
        "pay.share": "Anteil am Umsatz",
        "pay.about": "etwa {v}",
        "pay.note": "Vorschlag: {req} Tage gegen {pct} % höhere Preise. Oder {cur} Tage, dann bleibt das Angebot, wie es ist.",
        "pay.draft": "{hi} {req} Tage gehen, wenn die Preise um {pct} % steigen. Mit {cur} Tagen bleibt das Angebot, wie es ist. Was passt euch besser?",
        "guest.notice": "Hier schreiben nur Menschen von {org}. Nachrichten liegen auf deren Server{where}. {org} kann einzelne Nachrichten intern mit KI bearbeiten.",
        "guest.where": " in {place}",
        "mem.answered_by": "Beantwortet, gesendet von {name}",
        "mem.done_by": "Erledigt, gesendet von {name}",
        "mem.marked_done": "Als erledigt markiert von {name}",
        "language_name": "Deutsch",
    },
}

LANGUAGES = tuple(TEXTS)


def lang(code: str | None) -> str:
    code = (code or "").lower()[:2]
    return code if code in TEXTS else "en"


def t(language: str | None, key: str, **kw) -> str:
    table = TEXTS[lang(language)]
    return (table.get(key) or TEXTS["en"][key]).format(**kw)


def money(language: str | None, n: float) -> str:
    if lang(language) == "de":
        return f"{n:,.0f} €".replace(",", ".")
    return f"€{n:,.0f}"


def number(language: str | None, n: float, digits: int = 2) -> str:
    s = f"{n:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{n:.0f}"
    return s.replace(".", ",") if lang(language) == "de" else s

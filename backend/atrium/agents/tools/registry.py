"""Tools agents can call. An agent only ever gets the tools listed in its YAML file."""

import json
import math
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ... import policy
from ...actors import AgentActor
from ...i18n import money, number, t
from ...llm.base import ToolSpec, tool_schema
from ...models import (
    AuthorKind,
    Channel,
    MemoryEntry,
    MemoryKind,
    MemoryStatus,
    Organization,
    WorkResult,
)
from .adapters import ContractsAdapter, DispatchAdapter, ErpAdapter


@dataclass
class ToolEnv:
    session: AsyncSession
    agent: AgentActor
    channel: Channel | None
    org: Organization
    labels: dict[str, uuid.UUID]
    run_id: uuid.UUID | None
    erp: ErpAdapter
    dispatch: DispatchAdapter
    contracts: ContractsAdapter
    used: set[str] = field(default_factory=set)
    created: list[WorkResult] = field(default_factory=list)
    memory_changed: bool = False
    answer: dict | None = None
    today: date = field(default_factory=date.today)

    def resolve(self, refs) -> list[uuid.UUID]:
        out = []
        for r in refs or []:
            r = str(r).strip().strip("[]")
            if r in self.labels:
                out.append(self.labels[r])
        return out


@dataclass
class Tool:
    spec: ToolSpec
    run: Callable[[ToolEnv, dict], Awaitable[Any]]


TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, schema: dict):
    def wrap(fn):
        TOOLS[name] = Tool(ToolSpec(name=name, description=description, input_schema=schema), fn)
        return fn

    return wrap


def eur(n: float) -> str:
    return f"€{n:,.0f}"


def round_to(n: float, step: int) -> int:
    return int(math.floor(n / step + 0.5) * step)


_route = {"type": "object", "properties": {"origin": {"type": "string"}, "destination": {"type": "string"}}, "required": ["origin", "destination"]}
_labels = {"type": "array", "items": {"type": "string"}, "description": "Message labels like m2"}


@tool("erp_prices", "Last year's contract price per load for routes from the ERP, plus distance and the standard rate per km.",
      tool_schema(routes={"type": "array", "items": _route}))
async def erp_prices(env: ToolEnv, args: dict):
    env.used.add("erp")
    routes = [(r["origin"], r["destination"]) for r in args.get("routes", [])]
    return [p.__dict__ for p in env.erp.prices(routes, env.today.year)]


@tool("dispatch_capacity", "Free slots per month for our own trucks on a route, from dispatch.",
      tool_schema(origin=("string", "Origin"), destination=("string", "Destination"), month=("string", "Month as YYYY-MM")))
async def dispatch_capacity(env: ToolEnv, args: dict):
    env.used.add("dispatch")
    return {"free_slots_per_month": env.dispatch.free_slots(args["origin"], args["destination"], args.get("month", ""))}


@tool("contract_terms", "The current contract with a customer: routes, monthly volumes, payment days.",
      tool_schema(customer=("string", "Customer name")))
async def contract_terms(env: ToolEnv, args: dict):
    env.used.add("contracts")
    t = env.contracts.terms(args.get("customer", ""))
    return t.__dict__ if t else {"error": "No contract found"}


def quote_total(lines: list[dict]) -> int:
    return int(sum(l["loads"] * l["rate"] for l in lines))


def quote_summary(data: dict) -> str:
    L = data.get("language")
    loads = sum(l["loads"] for l in data["lines"])
    return t(L, "quote.summary", n=len(data["lines"]), loads=loads, total=money(L, data["total_per_month"]))


def joined(L, items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} {t(L, 'quote.and')} {items[-1]}"


@tool(
    "create_quote",
    "Create a quote as a work result in the backroom. Routes and volumes come from the customer's contract, "
    "new sites get the remaining loads. Prices are calculated here from the ERP, dispatch and contract.",
    {
        "type": "object",
        "properties": {
            "customer": {"type": "string", "description": "Customer company, e.g. Hollmann Bau"},
            "year": {"type": "integer", "description": "Year the quote is for"},
            "markup_pct": {"type": "number", "description": "Price increase on last year's prices in percent, e.g. 3"},
            "loads_per_month": {"type": "integer", "description": "Total loads per month the customer asked for"},
            "new_destinations": {"type": "array", "items": {"type": "string"}, "description": "New sites that are not in the contract yet, e.g. Erfurt"},
            "first_month": {"type": "string", "description": "YYYY-MM"},
            "answers": _labels,
            "greeting_name": {"type": "string", "description": "First name of the customer contact"},
        },
        "required": ["customer", "year", "markup_pct", "loads_per_month", "answers"],
    },
)
async def create_quote(env: ToolEnv, args: dict):
    if env.channel is None:
        return {"error": "No channel"}
    env.used.update({"erp", "contracts"})
    L = env.org.language
    year = int(args.get("year") or env.today.year + 1)
    markup = float(args.get("markup_pct") or 0)
    terms = env.contracts.terms(args.get("customer", "")) or env.contracts.terms(env.channel.partner_name or "")
    if terms is None:
        return {"error": "No contract found for this customer. Ask the colleague which routes and volumes to use."}
    sub_markup = terms.subcontractor_markup_pct
    month = args.get("first_month") or f"{year}-01"
    wanted = int(args.get("loads_per_month") or 0)
    base_routes = [(r["origin"], r["destination"], int(r["loads_per_month"])) for r in terms.routes]
    contract_destinations = {d.lower() for _, d, _ in base_routes}
    new = [d.strip() for d in args.get("new_destinations") or [] if d.strip() and d.strip().lower() not in contract_destinations]
    rest = max(0, wanted - sum(l for *_, l in base_routes)) if wanted else 0
    origin = base_routes[0][0] if base_routes else "Dortmund"
    plan = list(base_routes)
    for i, d in enumerate(new):
        share = rest // len(new) + (1 if i < rest % len(new) else 0)
        if share:
            plan.append((origin, d, share))
    lines, reasoning, notes, known = [], [], [], []
    for o, d, loads in plan:
        p = env.erp.prices([(o, d)], year - 1)[0]
        if p.price is not None:
            rate = round(p.price * (1 + markup / 100))
            lines.append({"origin": o, "destination": d, "loads": loads, "rate": rate, "new": False})
            known.append(d)
        else:
            env.used.add("dispatch")
            free = env.dispatch.free_slots(o, d, month)
            own = min(free, loads)
            sub = loads - own
            base = p.distance_km * p.rate_per_km
            avg = (own * base + sub * base * (1 + sub_markup / 100)) / max(loads, 1)
            rate = round_to(avg, 10)
            lines.append({"origin": o, "destination": d, "loads": loads, "rate": rate, "new": True})
            reasoning.append(
                t(L, "quote.reason_new", place=d, km=f"{p.distance_km:.0f}")
                + (t(L, "quote.reason_sub", pct=f"{sub_markup:.0f}") if sub else ".")
            )
            reasoning.append(t(L, "quote.reason_capacity", free=free, month=month))
            if sub:
                notes.append(t(L, "quote.note_sub", own=own, loads=loads, place=d, sub=sub))
    if known:
        reasoning.insert(0, t(L, "quote.reason_known", places=joined(L, known), year=year - 1, markup=number(L, markup)))
    if wanted and sum(l["loads"] for l in lines) != wanted:
        notes.append(t(L, "quote.note_volume", wanted=wanted))
    customer = terms.customer
    short = customer.replace(" GmbH", "")
    data = {
        "customer": customer,
        "year": year,
        "markup_pct": markup,
        "lines": lines,
        "total_per_month": quote_total(lines),
        "note": " ".join(notes),
        "reasoning": reasoning,
        "greeting_name": (args.get("greeting_name") or "").split(" ")[0],
        "pdf_name": t(L, "quote.pdf", year=year, customer=short),
        "language": L,
    }
    data["draft_text"] = quote_draft_text(data)
    sources = [t(L, "src.erp")]
    if "dispatch" in env.used:
        sources.append(t(L, "src.dispatch"))
    sources.append(t(L, "src.contract", year=terms.year))
    w = WorkResult(
        channel_id=env.channel.id, agent_id=env.agent.agent_id, run_id=env.run_id, kind="quote",
        title=t(L, "quote.title", customer=short, year=year), data=data, sources=sources,
        answers_message_ids=env.resolve(args.get("answers")),
    )
    env.session.add(w)
    await env.session.flush()
    env.created.append(w)
    return {"work_result_id": str(w.id), "total_per_month": data["total_per_month"], "lines": lines, "note": data["note"]}


def quote_draft_text(data: dict) -> str:
    L = data.get("language")
    hi = t(L, "quote.hi", name=data["greeting_name"]) if data.get("greeting_name") else t(L, "quote.hi_plain")
    new = [l["destination"] for l in data["lines"] if l.get("new")]
    extra = t(L, "quote.new_one" if len(new) == 1 else "quote.new_many", places=joined(L, new)) if new else ""
    return t(L, "quote.draft", hi=hi, year=data["year"], new=extra)


@tool(
    "calculate_payment_terms",
    "Work out what longer payment terms cost us, based on the latest quote in this backroom and the interest rate from the settings.",
    {
        "type": "object",
        "properties": {
            "current_days": {"type": "integer"},
            "requested_days": {"type": "integer"},
            "answers": _labels,
            "greeting_name": {"type": "string"},
        },
        "required": ["current_days", "requested_days", "answers"],
    },
)
async def calculate_payment_terms(env: ToolEnv, args: dict):
    if env.channel is None:
        return {"error": "No channel"}
    quote = (
        await env.session.execute(
            select(WorkResult)
            .where(WorkResult.channel_id == env.channel.id, WorkResult.kind == "quote")
            .order_by(WorkResult.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if quote is None:
        return {"error": "No quote in this backroom yet, so there is no revenue to calculate with."}
    cur, req = int(args["current_days"]), int(args["requested_days"])
    rate = float(env.org.interest_rate_pct)
    yearly = quote.data["total_per_month"] * 12
    extra_days = req - cur
    outstanding = yearly * extra_days / 365
    cost = outstanding * rate / 100
    share = cost / yearly * 100 if yearly else 0
    surcharge = math.ceil(share * 10) / 10
    L = env.org.language
    name = (args.get("greeting_name") or "").split(" ")[0]
    hi = t(L, "quote.hi", name=name) if name else t(L, "quote.hi_plain")
    pct = number(L, surcharge, 1)
    data = {
        "current_days": cur,
        "requested_days": req,
        "rows": [
            {"label": t(L, "pay.later"), "value": t(L, "pay.later_v", days=extra_days)},
            {"label": t(L, "pay.outstanding"), "value": t(L, "pay.about", v=money(L, round_to(outstanding, 100)))},
            {"label": t(L, "pay.cost", rate=number(L, rate)), "value": t(L, "pay.cost_v", amount=money(L, round_to(cost, 50)))},
            {"label": t(L, "pay.share"), "value": t(L, "pay.about", v=f"{number(L, round(share, 2))} %")},
        ],
        "note": t(L, "pay.note", req=req, cur=cur, pct=pct),
        "draft_text": t(L, "pay.draft", hi=hi, req=req, cur=cur, pct=pct),
        "surcharge_pct": surcharge,
        "language": L,
    }
    w = WorkResult(
        channel_id=env.channel.id, agent_id=env.agent.agent_id, run_id=env.run_id, kind="payment_terms",
        title=t(L, "pay.title", req=req, cur=cur), data=data,
        sources=[t(L, "src.quote"), t(L, "src.rate")],
        answers_message_ids=env.resolve(args.get("answers")),
    )
    env.session.add(w)
    await env.session.flush()
    env.created.append(w)
    return {"work_result_id": str(w.id), "rows": data["rows"], "note": data["note"]}


_entry = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["decided", "open", "committed"]},
        "text": {"type": "string"},
        "owner": {"type": "string"},
        "due": {"type": "string", "description": "Like 'by Friday', empty if none"},
        "source": {"type": "string", "description": "Message label like m3"},
    },
    "required": ["kind", "text", "source"],
}


@tool(
    "record_memory",
    "Record new memory entries and mark existing ones as resolved.",
    {
        "type": "object",
        "properties": {
            "entries": {"type": "array", "items": _entry},
            "resolve": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string"}, "note": {"type": "string"}}, "required": ["id"]}},
        },
        "required": ["entries"],
    },
)
async def record_memory(env: ToolEnv, args: dict):
    if env.channel is None:
        return {"error": "No channel"}
    existing = await policy.channel_memory(env.session, env.agent, env.channel.id)
    seen = {(e.kind.value, e.text.strip().lower()) for e in existing}
    added = 0
    for raw in args.get("entries") or []:
        try:
            kind = MemoryKind(raw.get("kind"))
        except ValueError:
            continue
        text = (raw.get("text") or "").strip()
        if not text or (kind.value, text.lower()) in seen:
            continue
        src = env.resolve([raw.get("source")])
        env.session.add(
            MemoryEntry(
                channel_id=env.channel.id, kind=kind, text=text[:500], owner_name=(raw.get("owner") or "")[:200],
                due_label=(raw.get("due") or "")[:100], source_message_id=src[0] if src else None,
                created_by_kind=AuthorKind.agent,
            )
        )
        seen.add((kind.value, text.lower()))
        added += 1
    by_id = {str(e.id): e for e in existing}
    resolved = 0
    for r in args.get("resolve") or []:
        e = by_id.get(str(r.get("id")))
        if e is not None and e.status == MemoryStatus.active and e.kind != MemoryKind.decided:
            from ...db import utcnow

            e.status = MemoryStatus.done
            e.done_at = utcnow()
            e.done_note = (r.get("note") or "Resolved in the backroom")[:300]
            resolved += 1
    if added or resolved:
        env.memory_changed = True
    return {"added": added, "resolved": resolved}


@tool(
    "answer",
    "Give the answer to the question.",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "known": {"type": "boolean", "description": "False if the material does not contain the answer"},
            "sources": {"type": "array", "items": {"type": "string"}, "description": "Message labels or memory ids"},
        },
        "required": ["text", "known", "sources"],
    },
)
async def answer(env: ToolEnv, args: dict):
    env.answer = {"text": args.get("text", ""), "known": bool(args.get("known")), "sources": list(args.get("sources") or [])}
    return {"ok": True}


def specs_for(names) -> list[ToolSpec]:
    return [TOOLS[n].spec for n in names if n in TOOLS]


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)

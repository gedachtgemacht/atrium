"""ContextBuilder: the only way content reaches an LLM.

It accepts messages and memory entries from internal channels (internal and
backroom) inside the agent's scope, plus tool results and room transcripts.
Anything from a shared channel raises WallViolation. The builder records the
message ids it let through; they end up in the llm_call audit row.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from .. import policy
from ..actors import AgentActor
from ..models import Channel, MemoryEntry, Message
from .base import ToolCall, ToolResult, Turn

_TOKEN = object()


@dataclass
class BuiltContext:
    system: str
    turns: list[Turn]
    message_ids: list[uuid.UUID]
    agent: AgentActor
    trigger: str
    _token: object = field(repr=False, default=None)

    def __post_init__(self):
        if self._token is not _TOKEN:
            raise TypeError("BuiltContext can only be created by ContextBuilder")

    def add_assistant(self, text: str, tool_calls: list[ToolCall]) -> None:
        self.turns.append(Turn(role="assistant", text=text, tool_calls=tool_calls))

    def add_tool_results(self, results: list[ToolResult]) -> None:
        self.turns.append(Turn(role="user", tool_results=results))


class ContextBuilder:
    def __init__(self, session: AsyncSession, agent: AgentActor, trigger: str):
        self.session = session
        self.agent = agent
        self.trigger = trigger
        self._system = ""
        self._parts: list[str] = []
        self._ids: list[uuid.UUID] = []
        self._labels: dict[uuid.UUID, str] = {}

    def system(self, text: str) -> "ContextBuilder":
        self._system = text
        return self

    def label(self, message_id: uuid.UUID) -> str:
        return self._labels[message_id]

    @property
    def labels(self) -> dict[str, uuid.UUID]:
        return {v: k for k, v in self._labels.items()}

    async def _check_channel(self, channel_id: uuid.UUID) -> Channel:
        if channel_id not in self.agent.scope_channel_ids:
            raise policy.WallViolation("message outside the agent's channel scope")
        kind = await policy.channel_kind(self.session, channel_id)
        policy.assert_agent_context_channel(kind)
        return await policy.get_channel(self.session, self.agent, channel_id)

    def _ref(self, message_id: uuid.UUID) -> str:
        if message_id not in self._labels:
            self._labels[message_id] = f"m{len(self._labels) + 1}"
        return self._labels[message_id]

    async def add_messages(self, messages: list[Message], heading: str = "") -> "ContextBuilder":
        lines = [heading] if heading else []
        for m in messages:
            await self._check_channel(m.channel_id)
            if m.id not in self._ids:
                self._ids.append(m.id)
            lines.append(self._render(m))
        if lines:
            self._parts.append("\n".join(lines))
        return self

    def _render(self, m: Message) -> str:
        when = m.created_at.strftime("%Y-%m-%d %H:%M")
        if m.author_agent is not None:
            who = f"{m.author_agent.name} (agent)"
        elif m.author_guest is not None:
            who = f"{m.author_guest.name or 'Guest'} (customer)"
        elif m.author_user is not None:
            who = m.author_user.name
        else:
            who = "Unknown"
        note = " [pulled in from the customer channel by a colleague]" if m.pulled_from_id else ""
        files = "".join(f" [file: {a.filename}]" for a in m.attachments)
        return f"[{self._ref(m.id)}] {when} {who}{note}: {m.body}{files}"

    async def add_memory(self, entries: list[MemoryEntry], heading: str = "Memory") -> "ContextBuilder":
        lines = [heading]
        for e in entries:
            await self._check_channel(e.channel_id)
            src = ""
            if e.source_message_id is not None:
                # The source must itself be readable by this agent, otherwise the entry stays out.
                found = await policy.messages_by_ids(self.session, self.agent, [e.source_message_id])
                if not found:
                    continue
                if e.source_message_id not in self._ids:
                    self._ids.append(e.source_message_id)
                src = f" (source {self._ref(e.source_message_id)})"
            due = f", due {e.due_label}" if e.due_label else ""
            owner = f", owner {e.owner_name}" if e.owner_name else ""
            lines.append(f"- [{e.id}] {e.kind.value}: {e.text}{owner}{due}, status {e.status.value}{src}")
        if len(lines) > 1:
            self._parts.append("\n".join(lines))
        return self

    def add_text(self, heading: str, text: str) -> "ContextBuilder":
        """Content that is not a channel message: room transcripts, the user's question, instructions."""
        self._parts.append(f"{heading}\n{text}" if heading else text)
        return self

    def build(self) -> BuiltContext:
        first = Turn(role="user", text="\n\n".join(self._parts))
        return BuiltContext(
            system=self._system,
            turns=[first],
            message_ids=list(self._ids),
            agent=self.agent,
            trigger=self.trigger,
            _token=_TOKEN,
        )

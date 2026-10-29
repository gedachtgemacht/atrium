"""Scripted provider for tests. Records every payload it receives."""

import json
from collections.abc import Callable

from ..base import LLMResponse, ToolSpec, Turn

Script = Callable[[str, list[Turn], list[ToolSpec]], LLMResponse]


class FakeProvider:
    name = "fake"

    def __init__(self, model: str = "fake-1"):
        self.model = model
        self.calls: list[dict] = []
        self.script: Script | None = None

    def payloads(self) -> list[str]:
        return [json.dumps(c, default=str, ensure_ascii=False) for c in self.calls]

    async def complete(self, *, system: str, turns: list[Turn], tools: list[ToolSpec]) -> LLMResponse:
        self.calls.append(
            {
                "system": system,
                "turns": [t.__dict__ | {"tool_calls": [c.__dict__ for c in t.tool_calls], "tool_results": [r.__dict__ for r in t.tool_results]} for t in turns],
                "tools": [t.name for t in tools],
            }
        )
        if self.script is None:
            return LLMResponse(text="Done.", tool_calls=[])
        return self.script(system, turns, tools)

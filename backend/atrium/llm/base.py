"""Provider neutral types for LLM calls. Nothing here knows about Anthropic or OpenAI."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class Turn:
    """One conversation turn. role is user or assistant; tool results travel in user turns."""

    role: str
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    input_tokens: int | None = None
    output_tokens: int | None = None


class Provider(Protocol):
    name: str
    model: str

    async def complete(self, *, system: str, turns: list[Turn], tools: list[ToolSpec]) -> LLMResponse: ...


class ProviderError(Exception):
    pass


def tool_schema(**props: Any) -> dict:
    """Small helper: tool_schema(text=("string", "What to remember"), ...) -> JSON schema."""
    properties, required = {}, []
    for key, spec in props.items():
        if isinstance(spec, dict):
            properties[key] = spec
        else:
            typ, desc = spec
            properties[key] = {"type": typ, "description": desc}
        required.append(key)
    return {"type": "object", "properties": properties, "required": required}

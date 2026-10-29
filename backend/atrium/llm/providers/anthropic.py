import anthropic

from ..base import LLMResponse, ProviderError, ToolCall, ToolSpec, Turn


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ProviderError("ATRIUM_ANTHROPIC_API_KEY is not set")
        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    @staticmethod
    def _turn(t: Turn) -> dict:
        content: list[dict] = []
        for r in t.tool_results:
            content.append({"type": "tool_result", "tool_use_id": r.call_id, "content": r.content, "is_error": r.is_error})
        if t.text:
            content.append({"type": "text", "text": t.text})
        for c in t.tool_calls:
            content.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments})
        return {"role": t.role, "content": content}

    async def complete(self, *, system: str, turns: list[Turn], tools: list[ToolSpec]) -> LLMResponse:
        try:
            resp = await self._client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system,
                messages=[self._turn(t) for t in turns],
                tools=[{"name": s.name, "description": s.description, "input_schema": s.input_schema} for s in tools],
            )
        except anthropic.APIError as e:
            raise ProviderError(str(e)) from e
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [ToolCall(id=b.id, name=b.name, arguments=dict(b.input)) for b in resp.content if b.type == "tool_use"]
        return LLMResponse(text=text, tool_calls=calls, input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens)

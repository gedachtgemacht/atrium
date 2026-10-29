"""Any OpenAI compatible chat completions endpoint (vLLM, Ollama, llama.cpp server, ...)."""

import json

import httpx

from ..base import LLMResponse, ProviderError, ToolCall, ToolSpec, Turn


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str, model: str):
        if not base_url:
            raise ProviderError("ATRIUM_OPENAI_COMPAT_BASE_URL is not set")
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    @staticmethod
    def _messages(system: str, turns: list[Turn]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for t in turns:
            for r in t.tool_results:
                out.append({"role": "tool", "tool_call_id": r.call_id, "content": r.content})
            if t.role == "assistant":
                msg: dict = {"role": "assistant", "content": t.text or ""}
                if t.tool_calls:
                    msg["tool_calls"] = [
                        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                        for c in t.tool_calls
                    ]
                out.append(msg)
            elif t.text:
                out.append({"role": "user", "content": t.text})
        return out

    async def complete(self, *, system: str, turns: list[Turn], tools: list[ToolSpec]) -> LLMResponse:
        body = {
            "model": self.model,
            "messages": self._messages(system, turns),
            "tools": [
                {"type": "function", "function": {"name": s.name, "description": s.description, "parameters": s.input_schema}}
                for s in tools
            ],
        }
        if not tools:
            body.pop("tools")
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                r = await client.post(self._url, json=body, headers=self._headers)
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderError(str(e)) from e
        choice = data["choices"][0]["message"]
        calls = []
        for i, c in enumerate(choice.get("tool_calls") or []):
            fn = c.get("function", {})
            args = fn.get("arguments") or "{}"
            try:
                parsed = json.loads(args) if isinstance(args, str) else dict(args)
            except json.JSONDecodeError:
                parsed = {}
            calls.append(ToolCall(id=c.get("id") or f"call_{i}", name=fn.get("name", ""), arguments=parsed))
        usage = data.get("usage") or {}
        return LLMResponse(
            text=choice.get("content") or "",
            tool_calls=calls,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

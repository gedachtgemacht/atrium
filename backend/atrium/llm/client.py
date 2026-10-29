"""LLMClient: takes a BuiltContext, calls the configured provider, writes the llm_call audit row."""

import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker

from ..config import Settings
from ..models import AuditEvent, LlmCall
from .base import LLMResponse, Provider, ProviderError, ToolSpec
from .context import BuiltContext


def make_provider(settings: Settings, name: str | None = None) -> Provider:
    name = name or settings.llm_provider
    if name == "anthropic":
        from .providers.anthropic import AnthropicProvider

        return AnthropicProvider(settings.anthropic_api_key, settings.llm_model)
    if name == "openai_compat":
        from .providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            settings.openai_compat_base_url,
            settings.openai_compat_api_key,
            settings.openai_compat_model or settings.llm_model,
            settings.openai_compat_reasoning,
        )
    if name == "fake":
        from .providers.fake import FakeProvider

        return FakeProvider()
    raise ProviderError(f"Unknown LLM provider {name!r}")


def available_providers(settings: Settings) -> list[str]:
    out = []
    if settings.anthropic_api_key:
        out.append("anthropic")
    if settings.openai_compat_base_url:
        out.append("openai_compat")
    if settings.llm_provider == "fake":
        out.append("fake")
    return out


class LLMClient:
    def __init__(self, sessions: async_sessionmaker, settings: Settings, provider: Provider | None = None):
        self._sessions = sessions
        self._settings = settings
        self._fixed = provider
        self._cache: dict[str, Provider] = {}

    def provider(self, name: str | None) -> Provider:
        if self._fixed is not None:
            return self._fixed
        key = name or self._settings.llm_provider
        if key not in self._cache:
            self._cache[key] = make_provider(self._settings, key)
        return self._cache[key]

    async def complete(
        self,
        ctx: BuiltContext,
        tools: list[ToolSpec],
        *,
        run_id: uuid.UUID | None,
        provider_name: str | None = None,
    ) -> LLMResponse:
        if not isinstance(ctx, BuiltContext):
            raise TypeError("LLMClient only accepts a BuiltContext from ContextBuilder")
        prov = self.provider(provider_name)
        ok, resp = True, None
        try:
            resp = await prov.complete(system=ctx.system, turns=ctx.turns, tools=tools)
            return resp
        except ProviderError:
            ok = False
            raise
        finally:
            async with self._sessions() as s:
                call = LlmCall(
                    run_id=run_id,
                    agent_id=ctx.agent.agent_id,
                    trigger=ctx.trigger,
                    context_message_ids=list(ctx.message_ids),
                    provider=prov.name,
                    model=prov.model,
                    input_tokens=resp.input_tokens if resp else None,
                    output_tokens=resp.output_tokens if resp else None,
                    ok=ok,
                )
                s.add(call)
                await s.flush()
                s.add(
                    AuditEvent(
                        org_id=ctx.agent.org_id,
                        actor_kind="agent",
                        actor_id=ctx.agent.agent_id,
                        actor_name=ctx.agent.name,
                        action="llm.call",
                        subject_id=call.id,
                        details={
                            "trigger": ctx.trigger,
                            "provider": prov.name,
                            "model": prov.model,
                            "context_message_ids": [str(i) for i in ctx.message_ids],
                            "ok": ok,
                        },
                    )
                )
                await s.commit()

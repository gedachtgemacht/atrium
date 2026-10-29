"""Agent definitions from agents/*.yaml. The YAML decides which tools an agent can use."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class AgentConfig:
    slug: str
    handle: str
    name: str
    initial: str
    role: str  # mention | memory | ask | notes
    description: str = ""
    permission: str = ""
    system: str = ""
    tools: tuple[str, ...] = field(default_factory=tuple)
    hidden: bool = False
    # Translations, e.g. {"de": {"name": "Angebotsagent", "description": "...", "permission": "..."}}
    translations: dict = field(default_factory=dict)


def load_agents(directory: Path) -> dict[str, AgentConfig]:
    out: dict[str, AgentConfig] = {}
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text()) or {}
        cfg = AgentConfig(
            slug=raw["slug"], handle=raw["handle"], name=raw["name"], initial=raw.get("initial", raw["name"][:1]),
            role=raw.get("role", "mention"), description=raw.get("description", ""),
            permission=raw.get("permission", ""), system=raw.get("system", ""),
            tools=tuple(raw.get("tools") or ()), hidden=bool(raw.get("hidden", False)),
            translations=raw.get("translations") or {},
        )
        out[cfg.slug] = cfg
    return out


def _tr(cfg: AgentConfig, lang: str | None, key: str) -> str:
    return (cfg.translations.get((lang or "")[:2]) or {}).get(key) or getattr(cfg, key)


def agent_name(cfg: AgentConfig, lang: str | None) -> str:
    return _tr(cfg, lang, "name")


def agent_description(cfg: AgentConfig, lang: str | None) -> str:
    return _tr(cfg, lang, "description")


def agent_initial(cfg: AgentConfig, lang: str | None) -> str:
    return _tr(cfg, lang, "initial")


def agent_permission(cfg: AgentConfig, lang: str | None) -> str:
    return _tr(cfg, lang, "permission")

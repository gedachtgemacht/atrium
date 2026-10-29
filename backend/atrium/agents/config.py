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


def load_agents(directory: Path) -> dict[str, AgentConfig]:
    out: dict[str, AgentConfig] = {}
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text()) or {}
        cfg = AgentConfig(
            slug=raw["slug"], handle=raw["handle"], name=raw["name"], initial=raw.get("initial", raw["name"][:1]),
            role=raw.get("role", "mention"), description=raw.get("description", ""),
            permission=raw.get("permission", ""), system=raw.get("system", ""),
            tools=tuple(raw.get("tools") or ()), hidden=bool(raw.get("hidden", False)),
        )
        out[cfg.slug] = cfg
    return out

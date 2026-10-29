"""Everything the running app holds in memory, shared by routes, sockets and background tasks."""

from dataclasses import dataclass, field

from .agents.config import AgentConfig
from .agents.tools.adapters import (
    ContractsAdapter,
    DispatchAdapter,
    ErpAdapter,
    MockContracts,
    MockDispatch,
    MockErp,
)
from .config import Settings
from .db import Database
from .llm.client import LLMClient
from .realtime.hub import Hub
from .tasks import TaskRunner


@dataclass
class AppState:
    settings: Settings
    db: Database
    llm: LLMClient
    agents: dict[str, AgentConfig]
    hub: Hub = field(default_factory=Hub)
    tasks: TaskRunner = field(default_factory=TaskRunner)
    erp: ErpAdapter = field(default_factory=MockErp)
    dispatch: DispatchAdapter = field(default_factory=MockDispatch)
    contracts: ContractsAdapter = field(default_factory=MockContracts)
    memory_delay: float = 1.5
    presence: object = None  # atrium.rooms.presence.Presence, set in main
    notes: object = None  # atrium.rooms.notes.NotesService, set in main
    notifier: object = None  # atrium.notify.Notifier, set in main
    agent_ids: dict = field(default_factory=dict)  # slug -> agent.id
    agent_permissions: dict = field(default_factory=dict)  # agent.id -> permission line

    def agent_by_handle(self, handle: str) -> AgentConfig | None:
        h = handle.lower()
        for a in self.agents.values():
            if a.handle.lower() == h and a.role in ("mention", "notes") and not a.hidden:
                return a
        return None

    def agent_with_role(self, role: str) -> AgentConfig | None:
        for a in self.agents.values():
            if a.role == role:
                return a
        return None

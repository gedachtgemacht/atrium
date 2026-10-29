"""Who is acting. Every request, socket and agent run has exactly one actor."""

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class UserActor:
    user_id: uuid.UUID
    org_id: uuid.UUID
    name: str
    is_admin: bool = False


@dataclass(frozen=True)
class GuestActor:
    guest_id: uuid.UUID
    channel_id: uuid.UUID
    name: str
    # Preview sessions ("View as Sarah") may read but never write.
    read_only: bool = False


@dataclass(frozen=True)
class AgentActor:
    agent_id: uuid.UUID
    org_id: uuid.UUID
    name: str
    # The internal channels this run was started in. An agent never sees anything else.
    scope_channel_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)


@dataclass(frozen=True)
class SystemActor:
    """Maintenance jobs (retention, export). Never used for LLM context."""

    org_id: uuid.UUID


Actor = UserActor | GuestActor | AgentActor | SystemActor

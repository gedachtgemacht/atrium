import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..actors import Actor, AgentActor, GuestActor, SystemActor, UserActor
from ..models import AuditEvent


def audit(session: AsyncSession, org_id: uuid.UUID, actor: Actor, action: str, subject_id=None, **details) -> None:
    if isinstance(actor, UserActor):
        kind, aid, name = "user", actor.user_id, actor.name
    elif isinstance(actor, GuestActor):
        kind, aid, name = "guest", actor.guest_id, actor.name
    elif isinstance(actor, AgentActor):
        kind, aid, name = "agent", actor.agent_id, actor.name
    else:
        kind, aid, name = "system", None, "System"
    clean = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in details.items()}
    session.add(AuditEvent(org_id=org_id, actor_kind=kind, actor_id=aid, actor_name=name, action=action,
                           subject_id=subject_id, details=clean))


__all__ = ["audit", "SystemActor"]

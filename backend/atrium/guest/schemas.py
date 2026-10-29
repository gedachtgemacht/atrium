"""Response schemas for guests.

Separate classes on purpose: they inherit nothing from atrium.schemas, so an
internal field can never leak by forgetting to hide it. extra="forbid" makes
building one with an unknown field fail loudly.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class GuestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GuestAuthor(GuestModel):
    kind: Literal["guest", "staff"]
    id: uuid.UUID
    name: str
    initials: str


class GuestFile(GuestModel):
    id: uuid.UUID
    filename: str
    mime: str
    size: int
    url: str


class GuestMessage(GuestModel):
    id: uuid.UUID
    author: GuestAuthor
    body: str
    created_at: datetime
    attachments: list[GuestFile]


class GuestChannel(GuestModel):
    company_name: str
    partner_name: str
    notice: str
    members: list[GuestAuthor]


class GuestMe(GuestModel):
    id: uuid.UUID
    name: str
    company: str
    preview: bool


class GuestJoinInfo(GuestModel):
    company_name: str
    needs_name: bool
    suggested_name: str


class GuestEvent(GuestModel):
    type: Literal["message.created", "members.updated"]
    message: GuestMessage | None = None
    members: list[GuestAuthor] | None = None

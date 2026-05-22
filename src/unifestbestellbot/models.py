"""SQLModel definitions for the three persisted tables."""

from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel


class TicketStatus(StrEnum):
    OPEN = "open"
    WIP = "wip"
    CLOSED = "closed"


_STATUS_DISPLAY = {
    TicketStatus.OPEN: "🟠 OPEN",
    TicketStatus.WIP: "🟢 WIP",
    TicketStatus.CLOSED: "✅ CLOSED",
}


def _now() -> datetime:
    return datetime.now(UTC)


class Registration(SQLModel, table=True):
    chat_id: int = Field(primary_key=True)
    group_name: str = Field(index=True)
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    registered_at: datetime = Field(default_factory=_now)

    def display_name(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        name = " ".join(parts) or "Unbekannt"
        return f"{name} <@{self.username}>" if self.username else name


class Ticket(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    status: TicketStatus = Field(default=TicketStatus.OPEN, index=True)
    category: str
    text: str
    group_requesting: str
    group_tasked: str = Field(index=True)
    who_wip: str | None = None
    created_at: datetime = Field(default_factory=_now)
    closed_at: datetime | None = None

    def display(self) -> str:
        return f"{_STATUS_DISPLAY[self.status]} #{self.id}: {self.text}"

    def is_open(self) -> bool:
        return self.status == TicketStatus.OPEN

    def is_wip(self) -> bool:
        return self.status == TicketStatus.WIP

    def is_closed(self) -> bool:
        return self.status == TicketStatus.CLOSED


class AuditEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=_now)
    kind: str  # 'open' | 'wip' | 'close' | 'move' | 'register' | 'unregister' | 'message'
    ticket_id: int | None = Field(default=None, foreign_key="ticket.id")
    actor_chat_id: int | None = None
    payload_json: str | None = None

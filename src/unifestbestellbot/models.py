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


def now_utc() -> datetime:
    """Naive UTC. SQLite does not round-trip timezone info, so we keep
    every datetime that's stored or compared with a stored value naive
    and in UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


def to_local(dt: datetime) -> datetime:
    """Convert a stored naive-UTC datetime to an aware datetime in the
    configured display timezone (settings.timezone, default Europe/Berlin).

    For human-facing output only — never feed the result back into a query
    or comparison against a stored value, which must stay naive UTC. Reading
    the timezone from settings keeps display deterministic regardless of the
    VM's ambient timezone."""
    from .settings import get_settings

    return dt.replace(tzinfo=UTC).astimezone(get_settings().local_tz())


def _now() -> datetime:
    return now_utc()


# Peer-activity notification kinds a user can individually opt out of (via
# /notify). The value is the stable callback/id; the map points at the
# Registration column holding that opt-out flag.
PEER_OPENED = "opened"
PEER_WIP = "wip"
PEER_CLOSED = "closed"
PEER_NOTIFY_KINDS = (PEER_OPENED, PEER_WIP, PEER_CLOSED)
PEER_NOTIFY_COLUMN = {
    PEER_OPENED: "mute_opened",
    PEER_WIP: "mute_wip",
    PEER_CLOSED: "mute_closed",
}


class Registration(SQLModel, table=True):
    chat_id: int = Field(primary_key=True)
    group_name: str = Field(index=True)
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    registered_at: datetime = Field(default_factory=_now)
    # If set and in the future, suppress peer-activity DMs (group_msg with
    # an `exclude_chat_id`). Actionable DMs about the user's own tickets
    # (CLOSED on their ticket, /message forwards, ...) are NOT suppressed.
    mute_peer_until: datetime | None = None
    # Self-chosen display name (via /name). When set, it replaces the
    # Telegram-derived name everywhere this person is shown for their actions.
    display_override: str | None = None
    # Per-kind opt-outs for peer-activity DMs (via /notify). True = suppressed.
    # Independent of mute_peer_until, which is a temporary blanket /quiet.
    mute_opened: bool = Field(default=False)
    mute_wip: bool = Field(default=False)
    mute_closed: bool = Field(default=False)

    def is_peer_kind_muted(self, kind: str) -> bool:
        return bool(getattr(self, PEER_NOTIFY_COLUMN[kind]))

    def display_name(self) -> str:
        if self.display_override:
            return self.display_override
        parts = [p for p in (self.first_name, self.last_name) if p]
        name = " ".join(parts) or "Unbekannt"
        return f"{name} <@{self.username}>" if self.username else name


class Ticket(SQLModel, table=True):
    # Status, closed_at and who_wip are coupled (closed ⇒ closed_at set;
    # wip ⇒ who_wip set; open ⇒ neither). That invariant is NOT enforced
    # on the type — SQLModel table models skip validation — but in the
    # single repo transition functions (set_wip/close_ticket), which are
    # the only writers. Keep all status mutations going through repo.py.
    id: int | None = Field(default=None, primary_key=True)
    status: TicketStatus = Field(default=TicketStatus.OPEN, index=True)
    category: str
    text: str
    group_requesting: str
    group_tasked: str = Field(index=True)
    who_wip: str | None = None
    # Stable Telegram chat_id of the orga who claimed the ticket (set together
    # with who_wip in set_wip). who_wip is a display string for humans; this is
    # the robust key for "my tickets" filtering, immune to name changes.
    who_wip_chat_id: int | None = Field(default=None, index=True)
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

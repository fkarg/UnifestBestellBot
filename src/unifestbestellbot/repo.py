"""Data-access functions. Each takes a Session and handles its own commit.
Audit events are written in the same transaction as the action they describe."""

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy import update as sa_update
from sqlmodel import Session, select

from .models import (
    PEER_NOTIFY_COLUMN,
    AuditEvent,
    Registration,
    Ticket,
    TicketStatus,
    now_utc,
)

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def upsert_registration(s: Session, reg: Registration) -> Registration:
    existing = s.get(Registration, reg.chat_id)
    if existing is not None:
        previous = existing.group_name
        existing.group_name = reg.group_name
        existing.username = reg.username
        existing.first_name = reg.first_name
        existing.last_name = reg.last_name
        s.add(existing)
        record = existing
        payload = {"group_name": reg.group_name, "previous": previous}
    else:
        s.add(reg)
        record = reg
        payload = {"group_name": reg.group_name}
    s.add(
        AuditEvent(
            kind="register",
            actor_chat_id=reg.chat_id,
            payload_json=json.dumps(payload),
        )
    )
    s.commit()
    s.refresh(record)
    return record


def unregister(s: Session, chat_id: int) -> str | None:
    """Returns the group_name the user was in, or None if nothing was deleted."""
    reg = s.get(Registration, chat_id)
    if reg is None:
        return None
    group = reg.group_name
    s.delete(reg)
    s.add(
        AuditEvent(
            kind="unregister",
            actor_chat_id=chat_id,
            payload_json=json.dumps({"group_name": group}),
        )
    )
    s.commit()
    return group


def registration_for(s: Session, chat_id: int) -> Registration | None:
    return s.get(Registration, chat_id)


def group_members(
    s: Session,
    group_name: str,
    *,
    exclude_muted: bool = False,
    exclude_kind: str | None = None,
) -> list[int]:
    stmt = select(Registration.chat_id).where(Registration.group_name == group_name)
    if exclude_muted:
        now = now_utc()
        # ty/mypy can't see SQLAlchemy's column descriptor; the runtime
        # column expression supports both `.is_(None)` and `<= now`.
        mute_col = Registration.mute_peer_until
        stmt = stmt.where(
            or_(mute_col.is_(None), mute_col <= now)  # ty: ignore[unresolved-attribute, unsupported-operator]
        )
    if exclude_kind is not None:
        # Drop members who opted out of this peer-notification kind via /notify.
        kind_col = getattr(Registration, PEER_NOTIFY_COLUMN[exclude_kind])
        stmt = stmt.where(~kind_col)
    return list(s.exec(stmt))


def set_mute(s: Session, chat_id: int, *, until: datetime | None) -> bool:
    """Set or clear the peer-activity mute on a registration. Returns
    True if the row existed and was updated."""
    reg = s.get(Registration, chat_id)
    if reg is None:
        return False
    reg.mute_peer_until = until
    s.add(reg)
    s.commit()
    return True


def set_display_override(s: Session, chat_id: int, value: str | None) -> bool:
    """Set or clear a registration's self-chosen display name. Returns True
    if the row existed and was updated."""
    reg = s.get(Registration, chat_id)
    if reg is None:
        return False
    reg.display_override = value
    s.add(reg)
    s.commit()
    return True


def toggle_notify_mute(s: Session, chat_id: int, kind: str) -> bool | None:
    """Flip the per-kind peer-notification opt-out. Returns the new muted
    state (True = suppressed), or None if the registration doesn't exist."""
    reg = s.get(Registration, chat_id)
    if reg is None:
        return None
    col = PEER_NOTIFY_COLUMN[kind]
    new_state = not bool(getattr(reg, col))
    setattr(reg, col, new_state)
    s.add(reg)
    s.commit()
    return new_state


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------


def create_ticket(
    s: Session,
    *,
    category: str,
    text: str,
    group_requesting: str,
    group_tasked: str,
    actor_chat_id: int,
) -> Ticket:
    t = Ticket(
        category=category,
        text=text,
        group_requesting=group_requesting,
        group_tasked=group_tasked,
    )
    s.add(t)
    s.flush()  # populate t.id
    s.add(AuditEvent(kind="open", ticket_id=t.id, actor_chat_id=actor_chat_id))
    s.commit()
    s.refresh(t)
    return t


def set_wip(s: Session, ticket_id: int, *, who: str, actor_chat_id: int) -> Ticket:
    """Atomically claim an OPEN ticket as WIP for `who`.

    The OPEN→WIP transition is a single conditional UPDATE rather than a
    read-check-write, so two near-simultaneous /wip on the same ticket can
    never both succeed: SQLite's write lock serialises them and only the
    statement that still matches `status == OPEN` flips the row. The loser
    sees rowcount 0 and gets the same ValueError as a stale claim. This is
    what makes WIP usable for task distribution (exactly one owner)."""
    t = s.get(Ticket, ticket_id)
    if t is None:
        raise LookupError(f"ticket {ticket_id} does not exist")
    stmt = (
        sa_update(Ticket)
        .where(Ticket.id == ticket_id)  # ty: ignore[invalid-argument-type]
        .where(Ticket.status == TicketStatus.OPEN)  # ty: ignore[invalid-argument-type]
        .values(status=TicketStatus.WIP, who_wip=who, who_wip_chat_id=actor_chat_id)
        .execution_options(synchronize_session=False)
    )
    # The conditional UPDATE runs on the session's connection (same
    # transaction). Going through the Connection rather than Session.execute
    # gives a CursorResult with rowcount and avoids SQLModel's select-oriented
    # exec() typing. rowcount 0 means we lost the race (someone already moved
    # it off OPEN); `t` is still OPEN here, that's fine for the message.
    if s.connection().execute(stmt).rowcount == 0:
        raise ValueError(f"ticket {ticket_id} is not open")
    s.add(
        AuditEvent(
            kind="wip",
            ticket_id=ticket_id,
            actor_chat_id=actor_chat_id,
            payload_json=json.dumps({"who": who}),
        )
    )
    s.commit()
    s.refresh(t)  # the UPDATE bypassed the ORM; reload t to reflect WIP/who
    return t


def close_ticket(s: Session, ticket_id: int, *, actor_chat_id: int) -> Ticket:
    t = s.get(Ticket, ticket_id)
    if t is None:
        raise LookupError(f"ticket {ticket_id} does not exist")
    if t.status == TicketStatus.CLOSED:
        raise ValueError(f"ticket {ticket_id} is already closed")
    t.status = TicketStatus.CLOSED
    t.closed_at = now_utc()
    s.add(t)
    s.add(AuditEvent(kind="close", ticket_id=t.id, actor_chat_id=actor_chat_id))
    s.commit()
    s.refresh(t)
    return t


def move_ticket(
    s: Session, ticket_id: int, *, new_group: str, actor_chat_id: int
) -> Ticket:
    t = s.get(Ticket, ticket_id)
    if t is None:
        raise LookupError(f"ticket {ticket_id} does not exist")
    if t.status != TicketStatus.OPEN:
        raise ValueError(f"ticket {ticket_id} is not open (status={t.status})")
    previous = t.group_tasked
    t.group_tasked = new_group
    s.add(t)
    s.add(
        AuditEvent(
            kind="move",
            ticket_id=t.id,
            actor_chat_id=actor_chat_id,
            payload_json=json.dumps({"from": previous, "to": new_group}),
        )
    )
    s.commit()
    s.refresh(t)
    return t


def get_ticket(s: Session, ticket_id: int) -> Ticket | None:
    return s.get(Ticket, ticket_id)


def active_tickets(
    s: Session,
    *,
    group_tasked: str | None = None,
    status: TicketStatus | None = None,
    who_wip_chat_id: int | None = None,
) -> list[Ticket]:
    stmt = select(Ticket).where(Ticket.status != TicketStatus.CLOSED)
    if group_tasked is not None:
        stmt = stmt.where(Ticket.group_tasked == group_tasked)
    if status is not None:
        stmt = stmt.where(Ticket.status == status)
    if who_wip_chat_id is not None:
        stmt = stmt.where(Ticket.who_wip_chat_id == who_wip_chat_id)
    # Ticket.id is an InstrumentedAttribute at the class level, but its
    # declared type is `int | None`; ty/mypy can't see the descriptor magic.
    stmt = stmt.order_by(Ticket.id)  # ty: ignore[invalid-argument-type]
    return list(s.exec(stmt))


def closed_tickets_for_chat_id(s: Session, chat_id: int) -> list[Ticket]:
    """All CLOSED tickets the given orga worked on (claimed via /wip).
    who_wip_chat_id survives the close transition, so this is the durable
    record of a person's handled tickets — used by /self for stats."""
    stmt = (
        select(Ticket)
        .where(Ticket.status == TicketStatus.CLOSED)
        .where(Ticket.who_wip_chat_id == chat_id)
        .order_by(Ticket.id)  # ty: ignore[invalid-argument-type]
    )
    return list(s.exec(stmt))


def tickets_requested_by(s: Session, group: str) -> list[Ticket]:
    stmt = (
        select(Ticket)
        .where(Ticket.group_requesting == group)
        .where(Ticket.status != TicketStatus.CLOSED)
        .order_by(Ticket.id)  # ty: ignore[invalid-argument-type]
    )
    return list(s.exec(stmt))


@dataclass
class CloseSummary:
    """One closed ticket, with metadata for display in /history."""

    ticket: Ticket
    closed_at: datetime
    closer_chat_id: int | None
    closer_display: str


def recent_closes(
    s: Session, *, group_tasked: str | None = None, limit: int = 10
) -> list[CloseSummary]:
    """Return up to `limit` most recently closed tickets, newest first.
    Each entry carries the closer's display name (from their registration
    if they still have one; otherwise their raw chat id)."""
    # SQLAlchemy comparison expressions look like `bool` to ty/mypy but
    # are ColumnElements at runtime; the join condition needs one ignore.
    stmt = (
        select(Ticket, AuditEvent)
        .join(AuditEvent, AuditEvent.ticket_id == Ticket.id)  # ty: ignore[invalid-argument-type]
        .where(Ticket.status == TicketStatus.CLOSED)
        .where(AuditEvent.kind == "close")
    )
    if group_tasked is not None:
        stmt = stmt.where(Ticket.group_tasked == group_tasked)
    stmt = stmt.order_by(AuditEvent.ts.desc()).limit(limit)  # ty: ignore[unresolved-attribute]

    summaries: list[CloseSummary] = []
    for ticket, event in s.exec(stmt):
        reg = (
            s.get(Registration, event.actor_chat_id)
            if event.actor_chat_id is not None
            else None
        )
        if reg is not None:
            display = reg.display_name()
        elif event.actor_chat_id is not None:
            display = f"chat {event.actor_chat_id}"
        else:
            display = "Unbekannt"
        summaries.append(
            CloseSummary(
                ticket=ticket,
                closed_at=event.ts,
                closer_chat_id=event.actor_chat_id,
                closer_display=display,
            )
        )
    return summaries


def record_message(
    s: Session, *, ticket_id: int, actor_chat_id: int, message: str
) -> None:
    s.add(
        AuditEvent(
            kind="message",
            ticket_id=ticket_id,
            actor_chat_id=actor_chat_id,
            payload_json=json.dumps({"message": message}),
        )
    )
    s.commit()

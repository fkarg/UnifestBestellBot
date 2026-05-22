"""Data-access functions. Each takes a Session and handles its own commit.
Audit events are written in the same transaction as the action they describe."""

import json
from datetime import datetime

from sqlalchemy import or_
from sqlmodel import Session, select

from .models import AuditEvent, Registration, Ticket, TicketStatus, now_utc

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
    s: Session, group_name: str, *, exclude_muted: bool = False
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
    t = s.get(Ticket, ticket_id)
    if t is None:
        raise LookupError(f"ticket {ticket_id} does not exist")
    if t.status != TicketStatus.OPEN:
        raise ValueError(f"ticket {ticket_id} is not open (status={t.status})")
    t.status = TicketStatus.WIP
    t.who_wip = who
    s.add(t)
    s.add(
        AuditEvent(
            kind="wip",
            ticket_id=t.id,
            actor_chat_id=actor_chat_id,
            payload_json=json.dumps({"who": who}),
        )
    )
    s.commit()
    s.refresh(t)
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
    s: Session, *, group_tasked: str | None = None, status: TicketStatus | None = None
) -> list[Ticket]:
    stmt = select(Ticket).where(Ticket.status != TicketStatus.CLOSED)
    if group_tasked is not None:
        stmt = stmt.where(Ticket.group_tasked == group_tasked)
    if status is not None:
        stmt = stmt.where(Ticket.status == status)
    # Ticket.id is an InstrumentedAttribute at the class level, but its
    # declared type is `int | None`; ty/mypy can't see the descriptor magic.
    stmt = stmt.order_by(Ticket.id)  # ty: ignore[invalid-argument-type]
    return list(s.exec(stmt))


def tickets_requested_by(s: Session, group: str) -> list[Ticket]:
    stmt = (
        select(Ticket)
        .where(Ticket.group_requesting == group)
        .where(Ticket.status != TicketStatus.CLOSED)
        .order_by(Ticket.id)  # ty: ignore[invalid-argument-type]
    )
    return list(s.exec(stmt))


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

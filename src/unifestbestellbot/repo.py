"""Data-access functions. Each takes a Session and handles its own commit.
Audit events are written in the same transaction as the action they describe."""

import json
from dataclasses import dataclass
from datetime import date, datetime

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
    to_local,
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


def all_registrations(s: Session) -> list[Registration]:
    """Every registration, ordered by group then chat_id. For the developer
    /system snapshot; not used in any hot path."""
    stmt = select(Registration).order_by(
        Registration.group_name,
        Registration.chat_id,  # ty: ignore[invalid-argument-type]
    )
    return list(s.exec(stmt))


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


def ticket_count(s: Session) -> int:
    """Total tickets in the DB across all statuses. For the startup summary."""
    return len(list(s.exec(select(Ticket))))


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


def recent_tickets(s: Session, *, limit: int = 10) -> list[Ticket]:
    """The most recently created tickets across all statuses, newest first.
    For the developer /system snapshot."""
    stmt = (
        select(Ticket)
        .order_by(Ticket.id.desc())  # ty: ignore[unresolved-attribute]
        .limit(limit)
    )
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


def recent_tickets_for_group(s: Session, group: str, *, limit: int = 5) -> list[Ticket]:
    """The `limit` most recent tickets a group requested, newest first,
    across all statuses. Backs the /history <group> inspection view."""
    stmt = (
        select(Ticket)
        .where(Ticket.group_requesting == group)
        .order_by(Ticket.id.desc())  # ty: ignore[unresolved-attribute]
        .limit(limit)
    )
    return list(s.exec(stmt))


def recent_closed_for_group(s: Session, group: str, *, limit: int = 5) -> list[Ticket]:
    """The `limit` most recently closed tickets a group requested, newest
    first. Backs the recently-resolved section of /status."""
    stmt = (
        select(Ticket)
        .where(Ticket.group_requesting == group)
        .where(Ticket.status == TicketStatus.CLOSED)
        .order_by(Ticket.id.desc())  # ty: ignore[unresolved-attribute]
        .limit(limit)
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


def record_direct_message(
    s: Session, *, chat_id: int, actor_chat_id: int, message: str
) -> None:
    """Audit a developer message sent directly to a Telegram chat."""
    s.add(
        AuditEvent(
            kind="direct_message",
            actor_chat_id=actor_chat_id,
            payload_json=json.dumps({"chat_id": chat_id, "message": message}),
        )
    )
    s.commit()


# ---------------------------------------------------------------------------
# Stats (read-only, for /stats)
# ---------------------------------------------------------------------------


@dataclass
class Percentiles:
    """Processing-time percentile summary in seconds."""

    p50_s: float
    p75_s: float
    p90_s: float
    p95_s: float
    max_s: float


@dataclass
class Stats:
    """Whole-database aggregate over every ticket seen this event. Counts are
    over all tickets regardless of status; timings are over the tickets that
    reached the relevant transition. Location is intentionally absent — it's
    config-derived, so the handler folds `by_group` into locations."""

    total: int
    open: int
    wip: int
    closed: int
    by_category: dict[str, int]
    by_group: dict[str, int]  # group_requesting -> count
    by_day: dict[date, int]  # local-time creation date -> count
    by_hour: dict[int, int]  # local-time creation hour -> count
    wait_median_s: float | None  # created -> closed, over closed tickets
    wait_max_s: float | None
    pickup_median_s: float | None  # created -> first WIP, over claimed tickets
    pickup_max_s: float | None
    wait_percentiles_by_group: dict[str, Percentiles]  # group_tasked -> created -> closed


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _percentile(values: list[float], fraction: float) -> float:
    """Linearly interpolate an inclusive percentile over non-empty values."""
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _percentiles(values: list[float]) -> Percentiles:
    return Percentiles(
        p50_s=_percentile(values, 0.50),
        p75_s=_percentile(values, 0.75),
        p90_s=_percentile(values, 0.90),
        p95_s=_percentile(values, 0.95),
        max_s=max(values),
    )


def stats_summary(s: Session) -> Stats:
    tickets = list(s.exec(select(Ticket)))
    status = {TicketStatus.OPEN: 0, TicketStatus.WIP: 0, TicketStatus.CLOSED: 0}
    by_category: dict[str, int] = {}
    by_group: dict[str, int] = {}
    by_day: dict[date, int] = {}
    by_hour: dict[int, int] = {}
    waits: list[float] = []
    waits_by_group: dict[str, list[float]] = {}
    created_by_id: dict[int, datetime] = {}
    for t in tickets:
        status[t.status] += 1
        by_category[t.category] = by_category.get(t.category, 0) + 1
        by_group[t.group_requesting] = by_group.get(t.group_requesting, 0) + 1
        local_created = to_local(t.created_at)
        by_day[local_created.date()] = by_day.get(local_created.date(), 0) + 1
        hour = local_created.hour
        by_hour[hour] = by_hour.get(hour, 0) + 1
        if t.id is not None:
            created_by_id[t.id] = t.created_at
        if t.closed_at is not None:
            wait = (t.closed_at - t.created_at).total_seconds()
            waits.append(wait)
            waits_by_group.setdefault(t.group_tasked, []).append(wait)

    # Pickup lag: created -> first 'wip' audit event per ticket. Ordered by ts
    # ascending so the first row seen for a ticket is its earliest claim.
    first_wip: dict[int, datetime] = {}
    wip_events = s.exec(
        select(AuditEvent)
        .where(AuditEvent.kind == "wip")
        .order_by(AuditEvent.ts)  # ty: ignore[invalid-argument-type]
    )
    for e in wip_events:
        if e.ticket_id is not None and e.ticket_id not in first_wip:
            first_wip[e.ticket_id] = e.ts
    pickups = [
        (ts - created_by_id[tid]).total_seconds()
        for tid, ts in first_wip.items()
        if tid in created_by_id
    ]

    return Stats(
        total=len(tickets),
        open=status[TicketStatus.OPEN],
        wip=status[TicketStatus.WIP],
        closed=status[TicketStatus.CLOSED],
        by_category=by_category,
        by_group=by_group,
        by_day=by_day,
        by_hour=by_hour,
        wait_median_s=_median(waits),
        wait_max_s=max(waits) if waits else None,
        pickup_median_s=_median(pickups),
        pickup_max_s=max(pickups) if pickups else None,
        wait_percentiles_by_group={
            group: _percentiles(group_waits) for group, group_waits in waits_by_group.items()
        },
    )

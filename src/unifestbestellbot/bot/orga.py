"""Orga commands plus shared support commands such as /helpers."""

from datetime import datetime
from urllib.parse import urlencode

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlmodel import Session

from .. import i18n, repo
from ..config import AppConfig
from ..engelsystem import ShiftLookup
from ..events import EventBus
from ..models import (
    PEER_CLOSED,
    PEER_WIP,
    Registration,
    Ticket,
    TicketStatus,
    now_utc,
    to_local,
)
from . import keyboards, notify
from .common import actor, bot_of, display_for
from .filters import IsOrga

router = Router(name="orga")

_DASHBOARD_URL = "https://bestellbot.unifest-karlsruhe.de/"


# --- Helpers -------------------------------------------------------------


def _picker(
    tickets: list[Ticket], action: str, header: str, *, show_all: bool = False
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t.display(), callback_data=f"{action}:{t.id}")]
        for t in tickets
    ]
    if show_all:
        rows.append(
            [InlineKeyboardButton(text=i18n.PICKER_SHOW_ALL, callback_data=f"{action}:_all")]
        )
    rows.append(
        [InlineKeyboardButton(text=i18n.PICKER_CANCEL, callback_data=f"{action}:_cancel")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# SQLite stores the ticket-id primary key as a signed 64-bit INTEGER. A larger
# value can't even be bound to a query — sqlite3 raises OverflowError before any
# lookup — so anything out of the valid id range (positive, ≤ 2**63-1) is parsed
# as "no valid id" and handled like a missing/garbage argument, not thrown.
_SQLITE_MAX_INT = 2**63 - 1


def _parse_ticket_id(token: str) -> int | None:
    try:
        tid = int(token)
    except ValueError:
        return None
    return tid if 0 < tid <= _SQLITE_MAX_INT else None


def _arg_id(msg: Message) -> int | None:
    parts = (msg.text or "").split()
    if len(parts) < 2:
        return None
    return _parse_ticket_id(parts[1])


# --- /tickets, /all ------------------------------------------------------


def _require_reg(s: Session, event: Message | CallbackQuery) -> Registration:
    """IsOrga filter guarantees the user is registered. Helper that asserts
    that invariant so callers can read .group_name without an Optional check."""
    reg = repo.registration_for(s, actor(event).id)
    assert reg is not None, "IsOrga filter guarantees a registration"
    return reg


def _reply_target(event: Message | CallbackQuery) -> Message | None:
    if isinstance(event, CallbackQuery):
        return event.message if isinstance(event.message, Message) else None
    return event


@router.message(Command("tickets"), IsOrga())
async def cmd_tickets(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = _require_reg(db_session, msg)
    open_for_group = repo.active_tickets(db_session, group_tasked=reg.group_name)
    if not open_for_group:
        await msg.answer(
            i18n.NO_OPEN_TICKETS_FOR_USER_GROUP.format(group=reg.group_name),
            reply_markup=keyboards.for_user(reg, config),
        )
        return
    body = "\n\n".join(t.display() for t in open_for_group)
    await msg.answer(
        i18n.TICKETS_FOR_GROUP_HEADER.format(group=reg.group_name, tickets=body),
        reply_markup=keyboards.for_user(reg, config),
    )


@router.message(Command("all"), IsOrga())
async def cmd_all(msg: Message, db_session: Session, config: AppConfig) -> None:
    all_open = repo.active_tickets(db_session)
    if not all_open:
        await msg.answer(i18n.NO_OPEN_TICKETS_ANYWHERE)
        return
    parts: list[str] = []
    for orga in config.orga_names():
        for_orga = [t for t in all_open if t.group_tasked == orga]
        if for_orga:
            parts.append(
                f"\n🔷 Offene Tickets für [{orga}]:\n\n"
                + "\n\n".join(t.display() for t in for_orga)
            )
    reg = _require_reg(db_session, msg)
    await msg.answer("\n".join(parts) or i18n.NO_OPEN_TICKETS_ANYWHERE,
                     reply_markup=keyboards.for_user(reg, config))


@router.message(Command("help2"), IsOrga())
async def cmd_help2(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = _require_reg(db_session, msg)
    await msg.answer(i18n.HELP_ORGA, reply_markup=keyboards.for_user(reg, config))


@router.message(Command("dashboard"), IsOrga())
async def cmd_dashboard(msg: Message, db_session: Session) -> None:
    reg = _require_reg(db_session, msg)
    group_url = f"{_DASHBOARD_URL}?{urlencode({'group': reg.group_name})}"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Alle aktiven Tickets", url=_DASHBOARD_URL)],
            [InlineKeyboardButton(text=f"Nur {reg.group_name}", url=group_url)],
        ]
    )
    await msg.answer(
        "Dashboard für alle aktiven Tickets:\n"
        f"{_DASHBOARD_URL}\n\n"
        f"Nur Tickets, die aktuell {reg.group_name} zugewiesen sind:\n"
        f"{group_url}\n\n"
        f"{i18n.DASHBOARD_ACCESS}",
        reply_markup=keyboard,
    )


# --- /wip -----------------------------------------------------------------


@router.message(Command("wip"), IsOrga())
async def cmd_wip(
    msg: Message, db_session: Session, config: AppConfig, events: EventBus
) -> None:
    if (tid := _arg_id(msg)) is not None:
        await _do_wip(msg, db_session, config, events, tid)
        return
    reg = _require_reg(db_session, msg)
    candidates = repo.active_tickets(
        db_session, group_tasked=reg.group_name, status=TicketStatus.OPEN
    )
    if not candidates:
        await msg.answer(
            i18n.NO_OPEN_TICKETS_FOR_GROUP.format(group=reg.group_name),
            reply_markup=keyboards.for_user(reg, config),
        )
        return
    await msg.answer(i18n.OPEN_TICKETS_LIST, reply_markup=_picker(candidates, "wip", i18n.OPEN_TICKETS_LIST))


@router.callback_query(F.data.startswith("wip:"), IsOrga())
async def on_wip_choice(
    cb: CallbackQuery, db_session: Session, config: AppConfig, events: EventBus
) -> None:
    assert cb.data is not None
    suffix = cb.data.removeprefix("wip:")
    if suffix == "_cancel":
        if isinstance(cb.message, Message):
            await cb.message.edit_text(i18n.PICKER_CANCELLED)
        await cb.answer()
        return
    try:
        tid = int(suffix)
    except ValueError:
        await cb.answer()
        return
    await _do_wip(cb, db_session, config, events, tid)
    await cb.answer()


async def _do_wip(
    event: Message | CallbackQuery,
    s: Session,
    config: AppConfig,
    events: EventBus,
    tid: int,
) -> None:
    ticket = repo.get_ticket(s, tid)
    reply_to = _reply_target(event)
    if ticket is None or ticket.is_closed():
        if reply_to is not None:
            await reply_to.answer(i18n.TICKET_NOT_FOUND_OR_CLOSED.format(uid=tid))
        return
    if ticket.is_wip():
        if reply_to is not None:
            await reply_to.answer(i18n.TICKET_ALREADY_WIP)
        return
    user = actor(event)
    bot = bot_of(event)
    reg = _require_reg(s, event)
    name = display_for(reg, user)
    try:
        updated = repo.set_wip(s, tid, who=name, actor_chat_id=user.id)
    except ValueError:
        # Lost the race: another orga claimed this ticket between our read
        # above and the atomic UPDATE. Tell the user it's already taken
        # rather than letting it surface as an unhandled exception.
        if reply_to is not None:
            await reply_to.answer(i18n.TICKET_ALREADY_WIP)
        return

    if isinstance(event, CallbackQuery) and isinstance(event.message, Message):
        await event.message.edit_text(updated.display())
    elif reply_to is not None:
        await reply_to.answer(
            i18n.TICKET_WIP_NOTICE.format(uid=tid),
            reply_markup=keyboards.for_user(reg, config),
        )

    await events.publish_ticket(updated)
    await notify.channel_msg(
        bot, i18n.CH_WIP.format(who=name, group=reg.group_name, uid=tid)
    )
    await notify.group_msg(
        bot, s, reg.group_name,
        i18n.GROUP_TICKET_WIP_PEER.format(who=name, uid=tid),
        exclude_chat_id=user.id,
        exclude_muted=True,
        kind=PEER_WIP,
    )
    await notify.group_msg(
        bot, s, ticket.group_requesting,
        i18n.GROUP_TICKET_WIP_OWNER.format(uid=tid),
    )


# --- /close ---------------------------------------------------------------


@router.message(Command("close"), IsOrga())
async def cmd_close(
    msg: Message, db_session: Session, config: AppConfig, events: EventBus
) -> None:
    if (tid := _arg_id(msg)) is not None:
        await _do_close(msg, db_session, config, events, tid)
        return
    reg = _require_reg(db_session, msg)
    # Default the picker to the caller's own WIP tickets: during the event the
    # group-wide WIP list overflows, and you almost always want to close one of
    # yours. The "Alle der Gruppe anzeigen" button expands to the full list.
    own = repo.active_tickets(
        db_session,
        status=TicketStatus.WIP,
        who_wip_chat_id=actor(msg).id,
    )
    if own:
        await msg.answer(
            i18n.MY_WIP_TICKETS_LIST,
            reply_markup=_picker(own, "close", i18n.MY_WIP_TICKETS_LIST, show_all=True),
        )
        return
    # No own WIP: fall back directly to the group list so the command is never
    # a dead end.
    group_wip = repo.active_tickets(
        db_session, group_tasked=reg.group_name, status=TicketStatus.WIP
    )
    if not group_wip:
        await msg.answer(
            i18n.NO_WIP_TICKETS_FOR_GROUP.format(group=reg.group_name),
            reply_markup=keyboards.for_user(reg, config),
        )
        return
    await msg.answer(
        i18n.NO_OWN_WIP_SHOWING_GROUP.format(group=reg.group_name),
        reply_markup=_picker(group_wip, "close", i18n.WIP_TICKETS_LIST),
    )


@router.callback_query(F.data.startswith("close:"), IsOrga())
async def on_close_choice(
    cb: CallbackQuery, db_session: Session, config: AppConfig, events: EventBus
) -> None:
    assert cb.data is not None
    suffix = cb.data.removeprefix("close:")
    if suffix == "_cancel":
        if isinstance(cb.message, Message):
            await cb.message.edit_text(i18n.PICKER_CANCELLED)
        await cb.answer()
        return
    if suffix == "_all":
        # Toggle from the own-tickets view to the full group WIP list.
        reg = _require_reg(db_session, cb)
        group_wip = repo.active_tickets(
            db_session, group_tasked=reg.group_name, status=TicketStatus.WIP
        )
        if isinstance(cb.message, Message):
            if group_wip:
                await cb.message.edit_text(
                    i18n.WIP_TICKETS_LIST,
                    reply_markup=_picker(group_wip, "close", i18n.WIP_TICKETS_LIST),
                )
            else:
                await cb.message.edit_text(
                    i18n.NO_WIP_TICKETS_FOR_GROUP.format(group=reg.group_name)
                )
        await cb.answer()
        return
    try:
        tid = int(suffix)
    except ValueError:
        await cb.answer()
        return
    await _do_close(cb, db_session, config, events, tid)
    await cb.answer()


async def _do_close(
    event: Message | CallbackQuery,
    s: Session,
    config: AppConfig,
    events: EventBus,
    tid: int,
) -> None:
    ticket = repo.get_ticket(s, tid)
    reply_to = _reply_target(event)
    if ticket is None or ticket.is_closed():
        if reply_to is not None:
            await reply_to.answer(i18n.TICKET_NOT_FOUND_OR_CLOSED.format(uid=tid))
        return
    user = actor(event)
    bot = bot_of(event)
    updated = repo.close_ticket(s, tid, actor_chat_id=user.id)
    reg = _require_reg(s, event)
    name = display_for(reg, user)

    if isinstance(event, CallbackQuery) and isinstance(event.message, Message):
        await event.message.edit_text(updated.display())
    elif reply_to is not None:
        await reply_to.answer(
            i18n.TICKET_CLOSED_NOTICE.format(uid=tid),
            reply_markup=keyboards.for_user(reg, config),
        )

    await events.publish_ticket(updated)
    await notify.channel_msg(
        bot, i18n.CH_CLOSED.format(who=name, group=reg.group_name, uid=tid)
    )
    await notify.group_msg(
        bot, s, reg.group_name,
        i18n.GROUP_TICKET_CLOSED_PEER.format(who=name, uid=tid),
        exclude_chat_id=user.id,
        exclude_muted=True,
        kind=PEER_CLOSED,
    )
    await notify.group_msg(
        bot, s, ticket.group_requesting,
        i18n.GROUP_TICKET_CLOSED_OWNER.format(uid=tid),
    )


# --- /self ----------------------------------------------------------------


def _fmt_duration(seconds: float) -> str:
    total_min = int(round(seconds / 60))
    if total_min < 60:
        return f"{total_min} min"
    h, m = divmod(total_min, 60)
    return f"{h} h {m} min"


def _self_overview(
    wip: list[Ticket], closed: list[Ticket], *, now: datetime
) -> str:
    """Render the caller's personal overview: their live WIP tickets plus
    how many they've handled. `now` is naive UTC; "today" is the local
    calendar day (matches /history's display timezone)."""
    lines = [i18n.SELF_HEADER, "", i18n.SELF_WIP_LINE.format(count=len(wip))]
    lines += [t.display() for t in wip] if wip else [i18n.SELF_NO_WIP]

    today = to_local(now).date()
    closed_today = sum(
        1 for t in closed if t.closed_at is not None and to_local(t.closed_at).date() == today
    )
    lines += ["", i18n.SELF_CLOSED_LINE.format(today=closed_today, total=len(closed))]

    durations = [
        (t.closed_at - t.created_at).total_seconds()
        for t in closed
        if t.closed_at is not None
    ]
    avg = (
        i18n.SELF_AVG_NONE
        if not durations
        else _fmt_duration(sum(durations) / len(durations))
    )
    lines.append(i18n.SELF_AVG_LINE.format(avg=avg))
    return "\n".join(lines)


@router.message(Command("self"), IsOrga())
async def cmd_self(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = _require_reg(db_session, msg)
    uid = actor(msg).id
    wip = repo.active_tickets(
        db_session, status=TicketStatus.WIP, who_wip_chat_id=uid
    )
    closed = repo.closed_tickets_for_chat_id(db_session, uid)
    await msg.answer(
        _self_overview(wip, closed, now=now_utc()),
        reply_markup=keyboards.for_user(reg, config),
    )


# --- /move ----------------------------------------------------------------


@router.message(Command("move"), IsOrga())
async def cmd_move(
    msg: Message, db_session: Session, config: AppConfig, events: EventBus
) -> None:
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.answer(i18n.MOVE_USAGE.format(groups=config.orga_names()))
        return
    tid = _parse_ticket_id(parts[1])
    if tid is None:
        await msg.answer(i18n.MOVE_USAGE.format(groups=config.orga_names()))
        return
    target = parts[2].strip()
    if not config.is_orga(target):
        await msg.answer(i18n.MOVE_USAGE.format(groups=config.orga_names()))
        return
    ticket = repo.get_ticket(db_session, tid)
    if ticket is None or ticket.is_closed():
        await msg.answer(i18n.TICKET_NOT_FOUND_OR_CLOSED.format(uid=tid))
        return
    if ticket.is_wip():
        await msg.answer(i18n.TICKET_MOVE_BLOCKED_WIP.format(uid=tid))
        return
    user = actor(msg)
    bot = bot_of(msg)
    updated = repo.move_ticket(db_session, tid, new_group=target, actor_chat_id=user.id)
    reg = _require_reg(db_session, msg)
    await msg.answer(
        i18n.TICKET_MOVED_NOTICE.format(uid=tid, group=target),
        reply_markup=keyboards.for_user(reg, config),
    )
    # Publish the moved ticket. The stream is unfiltered and the dashboard
    # filters by group client-side, so the new group's board adds it and the
    # old group's board removes it (its group_tasked no longer matches).
    await events.publish_ticket(updated)
    await notify.channel_msg(
        bot, i18n.CH_MOVED.format(uid=tid, group=target)
    )
    await notify.group_msg(
        bot, db_session, target,
        i18n.GROUP_TICKET_FOR_ORGA.format(uid=tid, text=ticket.text),
    )


# --- /message -------------------------------------------------------------


@router.message(Command("message"), IsOrga())
async def cmd_message(msg: Message, db_session: Session, config: AppConfig) -> None:
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await msg.answer(i18n.MESSAGE_USAGE)
        return
    tid = _parse_ticket_id(parts[1])
    if tid is None:
        await msg.answer(i18n.MESSAGE_USAGE)
        return
    body = parts[2]
    ticket = repo.get_ticket(db_session, tid)
    if ticket is None:
        await msg.answer(i18n.TICKET_NOT_FOUND_OR_CLOSED.format(uid=tid))
        return
    user = actor(msg)
    bot = bot_of(msg)
    reg = _require_reg(db_session, msg)
    # Record the audit trail first: a message that was sent but not recorded
    # (crash/DB error after the network send) is worse than the reverse, and
    # the audit row is the only durable proof the message went out.
    repo.record_message(
        db_session,
        ticket_id=tid,
        actor_chat_id=user.id,
        message=body,
    )
    await notify.group_msg(
        bot, db_session, ticket.group_requesting,
        i18n.GROUP_INCOMING_MESSAGE.format(sender=reg.group_name, message=body),
    )
    await notify.channel_msg(
        bot,
        i18n.CH_MESSAGE.format(
            sender=reg.group_name, recipient=ticket.group_requesting, message=body
        ),
    )
    await msg.answer(i18n.MESSAGE_DELIVERED, reply_markup=keyboards.for_user(reg, config))


# --- /helpers (shift lookup) ---------------------------------------------


@router.message(Command("helpers"))
async def cmd_helpers(
    msg: Message, db_session: Session, config: AppConfig, shift_lookup: ShiftLookup
) -> None:
    reg = repo.registration_for(db_session, actor(msg).id)
    if reg is None:
        await msg.answer(i18n.NOT_REGISTERED, reply_markup=keyboards.for_user(None, config))
        return
    parts = (msg.text or "").split(maxsplit=1)
    group = parts[1].strip() if len(parts) > 1 else reg.group_name
    summary = await shift_lookup(group, config)
    await msg.answer(summary, reply_markup=keyboards.for_user(reg, config))


# --- /bug, /feature (open to everyone) ------------------------------------


@router.message(Command("bug"))
async def cmd_bug(msg: Message, db_session: Session, config: AppConfig) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer(i18n.BUG_USAGE)
        return
    user = actor(msg)
    reg = repo.registration_for(db_session, user.id)
    await notify.dev_msg(
        bot_of(msg), i18n.DEV_BUG.format(who=display_for(reg, user), message=parts[1])
    )
    await msg.answer(i18n.BUG_FORWARDED, reply_markup=keyboards.for_user(reg, config))


@router.message(Command("feature"))
async def cmd_feature(msg: Message, db_session: Session, config: AppConfig) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer(i18n.FEATURE_USAGE)
        return
    user = actor(msg)
    reg = repo.registration_for(db_session, user.id)
    await notify.dev_msg(
        bot_of(msg), i18n.DEV_FEATURE.format(who=display_for(reg, user), message=parts[1])
    )
    await msg.answer(i18n.FEATURE_FORWARDED, reply_markup=keyboards.for_user(reg, config))


# --- /history -------------------------------------------------------------

_HISTORY_MAX = 50
_HISTORY_DEFAULT = 10
# A group inspection defaults to a shorter window than the caller's own
# close log; it's a quick "what has this stand been asking for" glance.
_HISTORY_GROUP_DEFAULT = 5


@router.message(Command("history"), IsOrga())
async def cmd_history(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = _require_reg(db_session, msg)
    arg = (msg.text or "").split(maxsplit=1)
    rest = arg[1].strip() if len(arg) > 1 else ""

    def _bad_limit(n: int | None) -> bool:
        return n is not None and (n < 1 or n > _HISTORY_MAX)

    async def _usage() -> None:
        await msg.answer(i18n.HISTORY_USAGE, reply_markup=keyboards.for_user(reg, config))

    # Resolve the argument. Group names can contain spaces and end in a digit
    # ("Cocktailbar 1"), so try the whole string as a group first, then peel a
    # trailing integer as the limit, then a bare integer (no group).
    group: str | None = None
    explicit: int | None = None
    if rest:
        group = config.resolve_group(rest)
        if group is None:
            head, _, tail = rest.rpartition(" ")
            # isdecimal(), not isdigit(): the latter is True for superscripts
            # like "²" that int() then rejects with ValueError.
            if head and tail.isdecimal() and (g := config.resolve_group(head)):
                group, explicit = g, int(tail)
            elif rest.isdecimal():
                explicit = int(rest)
            else:
                await _usage()
                return

    # A resolved group switches to inspecting that stand's own ticket history
    # (all statuses); otherwise it's the caller's tasked-group close log.
    if group is not None:
        if _bad_limit(explicit):
            await _usage()
            return
        tickets = repo.recent_tickets_for_group(
            db_session, group, limit=explicit or _HISTORY_GROUP_DEFAULT
        )
        if not tickets:
            await msg.answer(
                i18n.HISTORY_GROUP_EMPTY.format(group=group),
                reply_markup=keyboards.for_user(reg, config),
            )
            return
        lines = [
            f"{t.display()}\n  erstellt {to_local(t.created_at).strftime('%d.%m. %H:%M')}"
            for t in tickets
        ]
        body = i18n.HISTORY_GROUP_HEADER.format(group=group) + "\n\n" + "\n\n".join(lines)
        await msg.answer(body, reply_markup=keyboards.for_user(reg, config))
        return

    if _bad_limit(explicit):
        await _usage()
        return
    summaries = repo.recent_closes(
        db_session, group_tasked=reg.group_name, limit=explicit or _HISTORY_DEFAULT
    )
    if not summaries:
        await msg.answer(
            i18n.HISTORY_EMPTY.format(group=reg.group_name),
            reply_markup=keyboards.for_user(reg, config),
        )
        return

    lines = []
    for cs in summaries:
        # Stored timestamps are naive UTC; display in the configured local
        # timezone so "21:00" means what they expect regardless of VM tz.
        when = to_local(cs.closed_at).strftime("%d.%m. %H:%M")
        lines.append(
            f"#{cs.ticket.id} ({when}) – {cs.closer_display}\n  {cs.ticket.text}"
        )
    body = i18n.HISTORY_HEADER.format(group=reg.group_name) + "\n\n" + "\n\n".join(lines)
    await msg.answer(body, reply_markup=keyboards.for_user(reg, config))


def _fmt_dur(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    mins = int(seconds // 60)
    if mins < 60:
        return f"{mins} min"
    return f"{mins // 60} h {mins % 60} min"


def _counts_block(header: str, counts: dict[str, int]) -> str:
    # Largest first; ties keep insertion order, which is stable enough here.
    lines = [
        f"  {name}: {n}"
        for name, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    ]
    return header + "\n" + "\n".join(lines)


@router.message(Command("stats"), IsOrga())
async def cmd_stats(msg: Message, db_session: Session, config: AppConfig) -> None:
    reg = _require_reg(db_session, msg)
    kb = keyboards.for_user(reg, config)
    st = repo.stats_summary(db_session)
    if st.total == 0:
        await msg.answer(i18n.STATS_EMPTY, reply_markup=kb)
        return

    # Fold requesting-group counts into the location+type cut
    # ("Forum Süd [Cocktail]") — i.e. individual stands, config-derived.
    by_location_type: dict[str, int] = {}
    for group, n in st.by_group.items():
        stall = config.stall(group)
        loc_type = stall.display if stall else group
        by_location_type[loc_type] = by_location_type.get(loc_type, 0) + n

    sections = [
        i18n.STATS_HEADER,
        i18n.STATS_STATUS.format(
            open=st.open, wip=st.wip, closed=st.closed, total=st.total
        ),
    ]
    if st.wait_median_s is not None or st.pickup_median_s is not None:
        sections.append(
            i18n.STATS_WAIT.format(
                median=_fmt_dur(st.wait_median_s), max=_fmt_dur(st.wait_max_s)
            )
        )
        sections.append(
            i18n.STATS_PICKUP.format(
                median=_fmt_dur(st.pickup_median_s), max=_fmt_dur(st.pickup_max_s)
            )
        )
    else:
        sections.append(i18n.STATS_TIMINGS_NONE)

    sections.append(_counts_block(i18n.STATS_BY_CATEGORY, st.by_category))
    sections.append(_counts_block(i18n.STATS_BY_LOCATION_TYPE, by_location_type))
    # Hours read most naturally chronologically, not by volume.
    hour_counts = {f"{h:02d} Uhr": n for h, n in sorted(st.by_hour.items())}
    hour_lines = "\n".join(f"  {label}: {n}" for label, n in hour_counts.items())
    sections.append(i18n.STATS_BY_HOUR + "\n" + hour_lines)

    await msg.answer("\n\n".join(sections), reply_markup=kb)

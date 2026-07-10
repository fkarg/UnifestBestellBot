from datetime import datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from unifestbestellbot import repo
from unifestbestellbot.models import AuditEvent, Registration, Ticket, TicketStatus


@pytest.fixture
def s():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# --- Registration ---------------------------------------------------------


def test_upsert_registration_inserts_new(s):
    reg = repo.upsert_registration(
        s,
        Registration(
            chat_id=1, group_name="Cocktailbar", username="alice", first_name="Alice"
        ),
    )
    assert reg.chat_id == 1
    assert repo.registration_for(s, 1).group_name == "Cocktailbar"


def test_upsert_registration_updates_existing(s):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar"))
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Biertheke 1"))
    assert repo.registration_for(s, 1).group_name == "Biertheke 1"


def test_unregister_removes_and_returns_group(s):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar"))
    assert repo.unregister(s, 1) == "Cocktailbar"
    assert repo.registration_for(s, 1) is None


def test_unregister_returns_none_when_absent(s):
    assert repo.unregister(s, 99) is None


def test_group_members_lists_chat_ids(s):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="BiMi"))
    repo.upsert_registration(s, Registration(chat_id=2, group_name="BiMi"))
    repo.upsert_registration(s, Registration(chat_id=3, group_name="Finanz"))
    assert set(repo.group_members(s, "BiMi")) == {1, 2}
    assert repo.group_members(s, "Finanz") == [3]
    assert repo.group_members(s, "Helfen") == []


# --- Tickets --------------------------------------------------------------


def _make_ticket(s, **overrides):
    defaults = dict(
        category="Geld",
        text="x",
        group_requesting="Cocktailbar",
        group_tasked="Finanz",
        actor_chat_id=1,
    )
    defaults.update(overrides)
    return repo.create_ticket(s, **defaults)


def test_create_ticket_sets_open_status_and_id(s):
    t = _make_ticket(s)
    assert t.id is not None
    assert t.status == TicketStatus.OPEN
    assert t.closed_at is None


def test_set_wip_transitions_status_and_records_who(s):
    t = _make_ticket(s)
    repo.set_wip(s, t.id, who="Alice", actor_chat_id=99)
    updated = repo.get_ticket(s, t.id)
    assert updated.status == TicketStatus.WIP
    assert updated.who_wip == "Alice"


def test_set_wip_rejects_non_open(s):
    t = _make_ticket(s)
    repo.set_wip(s, t.id, who="Alice", actor_chat_id=99)
    with pytest.raises(ValueError):
        repo.set_wip(s, t.id, who="Bob", actor_chat_id=99)


def test_set_wip_rejects_missing(s):
    with pytest.raises(LookupError):
        repo.set_wip(s, 999, who="Alice", actor_chat_id=1)


def test_close_ticket_marks_closed_and_sets_timestamp(s):
    t = _make_ticket(s)
    repo.set_wip(s, t.id, who="Alice", actor_chat_id=99)
    closed = repo.close_ticket(s, t.id, actor_chat_id=99)
    assert closed.status == TicketStatus.CLOSED
    assert closed.closed_at is not None


def test_close_can_skip_wip(s):
    """The bot allows closing OPEN tickets directly (legacy behaviour)."""
    t = _make_ticket(s)
    closed = repo.close_ticket(s, t.id, actor_chat_id=1)
    assert closed.status == TicketStatus.CLOSED


def test_close_rejects_already_closed(s):
    t = _make_ticket(s)
    repo.close_ticket(s, t.id, actor_chat_id=1)
    with pytest.raises(ValueError):
        repo.close_ticket(s, t.id, actor_chat_id=1)


def test_close_rejects_missing(s):
    with pytest.raises(LookupError):
        repo.close_ticket(s, 999, actor_chat_id=1)


def test_move_ticket_changes_group_tasked(s):
    t = _make_ticket(s)
    moved = repo.move_ticket(s, t.id, new_group="BiMi", actor_chat_id=1)
    assert moved.group_tasked == "BiMi"


def test_move_rejects_non_open(s):
    t = _make_ticket(s)
    repo.set_wip(s, t.id, who="Alice", actor_chat_id=99)
    with pytest.raises(ValueError):
        repo.move_ticket(s, t.id, new_group="BiMi", actor_chat_id=1)


def test_active_tickets_excludes_closed(s):
    a = _make_ticket(s, text="a")
    b = _make_ticket(s, text="b")
    repo.close_ticket(s, b.id, actor_chat_id=1)
    open_ids = [t.id for t in repo.active_tickets(s)]
    assert a.id in open_ids and b.id not in open_ids


def test_active_tickets_filters_by_group_tasked(s):
    _make_ticket(s, group_tasked="Finanz")
    bimi = _make_ticket(s, group_tasked="BiMi")
    bimi_tickets = repo.active_tickets(s, group_tasked="BiMi")
    assert [t.id for t in bimi_tickets] == [bimi.id]


def test_active_tickets_filters_by_status(s):
    a = _make_ticket(s)
    b = _make_ticket(s)
    repo.set_wip(s, b.id, who="Alice", actor_chat_id=1)
    open_only = repo.active_tickets(s, status=TicketStatus.OPEN)
    wip_only = repo.active_tickets(s, status=TicketStatus.WIP)
    assert {t.id for t in open_only} == {a.id}
    assert {t.id for t in wip_only} == {b.id}


def test_tickets_requested_by_excludes_closed(s):
    a = _make_ticket(s, group_requesting="Cocktailbar")
    b = _make_ticket(s, group_requesting="Cocktailbar")
    repo.close_ticket(s, b.id, actor_chat_id=1)
    open_for_group = repo.tickets_requested_by(s, "Cocktailbar")
    assert [t.id for t in open_for_group] == [a.id]


# --- Audit ----------------------------------------------------------------


def _audit(s) -> list[AuditEvent]:
    return list(s.exec(select(AuditEvent).order_by(AuditEvent.id)))


def test_audit_logs_full_ticket_lifecycle(s):
    t = _make_ticket(s)
    repo.set_wip(s, t.id, who="Alice", actor_chat_id=99)
    repo.close_ticket(s, t.id, actor_chat_id=99)
    kinds = [e.kind for e in _audit(s)]
    assert kinds == ["open", "wip", "close"]


def test_audit_logs_register_and_unregister(s):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="X"))
    repo.unregister(s, 1)
    kinds = [e.kind for e in _audit(s)]
    assert kinds == ["register", "unregister"]


def test_audit_logs_move_with_payload(s):
    t = _make_ticket(s)
    repo.move_ticket(s, t.id, new_group="BiMi", actor_chat_id=1)
    move_event = [e for e in _audit(s) if e.kind == "move"][0]
    assert "BiMi" in move_event.payload_json


def test_record_message_writes_audit(s):
    t = _make_ticket(s)
    repo.record_message(s, ticket_id=t.id, actor_chat_id=5, message="hello")
    msgs = [e for e in _audit(s) if e.kind == "message"]
    assert len(msgs) == 1
    assert "hello" in msgs[0].payload_json


def test_rejected_transitions_write_no_audit_row(s):
    """A guard that rejects an action must leave the audit log untouched —
    no orphaned 'wip'/'close'/'move' row for an action that did not happen."""
    t = _make_ticket(s)
    repo.set_wip(s, t.id, who="Alice", actor_chat_id=1)  # open -> wip (audited)
    before = len(_audit(s))

    with pytest.raises(ValueError):
        repo.set_wip(s, t.id, who="Bob", actor_chat_id=2)  # already wip
    with pytest.raises(ValueError):
        repo.move_ticket(s, t.id, new_group="BiMi", actor_chat_id=2)  # not open
    with pytest.raises(LookupError):
        repo.set_wip(s, 999, who="x", actor_chat_id=2)  # missing

    repo.close_ticket(s, t.id, actor_chat_id=1)
    with pytest.raises(ValueError):
        repo.close_ticket(s, t.id, actor_chat_id=2)  # already closed

    kinds_after = [e.kind for e in _audit(s)]
    # Exactly the two successful actions were recorded; no rejected ones.
    assert kinds_after == ["open", "wip", "close"]
    assert len(_audit(s)) == before + 1  # only the close added


def test_set_wip_atomic_claim_keeps_first_owner(s):
    """The OPEN->WIP transition is an atomic conditional claim: a second
    claim loses (raises) and must not overwrite the first owner."""
    t = _make_ticket(s)
    repo.set_wip(s, t.id, who="Alice", actor_chat_id=1)
    with pytest.raises(ValueError):
        repo.set_wip(s, t.id, who="Bob", actor_chat_id=2)
    assert repo.get_ticket(s, t.id).who_wip == "Alice"


# --- Models ---------------------------------------------------------------


def test_ticket_display_includes_id_and_status(s):
    t = _make_ticket(s, text="needs cups")
    assert "#" + str(t.id) in t.display()
    assert "OPEN" in t.display()
    assert "needs cups" in t.display()


def test_registration_display_name():
    r = Registration(chat_id=1, group_name="X", first_name="A", last_name="B", username="u")
    assert r.display_name() == "A B <@u>"
    r2 = Registration(chat_id=2, group_name="X", username="solo")
    assert r2.display_name() == "Unbekannt <@solo>"
    r3 = Registration(chat_id=3, group_name="X")
    assert r3.display_name() == "Unbekannt"


# --- Stats ----------------------------------------------------------------


def test_stats_summary_empty(s):
    st = repo.stats_summary(s)
    assert st.total == 0
    assert (st.open, st.wip, st.closed) == (0, 0, 0)
    assert st.wait_median_s is None and st.pickup_median_s is None


def test_stats_summary_counts_by_status_category_group(s):
    _make_ticket(s, category="Geld", group_requesting="Cocktailbar 1")
    b = _make_ticket(s, category="Bier", group_requesting="Biertheke 1")
    c = _make_ticket(s, category="Bier", group_requesting="Biertheke 1")
    repo.set_wip(s, b.id, who="A", actor_chat_id=9)
    repo.close_ticket(s, c.id, actor_chat_id=9)

    st = repo.stats_summary(s)
    assert st.total == 3
    assert (st.open, st.wip, st.closed) == (1, 1, 1)
    assert st.by_category == {"Geld": 1, "Bier": 2}
    assert st.by_group == {"Cocktailbar 1": 1, "Biertheke 1": 2}


def test_stats_summary_timings(s):
    # Control timestamps directly: wait = created→closed, pickup = created→wip.
    base = datetime(2026, 7, 10, 20, 0, 0)
    t1 = _make_ticket(s)
    t2 = _make_ticket(s)
    for tid, closed_after in ((t1.id, 10), (t2.id, 20)):
        obj = s.get(Ticket, tid)
        obj.created_at = base
        obj.closed_at = base + timedelta(minutes=closed_after)
        obj.status = TicketStatus.CLOSED
        s.add(obj)
    s.add(AuditEvent(kind="wip", ticket_id=t1.id, ts=base + timedelta(minutes=2)))
    s.add(AuditEvent(kind="wip", ticket_id=t2.id, ts=base + timedelta(minutes=6)))
    s.commit()

    st = repo.stats_summary(s)
    assert st.wait_median_s == 15 * 60  # median([600, 1200])
    assert st.wait_max_s == 20 * 60
    assert st.pickup_median_s == 4 * 60  # median([120, 360])
    assert st.pickup_max_s == 6 * 60


def test_stats_summary_pickup_uses_earliest_wip(s):
    base = datetime(2026, 7, 10, 20, 0, 0)
    t = _make_ticket(s)
    obj = s.get(Ticket, t.id)
    obj.created_at = base
    s.add(obj)
    # Two wip events for the same ticket: only the earliest counts.
    s.add(AuditEvent(kind="wip", ticket_id=t.id, ts=base + timedelta(minutes=5)))
    s.add(AuditEvent(kind="wip", ticket_id=t.id, ts=base + timedelta(minutes=9)))
    s.commit()

    st = repo.stats_summary(s)
    assert st.pickup_max_s == 5 * 60

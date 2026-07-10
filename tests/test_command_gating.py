"""Permission-gating is enforced by route-selection filters on each handler.
The unit tests in test_permissions.py prove IsOrga/IsDeveloper decide
correctly in isolation; these tests prove the filters are actually WIRED
onto the right handlers, so an accidentally-dropped `IsOrga()` on a command
(which would let any user run it) fails CI instead of shipping green.

The intentionally-open commands (/bug, /feature) are pinned too, so a future
review doesn't "helpfully" gate them — and so the decision is documented in
an executable place. Orga registration itself is deliberately self-service
(any volunteer may /register an orga group); see docs/OPERATIONS.md.
"""

from unifestbestellbot.bot import admin as admin_flow
from unifestbestellbot.bot import orga as orga_flow
from unifestbestellbot.bot.filters import IsDeveloper, IsOrga


def _filters_for(observer, callback):
    """The filter instances attached to the handler whose callback is `callback`."""
    for h in observer.handlers:
        if h.callback is callback:
            return [f.callback for f in h.filters]
    raise AssertionError(f"{callback.__name__} is not registered on {observer}")


def _has_filter(observer, callback, filter_cls) -> bool:
    return any(isinstance(f, filter_cls) for f in _filters_for(observer, callback))


# --- orga commands must be gated by IsOrga -------------------------------

ORGA_MESSAGE_COMMANDS = [
    orga_flow.cmd_wip,
    orga_flow.cmd_close,
    orga_flow.cmd_move,
    orga_flow.cmd_message,
    orga_flow.cmd_tickets,
    orga_flow.cmd_all,
    orga_flow.cmd_history,
    orga_flow.cmd_help2,
]

ORGA_CALLBACKS = [
    orga_flow.on_wip_choice,
    orga_flow.on_close_choice,
]


def test_orga_message_commands_are_gated_by_is_orga():
    for cmd in ORGA_MESSAGE_COMMANDS:
        assert _has_filter(orga_flow.router.message, cmd, IsOrga), (
            f"{cmd.__name__} is missing the IsOrga() filter — any user could run it"
        )


def test_orga_ticket_callbacks_are_gated_by_is_orga():
    for cb in ORGA_CALLBACKS:
        assert _has_filter(orga_flow.router.callback_query, cb, IsOrga), (
            f"{cb.__name__} is missing the IsOrga() filter on its callback path"
        )


# --- intentionally-open commands must stay ungated -----------------------


def test_bug_and_feature_are_open_to_everyone():
    """Deliberate: any user (stall volunteer, not just orga) can report a
    bug or request a feature. Pinned so it isn't 'fixed' by mistake."""
    for cmd in (orga_flow.cmd_bug, orga_flow.cmd_feature):
        assert not _has_filter(orga_flow.router.message, cmd, IsOrga)


def test_helpers_is_open_to_registered_stands():
    assert not _has_filter(orga_flow.router.message, orga_flow.cmd_helpers, IsOrga)


# --- developer-only commands ---------------------------------------------


def test_developer_commands_are_developer_only():
    for cmd in (admin_flow.cmd_closeall, admin_flow.cmd_system, admin_flow.cmd_version):
        assert _has_filter(admin_flow.router.message, cmd, IsDeveloper)
    # And NOT merely IsOrga — /closeall is destructive, developer-gated.
    assert not _has_filter(admin_flow.router.message, admin_flow.cmd_closeall, IsOrga)

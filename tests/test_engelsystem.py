import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from unifestbestellbot.engelsystem import (
    EngelsystemClient,
    make_shift_lookup,
    summarize_shifts,
)

FIXTURE = Path(__file__).parent / "fixtures" / "engelsystem_shifts.json"


@pytest.fixture
def shifts() -> list[dict]:
    return json.loads(FIXTURE.read_text())["data"]


# --- summarize_shifts ----------------------------------------------------


def test_summarize_with_current_shift(shifts):
    now = datetime(2026, 5, 22, 15, 0, tzinfo=UTC)  # halfway through shift 1
    out = summarize_shifts(shifts, now=now)
    assert "Momentane Schicht" in out
    assert "Alice [Bar]" in out
    assert "Carol [Kasse]" in out
    # Shift 2 starts at 16:00, only 1h away — outside the 20m window by default.
    assert "Nächste Schicht" not in out


def test_summarize_with_imminent_next_shift(shifts):
    # 16:00 shift starts at 16:00; if it's 15:50, it's 10 minutes away → in window.
    now = datetime(2026, 5, 22, 15, 50, tzinfo=UTC)
    out = summarize_shifts(shifts, now=now)
    assert "Momentane Schicht" in out  # shift 1 still running until 16:00
    assert "Nächste Schicht in 10m" in out
    assert "Dan [Bar]" in out


def test_summarize_no_running_no_imminent(shifts):
    now = datetime(2026, 5, 22, 19, 0, tzinfo=UTC)
    out = summarize_shifts(shifts, now=now)
    assert "Keine aktuellen oder bevorstehenden" in out


def test_summarize_handles_missing_entries():
    shifts = [
        {
            "starts_at": "2026-05-22T14:00:00+00:00",
            "ends_at": "2026-05-22T16:00:00+00:00",
        }
    ]
    now = datetime(2026, 5, 22, 15, 0, tzinfo=UTC)
    out = summarize_shifts(shifts, now=now)
    assert "Momentane Schicht" in out


def test_summarize_empty_list():
    assert summarize_shifts([], now=datetime(2026, 5, 22, tzinfo=UTC)).startswith(
        "Keine"
    )


def test_summarize_remaining_time_renders_hours():
    shifts = [
        {
            "starts_at": "2026-05-22T14:00:00+00:00",
            "ends_at": "2026-05-22T18:00:00+00:00",
            "entries": [],
        }
    ]
    out = summarize_shifts(shifts, now=datetime(2026, 5, 22, 14, 30, tzinfo=UTC))
    assert "3h 30m" in out


# --- make_shift_lookup ---------------------------------------------------


async def test_lookup_reports_missing_location_mapping(config):
    """Tickets stall has location 'Eingang' which is not in config.locations."""
    client = AsyncMock(spec=EngelsystemClient)
    lookup = make_shift_lookup(client)
    out = await lookup("Tickets", config)
    assert "nicht korrekt konfiguriert" in out or "keine Schichten" in out
    client.shifts_at.assert_not_called()


async def test_lookup_calls_client_with_resolved_location_id(config, shifts):
    client = AsyncMock(spec=EngelsystemClient)
    client.shifts_at = AsyncMock(return_value=shifts)
    lookup = make_shift_lookup(client)
    await lookup("Cocktailbar", config)
    client.shifts_at.assert_awaited_once_with(12)  # Innenhof -> 12


async def test_lookup_handles_http_failure_gracefully(config):
    client = AsyncMock(spec=EngelsystemClient)
    client.shifts_at = AsyncMock(side_effect=RuntimeError("boom"))
    lookup = make_shift_lookup(client)
    out = await lookup("Cocktailbar", config)
    assert "fehlgeschlagen" in out

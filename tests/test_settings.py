"""Settings validation. The required secret fields come from the test
environment set in conftest.py; these cover the timezone fail-fast."""

import pytest
from pydantic import ValidationError
from unifestbestellbot.settings import Settings


def test_default_timezone_resolves():
    s = Settings()  # type: ignore[call-arg]
    assert s.timezone == "Europe/Berlin"
    assert s.local_tz().key == "Europe/Berlin"


def test_bogus_timezone_refuses_to_boot():
    with pytest.raises(ValidationError):
        Settings(timezone="Not/ARealZone")  # type: ignore[call-arg]

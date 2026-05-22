import contextlib
import logging
import logging.handlers

import pytest
from unifestbestellbot.logging_setup import setup_logging


@pytest.fixture
def reset_root_logger():
    """Snapshot root logger handlers + level; restore after the test so
    we don't leave the test runner without output."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    for h in list(root.handlers):
        with contextlib.suppress(Exception):
            h.close()
        root.removeHandler(h)
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)


def test_setup_logging_creates_log_dir_and_file(tmp_path, reset_root_logger):
    log_file = setup_logging(level="INFO", log_dir=str(tmp_path / "logs"), retention_days=7)
    assert log_file.parent.exists()
    assert log_file.name == "bot.log"


def test_setup_logging_installs_console_and_file_handlers(tmp_path, reset_root_logger):
    setup_logging(level="INFO", log_dir=str(tmp_path / "logs"), retention_days=7)
    root = logging.getLogger()
    types = [type(h) for h in root.handlers]
    assert logging.handlers.TimedRotatingFileHandler in types
    # The console handler is a plain StreamHandler (colorlog's
    # ColoredFormatter sits on it).
    assert logging.StreamHandler in types


def test_file_handler_rotates_at_midnight(tmp_path, reset_root_logger):
    setup_logging(level="INFO", log_dir=str(tmp_path / "logs"), retention_days=14)
    root = logging.getLogger()
    file_handler = next(
        h for h in root.handlers
        if isinstance(h, logging.handlers.TimedRotatingFileHandler)
    )
    assert file_handler.when == "MIDNIGHT"
    assert file_handler.backupCount == 14
    assert file_handler.encoding == "utf-8"


def test_setup_logging_resets_handlers_on_repeat(tmp_path, reset_root_logger):
    setup_logging(level="INFO", log_dir=str(tmp_path / "logs"), retention_days=1)
    first_count = len(logging.getLogger().handlers)
    setup_logging(level="INFO", log_dir=str(tmp_path / "logs2"), retention_days=1)
    second_count = len(logging.getLogger().handlers)
    assert first_count == second_count  # not duplicated


def test_setup_logging_writes_to_file(tmp_path, reset_root_logger):
    log_file = setup_logging(level="INFO", log_dir=str(tmp_path / "logs"), retention_days=1)
    logging.getLogger("test").info("hello from test")
    # Flush the file handler so the line is on disk before we read.
    for h in logging.getLogger().handlers:
        h.flush()
    body = log_file.read_text()
    assert "hello from test" in body
    assert "INFO" in body


def test_setup_logging_respects_level(tmp_path, reset_root_logger):
    setup_logging(level="WARNING", log_dir=str(tmp_path / "logs"), retention_days=1)
    assert logging.getLogger().level == logging.WARNING

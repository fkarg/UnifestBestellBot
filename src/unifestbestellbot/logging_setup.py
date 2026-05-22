"""Logging configuration. Two handlers:

- the console, with colour-coded level names via `colorlog`, intended
  for an operator watching the bot in a tmux pane on the VM;
- a `TimedRotatingFileHandler` writing to `<log_dir>/bot.log`, rotating
  at midnight and keeping `log_retention_days` files of history.

`uvicorn`'s and `aiogram`'s loggers are routed through the same handlers
so everything ends up in one place."""

import logging
import logging.handlers
from pathlib import Path

import colorlog


def setup_logging(*, level: str, log_dir: str, retention_days: int) -> Path:
    """Configure the root logger with a coloured console handler and a
    daily-rotating file handler. Returns the path of the live log file."""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "bot.log"

    root = logging.getLogger()
    root.setLevel(level.upper())
    # Reset any handlers a prior caller (or pytest) may have installed so
    # we don't end up double-logging.
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler()
    console.setFormatter(
        colorlog.ColoredFormatter(
            fmt=(
                "%(log_color)s%(asctime)s %(levelname)-8s%(reset)s "
                "%(cyan)s%(name)s%(reset)s: %(message)s"
            ),
            datefmt="%H:%M:%S",
            log_colors={
                "DEBUG": "white",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "red,bg_white",
            },
        )
    )
    root.addHandler(console)

    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        backupCount=retention_days,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(file_handler)

    # uvicorn installs its own handlers by default; route them through ours.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    return log_file

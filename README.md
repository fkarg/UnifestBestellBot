# UnifestBestellBot

Telegram bot for stalls at the Karlsruhe Unifest to order supplies (change
money, cups, beer, cocktail materials, helpers, ...). Includes a small live
dashboard for the orga groups handling tickets.

## Stack

- **aiogram v3** (async Telegram bot)
- **SQLModel** + SQLite (single file, `create_all` at startup, no migrations)
- **FastAPI** + SSE for the dashboard (no MQTT broker)
- **uv** for dependency management

## Quick start

```sh
# 1. Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install dependencies
uv sync

# 3. Configure secrets
cp .env.example .env        # then edit
cp config.yaml.example config.yaml   # then edit for the year's structure

# 4. Run
uv run unifestbestellbot
```

The bot polls Telegram and serves the dashboard at `http://0.0.0.0:8000`.
Open `http://<host>:8000/?group=Finanz` (or `?group=BiMi`, etc.) on a TV to
see live tickets for one orga group.

## Tests

```sh
uv run pytest
uv run ruff check
uv run ty check
```

The suite covers: config validation, repo CRUD + audit (including
rejected-transition immutability and the atomic WIP claim), the /register
flow, the full /request FSM end-to-end per category, all orga commands +
inline pickers and their permission gating, the notify fan-out (mute,
flood-control retry, block-then-unregister), the dashboard event bus
(including orga lifecycle publishing), Engelsystem summary rendering, and
the dashboard endpoints. Run `uv run pytest` for the live count.

## Development

Every commit bumps the package's patch version in `pyproject.toml` and
`uv.lock`. The hook is tracked in `.githooks`; enable it once after cloning:

```sh
git config core.hooksPath .githooks
```

The version bump also runs for empty commits, amend, merge, and revert. As with
all pre-commit hooks, `git commit --no-verify` bypasses it.

## Documentation

- [`docs/REWRITE_PLAN.md`](docs/REWRITE_PLAN.md) — the architecture and
  why each decision was made
- [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) — detailed module
  layout, schemas, and code sketches
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — deploy, backup, restore,
  common fixes
- [`docs/MIGRATION.md`](docs/MIGRATION.md) — observable behaviour and
  config differences vs. the legacy bot

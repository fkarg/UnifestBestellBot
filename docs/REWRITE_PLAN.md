# UnifestBestellBot — Rewrite Plan

Goal: replace the python-telegram-bot v13 implementation with a minimal,
well-tested, easy-to-fix-in-production codebase. No high-availability
engineering; the operating window is short and on-site fixes are the
support model.

## What's wrong with the current code

- **python-telegram-bot v13** (released 2021, sync API). v22+ is async with
  a different API. The pinned `urllib3<=2.0` constraint keeps breaking.
- **PicklePersistence** (`bot_persistence.cntx`). State is a pickled graph
  of Python objects; refactoring `Ticket` requires migration code, and
  inspecting state requires Python.
- **MQTT broker for the dashboard.** A whole mosquitto process, ACL config,
  websocket bridging, and a separate parcel-built static page to push
  ~30 events/hour to a handful of TVs. Pure overhead.
- **Stringly-typed `bot_data` / `user_data`** with keys like
  `"group_association"`, `"open_ticket"`, `"first_choice"`, `"highest_id"`.
  Typo-prone, no schema, no audit trail.
- **Circular imports** between `commands.py`, `states.py`, and `tickets.py`
  patched with local imports — symptom of unclear layering.
- **No tests.** `.travis.yml` exists but the repo has no test suite.
- **State machine spread across files.** Adding a category requires editing
  `main.py` (regex filters), `states.py` (state constants and handlers),
  `config.py` (option lists), and `tickets.py` (category→group mapping).

## Decisions

| Concern              | Now                                | Proposed                                          |
| -------------------- | ---------------------------------- | ------------------------------------------------- |
| Bot library          | PTB v13 (sync)                     | **aiogram v3** (see below)                        |
| Persistence          | `PicklePersistence`                | **SQLite via SQLModel** (create_all, no migrations) |
| Config               | `load_json` over a dozen files     | **`.env` for secrets + `config.yaml` for stall/group structure** |
| Dashboard transport  | MQTT (mosquitto + paho + mqtt.js)  | **SSE from the bot's own FastAPI**                |
| Dashboard build      | parcel + npm                       | **Plain HTML + one JS file**                      |
| Web framework        | none                               | **FastAPI** (alongside aiogram)                   |
| Logging              | rich + ANSI format codes           | **stdlib logging.dictConfig**                     |
| Process model        | Threaded long-poll                 | **Single async event loop**                       |
| Keyboards            | Reply keyboards (regex on text)    | **Mix: reply keyboards + free text for flows; inline for picking specific tickets** |

### Why aiogram v3 over PTB v22+

The v13→v22 PTB migration is a near-rewrite anyway (sync→async, persistence
API changes, handler signatures), so the cost of switching libraries is
not much higher than the cost of upgrading.

aiogram v3 gives us:
- **Router-based handler registration** — handlers live next to the flow
  they implement, not centrally wired in `main.py`.
- **FSM with pluggable storage** — tests can use `MemoryStorage` directly;
  production can use the same.
- **Trivially testable handlers** — they're just async functions taking
  `Message` / `CallbackQuery`. No `Updater` / `Dispatcher` ceremony in tests.
- **Cleaner type hints** end-to-end.

PTB v22 is still a fine library; this is a judgement call, not a bug fix
on PTB's part. The test ergonomics tip the scale.

### Why SSE over MQTT

The dashboard is a one-way push from the bot to a small number of browsers
on the same network as the bot. Server-Sent Events does exactly that with:
- no broker process,
- native browser reconnect,
- plain `text/event-stream` HTTP — debuggable with `curl`,
- runs in the same FastAPI process as the bot.

We lose nothing in the current dashboard's UX (snapshot on load + live
updates + sound on OPEN + per-orga filter).

### Why SQLite + SQLModel, no migrations

- **SQLite**: one file, copied with `cp` for backups, inspectable on-site
  with the `sqlite3` CLI, no separate process to babysit, WAL mode covers
  the dashboard's read concurrency.
- **SQLModel**: Pydantic + SQLAlchemy in one model class. Same model is
  used by aiogram handlers, the FastAPI SSE endpoint, and tests. One source
  of truth for shape and validation.
- **No migrations.** `SQLModel.metadata.create_all(engine)` at startup is
  the entire schema setup. The only persistent state across restarts is
  *open tickets and registrations during one event*. Between events the
  DB is thrown away — stall layout, orga groups, and routing change year
  to year and live in `config.yaml`, not the database. If a schema change
  is needed mid-event, `rm bot.db && systemctl restart` is the migration.

### Config ergonomics

The current setup spreads ~10 single-value JSON files across
`unifest-secrets/`. Replace with two files:

- **`.env`** — credentials only: `TELEGRAM_TOKEN`,
  `DEVELOPER_CHAT_ID`, `UPDATES_CHANNEL_ID`, `ENGELSYSTEM_API_KEY`,
  `DATABASE_URL`, `WEB_BIND`. Loaded via `pydantic-settings`.
- **`config.yaml`** — the year's stall/orga/routing structure. Loaded
  once at startup, validated by a Pydantic model. Reloaded by restarting
  the bot (3 seconds; the operational support model anyway).

This folds `groups.json`, `orga.json`, `hidden.json`, `mapping.json`,
`location.json` and the hard-coded category → orga group routing from
`tickets.py:create_ticket` into one declarative file. See
`docs/IMPLEMENTATION.md` for the schema.

## Target layout

```
unifestbestellbot/
  pyproject.toml                # uv-managed
  docs/
    REWRITE_PLAN.md             # this file
    OPERATIONS.md               # how to deploy, backup, restore, debug
  config.yaml                   # stall/orga structure for this year's event
  .env                          # secrets (gitignored); .env.example committed
  src/unifestbestellbot/
    __main__.py                 # `uv run unifestbestellbot`
    settings.py                 # pydantic-settings: .env
    config.py                   # Pydantic schema + loader for config.yaml
    db.py                       # engine + session + create_all
    models.py                   # SQLModel: Ticket, Registration, AuditEvent
    repo.py                     # data access functions over SQLModel sessions
    events.py                   # in-process pub/sub for dashboard SSE
    bot/
      __init__.py               # build aiogram Dispatcher + Routers
      register.py               # /register /unregister /status
      request.py                # /request conversation (FSM)
      orga.py                   # /wip /close /move /message /all /tickets
      admin.py                  # /closeall /resetcount /system (dev only)
      common.py                 # keyboards, helpers, decorators
    engelsystem.py              # shift lookup, httpx.AsyncClient
    web.py                      # FastAPI: snapshot + SSE + static
    static/
      index.html
      main.js
      style.css
      sound_a.mp3
    i18n.py                     # all German strings in one module
  tests/
    conftest.py
    test_repo.py
    test_register_flow.py
    test_request_flow.py
    test_orga_flow.py
    test_permissions.py
    test_engelsystem.py
    test_web.py
    fixtures/
      engelsystem_shifts.json
  .github/workflows/ci.yml      # uv run pytest
  systemd/
    unifestbestellbot.service   # one VM, one unit
```

## Data model

Three tables, defined as SQLModel classes. See `docs/IMPLEMENTATION.md`
for the full Python source; sketch here:

- `Registration(chat_id, group_name, username, first_name, last_name, registered_at)`
  — keyed by `chat_id`. Indexed on `group_name` for the fanout queries
  (`group_msg`).
- `Ticket(id, status, category, text, group_requesting, group_tasked, who_wip, created_at, closed_at)`
  — `status` is a `TicketStatus` enum (`OPEN`/`WIP`/`CLOSED`). Partial
  index on non-closed rows.
- `AuditEvent(id, ts, kind, ticket_id, actor_chat_id, payload_json)`
  — append-only log of every state transition. Useful for the developer
  to reconstruct what happened on-site.

`PRAGMA journal_mode=WAL` set at engine creation. `create_all` runs on
startup; that is the entire schema lifecycle.

Conversation in-flight state lives in aiogram's `MemoryStorage` —
ephemeral by design. Half-finished `/request` flows should not survive
a restart.

## Dashboard

- `GET /` → `static/index.html`
- `GET /api/tickets?group=Finanz` → snapshot of open + wip tickets
- `GET /api/stream?group=Finanz` → SSE: `event: ticket\ndata: {...}\n\n`
- `static/main.js`: fetch snapshot, open EventSource, render tickets,
  play sound on `OPEN`. ~80 lines.

Replace `#finanz` URL hash with `?group=finanz` query param.

## Tests

Targeted, not exhaustive. A test is worth writing when it catches a class
of bug that has bitten before or that is non-obvious.

1. **Repo** — open/wip/close/move transitions persist correctly; audit events
   recorded; status invariants enforced.
2. **Permissions** — orga-only commands reject non-orga users; dev-only
   commands reject non-devs. Cheap to cover, embarrassing to miss.
3. **Request flow** — script `/request → Geld → Wechselgeld → Scheine`
   end-to-end with synthetic `Update`s, assert the ticket lands with
   `group_tasked='Finanz'`.
4. **Category routing** — table-driven test for every category →
   group_tasked mapping.
5. **Engelsystem** — feed a recorded JSON fixture, assert "current" and
   "next" shifts are extracted, including timezone handling.
6. **SSE** — open a stream, create a ticket via the repo, assert the
   event is broadcast within N ms.

CI: GitHub Actions, `uv run pytest`. Drop `.travis.yml`.

## What gets deleted

- `mosquitto.conf`, `mosquitto_acl`, `src/dashboard_bridge.py`,
  `paho-mqtt` dependency.
- `experiments.py` (dead scratch).
- `dashboard/` (replaced with `src/unifestbestellbot/static/`).
- `bot_persistence.cntx` (no migration; clean start at Unifest 2026).
- `src/parser.py` (inline `argparse` or drop entirely).
- `rich` dependency.
- `.travis.yml`.

## What is kept

- **Telegram error reporting to the developer chat.** This is the one
  piece of "reliability theatre" that earns its keep — when something
  breaks at the festival, having the traceback show up in Telegram saves
  minutes that matter. Trim to a one-line summary; full traceback to a
  rotating local log file.
- **German UI strings.** Centralized in `i18n.py` so they're greppable
  and consistent.
- **The conversation shape of `/request`.** Volunteers already know it;
  don't redesign the UX.

## Migration

Clean start at Unifest 2026. No pickle→sqlite import code. Registrations
get re-collected at the start of the event (~30 stalls, takes minutes).

Within an event the database persists across bot restarts so that open
tickets and registrations survive a process bounce. Across events, the
DB file is deleted — the year's `config.yaml` is the only thing that
needs to be edited and re-committed.

## Order of work

Each step is shippable independently and adds tests for what it ships.

1. **Scaffold + DB.** Package layout, `pydantic-settings`, SQLite +
   migration runner, `repo.py`, `models.py`, repo tests.
2. **Bot skeleton on aiogram.** `/start`, `/help`, `/register`,
   `/unregister`, `/status`. Inline-button group selection. Tests.
3. **Request flow.** Port `/request` FSM, end-to-end test per category.
4. **Orga flow.** `/wip`, `/close`, `/move`, `/message`, `/all`,
   `/tickets`, audit logging, permission tests.
5. **Engelsystem.** Port `helpers` command, fixture-based test.
6. **FastAPI dashboard.** Snapshot endpoint, SSE, static page, tests.
7. **Deployment.** systemd unit + `docs/OPERATIONS.md` covering deploy,
   backup, restore, common fixes.
8. **Cutover.** Run alongside on a debug token, verify, swap the
   production token.

Ballpark: 3–5 focused days, ~1500 LOC + ~800 LOC of tests.

## Non-goals

- High availability, failover, hot-reload of config.
- Multi-tenant (this is one bot for one festival).
- Internationalization beyond German.
- A general-purpose ticketing framework. This is a single-purpose tool.
- Realtime collaboration features in the dashboard (orga actions stay
  in Telegram per the chosen scope).

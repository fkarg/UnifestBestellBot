# UnifestBestellBot — Rust port

A behavioural-equivalent rewrite of the Python implementation in
`../src/unifestbestellbot/`. The Python version is the reference; this
crate is a parallel-track experiment for fun and comparison.

## What's preserved verbatim

The Python and Rust binaries are designed to be **drop-in interchangeable**
at every wire boundary:

- **`config.yaml`** — same schema, same validators, same error messages.
- **SQLite schema** — column names + types match, so a `bot.db` written
  by either implementation is readable by the other.
- **SSE payload** — JSON shape matches `Ticket.model_dump_json` exactly.
- **German user-facing strings** — every line in `src/i18n.rs` is a
  verbatim port of `src/unifestbestellbot/i18n.py`.
- **Engelsystem fixture** — `tests/fixtures/engelsystem_shifts.json` is
  the same file used in the Python tests.

## Stack

| Concern | Crate |
|---|---|
| Telegram | teloxide 0.13 (rustls, no native-tls) |
| DB | sqlx 0.8 (sqlite + chrono) |
| Web + SSE | axum 0.7 + tower-http |
| Async | tokio |
| Config | serde + serde_yaml |
| Logging | tracing + tracing-subscriber + tracing-appender |
| HTTP client | reqwest (rustls) |
| Test HTTP server | wiremock |

## Architecture

Handler logic is **pure**: each command takes (pool, config, caller,
args, [state]), mutates an `Outbox`, returns. The `Outbox` collects
`Action`s — `Reply`, `Dm`, `Channel`, `Dev`, `EditMessage`,
`AnswerCallback`. A thin teloxide adapter (`bot/adapter.rs`) translates
incoming updates into these calls and executes the resulting actions
against a real `Bot`.

```
┌────────────────────────────────────────────────────────┐
│                 teloxide adapter                       │
│   Update → Caller / args                               │
│            ↓                                           │
│   logic fn (pool, config, caller, ...) → Outbox        │
│            ↓                                           │
│   for each Action: send_message / edit / answer ...    │
└────────────────────────────────────────────────────────┘
```

This means behavioural tests can drive the logic functions directly
against an in-memory SQLite and assert on (a) the outbox actions and
(b) the DB state — without inventing teloxide fakes.

## Tests

```sh
cargo test
```

154 tests across nine integration binaries:

| File | Coverage |
|---|---|
| `tests/config_behaviour.rs` | YAML loading, validators, routing, display strings, shift_digest defaults |
| `tests/repo_behaviour.rs` | Ticket lifecycle, mute filtering, audit log, recent-closes history |
| `tests/engelsystem_behaviour.rs` | Pure summary renderer + wiremock-backed HTTP |
| `tests/web_behaviour.rs` | Snapshot endpoint, EventBus broadcast, matches_group |
| `tests/register_behaviour.rs` | /start /help /register /unregister /status /quiet /loud — picker and textual paths |
| `tests/request_behaviour.rs` | Full /request FSM, every category branch, finalize side-effects |
| `tests/orga_behaviour.rs` | /wip /close /move /message /all /tickets /history /bug /feature plus IsOrga gate |
| `tests/admin_unknown_behaviour.rs` | /closeall fan-out + Entwickler attribution; unknown-command fallback |
| `tests/digest_behaviour.rs` | Window arithmetic + digest_once announce/skip/reannounce/HTTP-fail/routing |

Every repo test goes through real sqlx + SQLite (in-memory). Every web
test spawns axum on an ephemeral port and uses reqwest as a real HTTP
client. Engelsystem tests stand up wiremock servers for HTTP behaviour.

## Run

```sh
cp ../.env.example .env       # same env vars as the Python side
cp ../config.yaml.example config.yaml
cargo run --release
```

The binary loads `.env`, opens `bot.db`, starts the dashboard on
`WEB_BIND`, posts the startup channel notice, and begins long-polling.
Ctrl-C exits cleanly (teloxide's ctrlc_handler).

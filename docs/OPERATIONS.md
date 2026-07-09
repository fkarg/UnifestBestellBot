# Operations

The bot's support model is "fix in production". This document tells you
where to look and what to do when something is wrong.

## Deploy

One VM, one `tmux` (or `screen`) session. The bot polls Telegram and
serves the dashboard HTTP from the same process. For a few days of
operating, this is more practical than a systemd indirection: the
operator can watch the live coloured output, paste a Python REPL in
the next tmux window, and bounce the process with `Ctrl-C` + up-arrow.

```sh
# On the VM, in a long-lived tmux session
git clone <repo> ~/unifestbestellbot
cd ~/unifestbestellbot

# Install uv if missing
curl -LsSf https://astral.sh/uv/install.sh | sh

uv sync
cp .env.example .env       # fill in TELEGRAM_TOKEN, DEVELOPER_CHAT_ID,
                           # UPDATES_CHANNEL_ID, ENGELSYSTEM_API_KEY
cp config.yaml.example config.yaml   # edit for the year's stalls / orga

# Run it
uv run unifestbestellbot
```

A typical workflow:

```sh
tmux new -s bot                       # start (or `tmux attach -t bot`)
uv run unifestbestellbot              # foreground; logs print live
                                       # detach with Ctrl-b d
```

For local testing, you can run the whole bot under a file watcher. This is
deliberately a development workflow, not the default event deploy path:

```sh
uv run watchfiles --filter all \
  --ignore-paths .venv,logs,bot.db,bot.db-shm,bot.db-wal \
  'uv run unifestbestellbot' src config.yaml .env
```

On changes, `watchfiles` sends `SIGINT` to the running bot, waits for its
clean shutdown, then starts it again. Telegram polling is restarted too, so
in-flight `/request` conversations are dropped just like a manual restart.

`Ctrl-C` exits cleanly: SSE subscribers are disconnected, the bot session
is closed, and the Engelsystem HTTP client is shut down.

**Self-healing.** The two long-running parts (Telegram polling and the web
server) are each supervised: if one throws, it is restarted with backoff
and the traceback is DMed to `DEVELOPER_CHAT_ID`, so a transient crash does
not take the whole process down — important on the foreground tmux path,
which otherwise has no supervisor. Handler-level exceptions are likewise
caught and forwarded to the developer. What this does **not** cover is the
process being killed outright (OOM, `kill`, VM reboot): for auto-restart on
that, use the systemd unit (`Restart=on-failure`) or wrap the tmux command
in `while true; do uv run unifestbestellbot; sleep 2; done`.

## Update

```sh
cd ~/unifestbestellbot
git pull
uv sync
# In the tmux window running the bot:
#   Ctrl-C   (graceful stop)
#   ↑ Enter  (restart from shell history)
```

Restart drops in-flight `/request` conversations (FSM state is in-memory)
but does not lose tickets or registrations (those live in `bot.db`).

## Logs

Two destinations, configured by `setup_logging()` at startup:

- **Terminal** — coloured by level (INFO green, WARNING yellow, ERROR red,
  CRITICAL on red background). Intended for the human watching the tmux
  pane.
- **`./logs/bot.log`** — plain-text, no colour codes. Rotates daily at
  local midnight; `LOG_RETENTION_DAYS` (default 14) days of history are
  kept as `bot.log.YYYY-MM-DD` next to the live file.

`LOG_LEVEL` (default `INFO`) controls both. `LOG_DIR` (default `./logs`)
controls the file destination. `uvicorn` and `aiogram` are routed through
the same handlers so everything lands in one place.

```sh
# Watch the live colour stream — the tmux pane already shows it; this is
# for a second pane.
tail -f logs/bot.log

# Yesterday's full session, no colours
less logs/bot.log.$(date -d yesterday +%F)
```

## Alternative: systemd

A `systemd/unifestbestellbot.service` unit is committed in the repo for
operators who want auto-restart on crash. It is **secondary** — for a
short event, the tmux setup above is simpler and more legible. If you do
use systemd, the file handler still rotates inside `LOG_DIR`; the
terminal handler's colours will be stripped in the journal.

```sh
sudo cp systemd/unifestbestellbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now unifestbestellbot
journalctl -u unifestbestellbot -f
```

## Configuration

Two files. Restart the bot to pick up changes.

- **`.env`** — secrets and runtime knobs. See `.env.example`.
- **`config.yaml`** — the year's stall and orga structure. Schema is
  validated at startup; typos refuse to boot. See `config.yaml.example`.

`TIMEZONE` (in `.env`, default `Europe/Berlin`) is the display/window
timezone. All stored timestamps are naive UTC; this only controls how they
are shown (`/history`, the shift digest) and how the digest's operational
window is interpreted. It is read explicitly, so behaviour does **not**
depend on the VM's ambient timezone — but set it if the event isn't in
Berlin time.

### Mental model for `config.yaml`

A `stalls:` entry is a **group** that volunteers /register as
(e.g. `"Cocktailbar 1"`, `"Biertheke Süd"`). Each group has a
location and a stand type:

- `stalls[].name` — what volunteers type / pick to identify their group.
- `stalls[].location` — physical area, e.g. "Forum Süd", "DJ", "Mitte".
- `stalls[].type` — what the stand does, e.g. "Bier", "Cocktail",
  "Tickets". This drives the ticket text shown to handler teams.

Ticket text shown to orga is `"{location} [{type}]"`, e.g.
`"Forum Süd [Cocktail]"`. The group's *name* never appears in ticket
text — handlers orient on the stand, not on whichever crew is currently
on shift under that group identity.

Multiple groups can share the same `(location, type)` — two cocktail
crews at Forum Süd are fine.

`orga_groups:` are the **handler** teams (Finanz, BiMi, ...). Each
ticket category routes to one orga group; one orga group is the
`default:` for any category not explicitly listed. Orga group names
cannot collide with any stall name.

### Engelsystem shift digest

Optional. When `shift_digest.enabled: true` in `config.yaml`, a
background task DMs the orga group that handles the `Helfer` category
with the rota of any shift starting within `lookahead_minutes` (default
10). Polls every `check_interval_minutes` (default 5) and only fires
inside `window_start` to `window_end` (local time, may wrap midnight).

Requires `ENGELSYSTEM_API_KEY` to be set and every location's
Engelsystem id to be in `locations:`. Disabled-with-warning if the key
is missing.

### Year-to-year edits

| Change                                       | Where                              |
| -------------------------------------------- | ---------------------------------- |
| New group                                    | Add to `stalls:`                   |
| Group closed                                 | Remove from `stalls:`              |
| Group moved to a different location          | Edit `stalls[].location`           |
| Group changed what it sells (Bier → Cocktail)| Edit `stalls[].type`               |
| Different crew on shift                      | No config change — they /register at the same group name |
| Group exists but should not be advertised    | `hidden: true` (reachable only via textual `/register <name>`) |
| Orga teams renamed / reorganised             | `orga_groups:`                     |
| New ticket category                          | One row in `orga_groups[].categories` + one row in `FOLLOWUPS` in `bot/request.py` |
| Engelsystem location id changed              | `locations:`                       |

## Database

SQLite, single file. WAL mode.

```sh
# Inspect on the running box
sqlite3 /opt/unifestbestellbot/bot.db

sqlite> .tables
auditevent  registration  ticket

sqlite> SELECT id, status, group_requesting, group_tasked, text FROM ticket WHERE status != 'closed';
sqlite> SELECT chat_id, group_name FROM registration;
sqlite> SELECT ts, kind, ticket_id, actor_chat_id, payload_json FROM auditevent ORDER BY id DESC LIMIT 20;
```

### Backup

```sh
# Lightweight, runs while the bot is live thanks to WAL.
cp /opt/unifestbestellbot/bot.db /var/backups/bot-$(date +%FT%H%M).db
```

Suggested cron, every 15 minutes during the event:

```cron
*/15 * * * * cp /opt/unifestbestellbot/bot.db /var/backups/bot-$(date +\%FT\%H\%M).db
```

### Restore

```sh
sudo systemctl stop unifestbestellbot
cp /var/backups/bot-2026-05-22T1815.db /opt/unifestbestellbot/bot.db
sudo systemctl start unifestbestellbot
```

### Reset between events

```sh
sudo systemctl stop unifestbestellbot
rm /opt/unifestbestellbot/bot.db*
sudo systemctl start unifestbestellbot
```

## Dashboard

Open `http://<host>:8000/?group=<orga>` on a TV (e.g. `?group=Finanz`).
Click anywhere on the page once to enable fullscreen and sound on new
tickets. Without `?group=`, all groups are shown.

If the page goes red ("reconnecting…"), the bot process restarted or the
network blipped — it will reconnect on its own.

## Common fixes

| Symptom                                | Look at                                              |
| -------------------------------------- | ---------------------------------------------------- |
| Bot won't start                        | `journalctl -u unifestbestellbot -n 100`             |
| "exactly one orga_group must be default" | `config.yaml` — set `default: true` on exactly one orga group |
| Dashboard says "reconnecting…"         | `systemctl status unifestbestellbot`, then `journalctl -u unifestbestellbot -f` |
| Volunteer claims to be unregistered    | `SELECT * FROM registration WHERE chat_id=…;`        |
| Ticket reappears after close           | `SELECT * FROM auditevent WHERE ticket_id=…;` — look at the kind sequence |
| Helpers shift list errors              | Check `ENGELSYSTEM_API_KEY` and that the stall's location is mapped in `config.yaml`'s `locations:` |
| Lost developer notifications           | Confirm `DEVELOPER_CHAT_ID` in `.env` matches a chat where the user has DM-ed the bot at least once |
| Lost channel updates                   | `UPDATES_CHANNEL_ID` must be negative for groups/channels, and the bot must be a member with post permissions |

## Adding a new orga group mid-event

1. Edit `config.yaml`, add the orga group entry. Make sure exactly one
   group still has `default: true`.
2. `sudo systemctl restart unifestbestellbot`.
3. Tell the new orga member(s) to `/register` and choose the new group.

## Design decisions & accepted limitations

These are deliberate, not oversights. Documented so a future reviewer (or
the next year's maintainer) doesn't re-litigate them — revisit only if the
threat model or scale changes.

- **Orga membership is self-service.** Anyone can `/register <orga-group>`
  (e.g. `/register Finanz`) and gain that group's commands. There is no
  per-user allowlist. This fits the trust model: a local event run by ~200
  vetted volunteers where everyone aware of the bot is trusted. The
  **audit trail is the safety net** — every register, request, wip, close,
  move and message is logged both to the updates channel and to the
  `auditevent` table with the actor's chat id and a timestamp. Add real
  permission checks only if someone actually abuses it.
- **Any orga member can act on any group's ticket by id.** `/wip 47`,
  `/close 47`, `/message 47` operate on the raw id with no "is this my
  group's ticket" check (the no-arg pickers are still scoped to your own
  group). Intentional: Zentrale watches `/all` and helps across groups.
  The audit log records who did what.
- **WIP is atomically claimed; close/move are not.** Taking a ticket
  `/wip` is a single conditional UPDATE, so exactly one person can own it
  (task distribution). `/close` and `/move` are not strictly serialised —
  two simultaneous closes could both succeed and emit two notifications —
  but the outcome is idempotent (the ticket ends closed), so it's accepted.
- **The dashboard is unauthenticated** and binds `0.0.0.0:8000`. It is
  read-only and the ticket text is location+type only (no team identity),
  so the exposure is low. Fine on a trusted ops LAN; firewall the port or
  bind to loopback if the VM is reachable from an untrusted network.
- **The shift-digest dedup is in-memory.** A process restart can re-send a
  "shift starting" DM for a shift still inside the lookahead window. The
  supervisor makes restarts rare and a duplicate DM is harmless, so it is
  not persisted.
- **In-flight `/request` conversations are lost on restart** (FSM state is
  in `MemoryStorage`). Tickets and registrations survive (committed per
  action). Acceptable for a short event.

## Post-event statistics

The `auditevent` table is a complete, durable history — no extra pipeline
needed. Every ticket carries `created_at`, `who_wip` and `closed_at`, and
the audit log records each `open`/`wip`/`close`/`move`/`message` with the
actor and timestamp. Example queries:

```sql
-- Tickets per category
SELECT category, COUNT(*) FROM ticket GROUP BY category;

-- Median time-to-close (creation -> close), per handling group
SELECT group_tasked,
       COUNT(*) AS closed,
       AVG((julianday(closed_at) - julianday(created_at)) * 24 * 60) AS avg_minutes
FROM ticket WHERE status = 'closed' GROUP BY group_tasked;

-- Who took (wip'd) the most tickets
SELECT actor_chat_id, COUNT(*) FROM auditevent WHERE kind = 'wip'
GROUP BY actor_chat_id ORDER BY 2 DESC;
```

## Telegram setup checklist

- The bot must be in any channel passed via `UPDATES_CHANNEL_ID` and
  have post permissions.
- The developer must have started a private chat with the bot at least
  once (Telegram blocks bot-initiated DMs to users who haven't).
- Group-fanout (`group_msg`) skips chats that have blocked the bot and
  removes them from the registration list automatically.

## Where things live

```
src/unifestbestellbot/
├── __main__.py        # asyncio entrypoint (`uv run unifestbestellbot`)
├── settings.py        # .env loader
├── config.py          # config.yaml schema + AppConfig
├── db.py              # SQLite engine + init_db (create_all)
├── models.py          # SQLModel: Registration, Ticket, AuditEvent
├── repo.py            # data access functions
├── events.py          # in-process pub/sub for SSE
├── engelsystem.py     # shift lookup client + renderer
├── i18n.py            # every German user-facing string
├── web.py             # FastAPI: /api/tickets, /api/stream, /api/health, /
├── static/            # dashboard frontend (plain HTML + JS)
└── bot/
    ├── __init__.py    # build_bot, build_dispatcher
    ├── keyboards.py   # reply keyboards
    ├── middleware.py  # SessionMiddleware
    ├── filters.py     # IsOrga, IsDeveloper
    ├── common.py      # who(), small helpers
    ├── notify.py      # channel_msg, dev_msg, group_msg
    ├── register.py    # /start /help /register /unregister /status
    ├── request.py     # /request FSM
    ├── orga.py        # /wip /close /move /message /all /tickets /help2 /helpers
    └── admin.py       # /closeall (developer-only)
```

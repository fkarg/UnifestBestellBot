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

`Ctrl-C` exits cleanly: SSE subscribers are disconnected, the bot session
is closed, and the Engelsystem HTTP client is shut down.

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

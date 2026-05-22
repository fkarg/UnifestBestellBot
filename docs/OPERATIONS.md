# Operations

The bot's support model is "fix in production". This document tells you
where to look and what to do when something is wrong.

## Deploy

One VM, one systemd unit. The bot polls Telegram and serves the dashboard
HTTP from the same process.

```sh
# On the VM
git clone <repo> /opt/unifestbestellbot
cd /opt/unifestbestellbot

# Install uv if missing
curl -LsSf https://astral.sh/uv/install.sh | sh

uv sync
cp .env.example .env       # fill in TELEGRAM_TOKEN, DEVELOPER_CHAT_ID,
                           # UPDATES_CHANNEL_ID, ENGELSYSTEM_API_KEY
cp config.yaml.example config.yaml   # edit for the year's stalls / orga

# Install the systemd unit
sudo cp systemd/unifestbestellbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now unifestbestellbot

# Tail logs
journalctl -u unifestbestellbot -f
```

## Update

```sh
cd /opt/unifestbestellbot
git pull
uv sync
sudo systemctl restart unifestbestellbot
```

Restart drops in-flight `/request` conversations (FSM state is in-memory)
but does not lose tickets or registrations (those live in `bot.db`).

## Configuration

Two files. Restart the bot to pick up changes.

- **`.env`** — secrets and runtime knobs. See `.env.example`.
- **`config.yaml`** — the year's stall and orga structure. Schema is
  validated at startup; typos refuse to boot. See `config.yaml.example`.

### Mental model for `config.yaml`

The bot does not track teams separately from stalls. A `stalls:` entry's
`name:` is both:

- the identifier volunteers type when they `/register` ("I work at the
  Cocktailbar"), and
- the stall identifier shown in every ticket the bot creates.

`stalls[].location` is the physical spot ("Innenhof", "Außenbereich"),
shown in ticket text and used by `/helpers` to look up shifts.

`orga_groups:` are the *handler* teams (Finanz, BiMi, ...) — distinct
from the stalls that write tickets. Each category routes to one orga
group, with exactly one `default: true` as the fallback.

### Year-to-year edits

| Change                                     | Where                              |
| ------------------------------------------ | ---------------------------------- |
| New stall                                  | Add to `stalls:`                   |
| Stall closed                               | Remove from `stalls:`              |
| Stall moved to a different location        | Edit `stalls[].location`           |
| Different crew runs an existing stall      | No config change needed            |
| Stall exists but should not be advertised  | `hidden: true`                     |
| Orga teams renamed / reorganised           | `orga_groups:`                     |
| New ticket category                        | One row in `orga_groups[].categories` + one row in `FOLLOWUPS` in `bot/request.py` |
| Engelsystem location id changed            | `locations:`                       |

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

# Behaviour & Configuration Differences vs. the Legacy Bot

This document audits everything an operator or user can *observe* that
changed between the legacy python-telegram-bot v13 implementation and the
current aiogram v3 rewrite. Technical/internal changes (async, SQLModel,
SSE, ...) are described in `REWRITE_PLAN.md` and are not repeated here.

## TL;DR

- **Configuration:** ten JSON secret files replaced by one `.env` + one
  `config.yaml`. Stands are now identified by `(location, type)` rather
  than by a single string name.
- **Bot UX:** mostly identical — same commands, same German prompts, same
  reply keyboards in the `/request` flow. Notable: ticket text now reads
  `"Forum Süd [Cocktail] ..."` instead of `"Forum Süd [Cocktailbar] ..."`,
  i.e. stand *type* in brackets instead of team name.
- **Dashboard:** same UX (live tickets, sound on new), simpler URL
  (`?group=Finanz` query param instead of `#finanz|host:port`), no
  MQTT broker.
- **Several developer / debugging commands removed.** A few small
  notifications stopped being sent. See "Regressions" below; some are
  intentional, some are likely worth restoring.

---

## 1. Commands

### Removed

| Command       | What it did in legacy                                  | Replacement                                              |
| ------------- | ------------------------------------------------------ | -------------------------------------------------------- |
| `/details`    | Echoed the user's stored data (debug)                  | None. The data is in `bot.db` (`sqlite3 bot.db`).        |
| `/reset`      | Cleared the calling user's local data                  | None. `/unregister` covers the common case.              |
| `/system`     | Developer-only dump of `bot_data` (full state)         | None. Use `sqlite3 bot.db` directly.                     |
| `/resetcount` | Developer-only: reset the ticket-id counter            | None. `DELETE FROM ticket; DELETE FROM sqlite_sequence WHERE name='ticket';` |

### Kept (same name + general purpose)

`/start`, `/help`, `/register`, `/unregister`, `/status`, `/request`,
`/cancel`, `/bug`, `/feature`, `/wip`, `/close`, `/move`, `/message`,
`/all`, `/tickets`, `/help2`, `/helpers`, `/closeall`.

### Per-command behavioural differences

#### `/register`

| Aspect | Legacy | New |
| --- | --- | --- |
| Accepts a textual argument | `/register Cocktailbar` worked; case-insensitive match against the union of visible + orga + hidden groups | **Restored.** `/register <name>` resolves case-insensitively against visible + hidden stands and orga groups. |
| Inline picker contents | Visible stalls only (orga members had to type) | Same — visible stands only. Orga and hidden groups are reachable only via the textual argument. |
| Picker callback safety | Anything in the union of groups | Picker callback path explicitly rejects orga/hidden groups; only `visible_stall_names()` are accepted. Defence in depth. |
| Magic value | `/register no group` unregistered | Removed; use `/unregister` |
| Auto-`/help2` on orga register | Legacy ran `/help2` automatically after registering as orga | No automatic help; the orga reply keyboard is shown |
| Confirmation message | `"Anmelden bei Gruppe [X] erfolgreich."` followed by a separate "keyboard update" message | For textual /register: a single confirmation with the new keyboard. For the picker: the picker message is edited and a second DM updates the keyboard. |

#### `/status`

- **Legacy:** sent two separate messages — first `"Mitglied der Gruppe [X]."`, then either the ticket list or `"Deine Gruppe hat gerade keine offenen Tickets."`.
- **New:** one combined message containing membership + ticket list (or
  the no-tickets line).

#### `/request`

The state machine, prompts, and reply keyboards are identical down to
the labels. Differences:

- **In-flight FSM persistence:** legacy ConversationHandler had
  `persistent=True`, so a half-completed `/request` survived a restart.
  New uses in-memory storage — restart drops in-flight state. Restart is
  expected to be rare; volunteers re-run `/request`.
- **Defensive bot-data desync handling:** legacy `/request` had three
  fallback paths for "user thinks they're registered but `bot_data`
  disagrees" (which used to happen after pickle resets). With SQLite as
  the single source of truth, these branches are gone.

#### Ticket text format

| Scenario | Legacy | New |
| --- | --- | --- |
| Amount | `"Innenhof [Cocktailbar] hat noch ~20 Normale Becher"` | `"Innenhof [Cocktail] hat noch ~20 Normale Becher"` |
| Collect | `"Geld abholen an Stand Innenhof [Cocktailbar]"` | `"Geld abholen an Innenhof [Cocktail]"` |
| Free text | `"Innenhof [Cocktailbar] braucht Bier: '2 Fässer'"` | `"Innenhof [Cocktail] braucht Bier: '2 Fässer'"` |
| Money change | `"Innenhof [Cocktailbar] braucht Münzen"` | `"Innenhof [Cocktail] braucht Münzen"` |

The bracketed token went from *team name* to *stand type*. This was
requested explicitly — BiMi orients on `(location, type)`, never on
which crew is currently on shift.

#### `/move`

- **Legacy bug:** if the ticket was already WIP, the bot replied with
  "cannot move" *and then* logged a fake `🟠 MOVED ...` channel message
  and replied "now assigned to X". New refuses cleanly with no false
  positives.
- **Target-group notification:** legacy did **not** notify the target
  orga group when a ticket was moved to them. New sends a
  `🟠 OPEN #N: ...` message to the new tasked group so they see it.

#### `/closeall` (developer command)

- **Legacy:** closed each ticket via the normal `close_uid` path, so
  every ticket creator got a `✅ CLOSED: Euer Ticket #N wurde bearbeitet`
  DM and every orga group got their peer notification.
- **New:** same fan-out as legacy. Each closed ticket sends the channel
  log, a DM to the requesting stand's members, and a peer DM to the
  tasked orga group. The closer is attributed to a virtual group named
  "Entwickler" in the channel log so dev-driven closes are
  distinguishable from regular ones.

#### `/helpers`

Same syntax (`/helpers` uses your registered group; `/helpers <group>`
overrides), same German output. The Engelsystem base URL is now
configurable (`ENGELSYSTEM_BASE_URL`); legacy hard-coded
`https://helfen.unifest-karlsruhe.de/api/v0-beta/`. HTTP timeout went
from "none" (legacy used `requests` with no timeout) to 5s — slow
backends now fail fast.

### Unknown / unrecognised input

- **Legacy:** caught unknown commands and stray text with a fallback
  handler that replied with `"Kommando nicht erkannt oder im falschen
  Zusammenhang. Sende /help ..."` plus the user's reply keyboard.
- **New:** **Restored.** A catch-all router included last in the
  dispatcher replies with the same hint and the user's appropriate reply
  keyboard. FSM-state handlers (inside `/request`) still preempt this
  fallback, so an unrecognised reply inside the request flow still gets
  the per-state "wähle eine Option" prompt.

### Edited messages

The legacy unknown-handler explicitly logged a warning when it received
an edited message. The new fallback handler does the same — edited
messages flow through it and are warned in the journal, plus the user
gets the standard "command not recognised" reply.

---

## 2. Notifications

### Same as legacy

- Channel log on every ticket transition (open/wip/closed/moved/message).
- Channel log on /register and /unregister.
- DM to the requesting group when their ticket goes wip / closed / moved.
- DM peer notification to the orga group taking action.
- DM forward of `/message <id> <text>` to the requesting group.

### Changed or dropped

| Notification | Legacy | New |
| --- | --- | --- |
| Bot startup channel post | `"🔘 Started from <hostname>"` sent on every restart | **Restored.** Same message goes to the updates channel on startup; failure to send is logged but doesn't block boot. |
| Bot crashed status (dashboard) | MQTT `will_set` payload `{"status":"BOT_CRASHED"}` retained at the broker; the dashboard would see it | Dashboard reconnects on its own ("reconnecting…" badge); no explicit crash event |
| Bot disconnected status | MQTT `BOT_DISCONNECTED` published on graceful stop | Same — no explicit event |
| Unauthorised-DM cleanup | Legacy: when a user blocked the bot, the channel got a `dev_msg` *and* the user was removed from the group | New: removes the user silently (logged to journal only) |
| Per-ticket DM on `/closeall` | All requesters and peers got DMs | **Restored.** Each ticket sends a channel log, a CLOSED DM to the requesting stand's members, and a peer DM to the tasked orga group. Channel log attributes the closer to "Entwickler". |
| Uncaught exception → developer | Legacy `error_handler` sent the full traceback + update JSON to the developer chat as HTML | **Restored.** Dispatcher-level error handler forwards the exception summary, truncated traceback, and JSON-serialised update to the developer chat. Network errors are logged but not forwarded (avoids storm during outages). |

---

## 3. Configuration surface

### File layout

| Legacy file              | Replaced by                                                |
| ------------------------ | ---------------------------------------------------------- |
| `unifest-secrets/token.json`           | `.env` `TELEGRAM_TOKEN`                      |
| `unifest-secrets/developer.json`       | `.env` `DEVELOPER_CHAT_ID`                   |
| `unifest-secrets/channel.json`         | `.env` `UPDATES_CHANNEL_ID`                  |
| `unifest-secrets/engelsystem_api.json` | `.env` `ENGELSYSTEM_API_KEY`                 |
| `unifest-secrets/mqtt.json`            | **Removed.** Dashboard is now SSE in the same process.     |
| `unifest-secrets/groups.json`          | `config.yaml` `stalls:` (with `location` + `type`)         |
| `unifest-secrets/orga.json`            | `config.yaml` `orga_groups:`                               |
| `unifest-secrets/hidden.json`          | `config.yaml` `stalls[].hidden: true`                      |
| `unifest-secrets/mapping.json`         | Folded into `stalls[].location`                            |
| `unifest-secrets/location.json`        | `config.yaml` `locations:`                                 |
| —                                      | `.env` `DATABASE_URL` (default `sqlite:///./bot.db`)       |
| —                                      | `.env` `CONFIG_PATH`                                       |
| —                                      | `.env` `WEB_BIND` (host:port the dashboard listens on)     |
| —                                      | `.env` `LOG_LEVEL`                                         |
| —                                      | `.env` `ENGELSYSTEM_BASE_URL` (was hard-coded in legacy)   |

### Stand identity

Legacy: a stall was a free string in `groups.json` (e.g. `"Cocktailbar"`),
optionally listed in `hidden.json`, with a separate `mapping.json` saying
which location it was at. The string name was both the registration
target and the identifier shown to orga.

New: a stand is `{location, type, hidden?}`. The registration identifier
is the synthesized `"{location} {type}"` (e.g. `"Forum Süd Cocktail"`).
The display string in tickets is `"{location} [{type}]"`. There is no
team-identity field; whichever crew is on shift just `/register`s at the
stand.

### Validation

Legacy: invalid JSON or missing keys would crash mid-startup with a
plain Python traceback.

New: `config.yaml` is validated by Pydantic at startup, with named
errors for: missing `default: true` on exactly one orga group, duplicate
orga names, duplicate `(location, type)` pairs, orga names that collide
with stand identifiers, and categories routed to multiple orga groups.

### CLI / runtime flags

Legacy had a small `argparse` parser with `--nocolor` and `-v` (repeatable
for verbosity).

New has no CLI flags. Logging level comes from `LOG_LEVEL`. Coloured
output (rich) is gone — logs are plain text fit for `journalctl`.

---

## 4. Dashboard

### URL

- **Legacy:** `http://<host>:8003/#<orga>|<host>:<port>` — the hash held
  the orga filter and the MQTT broker WebSocket endpoint. Hard-coded
  fallback to `ws://162.55.42.21:8002/mqtt` in the source.
- **New:** `http://<host>:8000/?group=<Orga>` — same origin as the bot,
  query-param filter, no broker.

### Page UX

- **Legacy:** popped an `alert()` on load asking the user to click and
  enter fullscreen.
- **New:** silent on load; the first click anywhere on the page enables
  fullscreen + sound (same effect, no alert dialog).

### Filter scope

Both filter by orga group, case-insensitively. New filters server-side
(the SSE stream omits non-matching events); legacy filtered client-side.

### Tickets shown

Same: open + wip tickets, removed on close, with sound on new "open".
Layout is functionally equivalent.

### Operational

- **Legacy:** required `mosquitto` + parcel build of the static page +
  separate `python3 -m http.server`. Three processes.
- **New:** one process. `uvicorn` inside the bot serves the static page
  and the SSE stream.

---

## 5. Operations

### Persistence

- **Legacy:** `bot_persistence.cntx` (pickle). To inspect or repair you
  needed Python and the same `Ticket` class definition. A schema change
  on `Ticket` required a migration script.
- **New:** `bot.db` (SQLite). `sqlite3 bot.db` from the prod box; copy
  the file to back up; delete + restart between events.

### Logs

- **Legacy:** stdout with ANSI colour codes via `rich`. CLI flags
  selected verbosity.
- **New:** stdout (captured by systemd journal), `LOG_LEVEL` env var.

### Process management

- **Legacy:** typically `tmux` + `uv run main.py` (manual restart). The
  README documented only the bot; the dashboard ran via three additional
  commands (`mosquitto`, parcel, http.server).
- **New:** one `systemd` unit (committed at `systemd/unifestbestellbot.service`).
  `journalctl -u unifestbestellbot -f` for logs.

### Backups

- **Legacy:** `cp bot_persistence.cntx ...` works but requires the
  matching code version to read back.
- **New:** `cp bot.db ...` — the schema is human-readable, SQL.

---

## 6. Remaining differences from the legacy bot

After the targeted restorations (see commits following the audit), the
legacy behaviours kept include:

- Textual `/register <name>` argument, case-insensitive, reachable
  against visible + hidden stands and orga groups.
- Orga and hidden groups are absent from the inline picker.
- Uncaught-exception → developer DM (with traceback + update JSON).
- Fallback handler for unknown commands / stray text.
- Startup channel post (`"🔘 Started from <hostname>"`).
- `/closeall` fans out per-ticket CLOSED notifications.

What stays different:

1. **`/closeall` attribution.** Channel log line credits the closer to
   a virtual "Entwickler" group rather than the developer's own orga
   group (which they may not have). Cosmetic.

2. **No `/details`, `/reset`, `/system`, `/resetcount`.** All four were
   debugging tools. The DB-as-source-of-truth model makes them
   redundant: `sqlite3 bot.db` covers `/system` and `/details`;
   `/closeall` covers `/resetcount`'s practical use. `/reset` (user
   wipe of own data) has no replacement, but `/unregister` covers the
   common case.

3. **Conversation FSM does not persist across restarts.** Volunteers
   mid-`/request` during a bot restart have to start over. Accepted
   trade-off.

4. **Per-stand identity model** (`(location, type)` instead of a single
   string name). See section 3.

5. **Ticket text format** — bracketed token is the stand TYPE, not the
   team name. See section 1.

6. **`/move` correctness fixes** — no false success on WIP tickets, and
   the target orga group is notified. See section 1.

These are intentional; anything else is a bug.

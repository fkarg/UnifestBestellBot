# UnifestBestellBot — Implementation Proposal

Companion to [`REWRITE_PLAN.md`](./REWRITE_PLAN.md). That document is the
*what and why*. This document is the *how*: concrete shapes, signatures,
and code sketches a contributor (or future-you) can implement against
without inventing details.

Conventions used here:
- Code blocks show the intended shape, not necessarily the final
  implementation. Imports are abbreviated.
- Where current code is referenced, the path uses the legacy layout
  (`src/...`); new code lives under `src/unifestbestellbot/...`.

---

## 1. Configuration

Two files, two layers. Secrets are environment-managed; structural
config is a versionable YAML file.

### 1.1 `.env`

```dotenv
# .env.example — committed; .env is gitignored
TELEGRAM_TOKEN=123456:ABC-DEF...
DEVELOPER_CHAT_ID=12345678
UPDATES_CHANNEL_ID=-1001234567890
ENGELSYSTEM_API_KEY=...
ENGELSYSTEM_BASE_URL=https://helfen.unifest-karlsruhe.de/api/v0-beta/

DATABASE_URL=sqlite:///./bot.db
CONFIG_PATH=./config.yaml
WEB_BIND=0.0.0.0:8000
LOG_LEVEL=INFO
```

### 1.2 `settings.py`

```python
from pydantic import HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_token: str
    developer_chat_id: int
    updates_channel_id: int
    engelsystem_api_key: str
    engelsystem_base_url: HttpUrl

    database_url: str = "sqlite:///./bot.db"
    config_path: str = "./config.yaml"
    web_bind: str = "0.0.0.0:8000"
    log_level: str = "INFO"

settings = Settings()  # raises at import time if anything is missing
```

### 1.3 `config.yaml`

The whole stall/orga/routing structure for one event. Edited by the
maintainer between events and committed.

A `stalls:` entry is a **group** with an explicit `name` (what
volunteers /register as), plus a `location` and `type`. Multiple groups
can share the same `(location, type)`. The group name is the
registration identifier; ticket text to orga always renders
`"{location} [{type}]"`, so handler teams orient on the stand and never
see crew identity.

```yaml
# config.yaml
stalls:
  - name: "Cocktailbar 1"
    location: "Forum Süd"
    type: "Cocktail"
  - name: "Cocktailbar 2"
    location: "Forum Süd"
    type: "Cocktail"
  - name: "Biertheke Süd"
    location: "Forum Süd"
    type: "Bier"
  - name: "Biertheke DJ"
    location: "DJ"
    type: "Bier"
  - name: "Tickets"
    location: "Eingang"
    type: "Tickets"
    hidden: true             # not offered in /register picker

orga_groups:
  - name: "Finanz"
    categories: ["Geld"]
  - name: "BiMi"
    categories: ["Bier", "Cocktail", "Becher"]
  - name: "Helfen"
    categories: ["Helfer"]
  - name: "Zentrale"
    categories: ["Sonstiges"]
    default: true            # fallback for any category not matched above

# Optional. Used only by the Engelsystem helper-shift integration.
locations:
  "Forum Süd": 12
  "DJ": 15
  "Eingang": 3
```

Tickets render the requesting group as `"{location} [{type}]"`, e.g.
`"Forum Süd [Cocktail] hat noch ~20 Normale Becher"`. The group's
*name* is stored on the `Ticket.group_requesting` column (used to fan
out CLOSED notifications back to the requesting crew and to filter
`/status`), but it does not appear in the ticket text orga sees.

### 1.4 `config.py`

```python
from pathlib import Path
from typing import Self
import yaml
from pydantic import BaseModel, model_validator

class Stall(BaseModel):
    name: str
    location: str
    hidden: bool = False

class OrgaGroup(BaseModel):
    name: str
    categories: list[str]
    default: bool = False

class AppConfig(BaseModel):
    stalls: list[Stall]
    orga_groups: list[OrgaGroup]
    locations: dict[str, int] = {}

    @model_validator(mode="after")
    def _exactly_one_default(self) -> Self:
        defaults = [g for g in self.orga_groups if g.default]
        if len(defaults) != 1:
            raise ValueError("exactly one orga_group must be marked default")
        return self

    # Derived lookups — populated lazily, kept off-model to keep validation clean.
    def route_category(self, category: str) -> str:
        for g in self.orga_groups:
            if category in g.categories:
                return g.name
        return next(g.name for g in self.orga_groups if g.default)

    def stall_names(self, *, include_hidden: bool = False) -> list[str]:
        return [s.name for s in self.stalls if include_hidden or not s.hidden]

    def stall(self, name: str) -> Stall | None:
        return next((s for s in self.stalls if s.name == name), None)

    def orga_names(self) -> list[str]:
        return [g.name for g in self.orga_groups]

def load_config(path: str | Path) -> AppConfig:
    return AppConfig.model_validate(yaml.safe_load(Path(path).read_text()))
```

Notes:
- Validation at startup catches typos in `categories:` or duplicate
  defaults before the bot starts taking traffic.
- The current `src/tickets.py:create_ticket` hard-codes the category →
  orga mapping. That logic moves into `AppConfig.route_category`. To
  add a new category, edit `config.yaml` only.

---

## 2. Database & models

### 2.1 `db.py`

```python
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import event

from .settings import settings

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)

@event.listens_for(engine, "connect")
def _enable_sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()

def init_db() -> None:
    """Create tables. Idempotent. Called once at startup."""
    SQLModel.metadata.create_all(engine)

def session() -> Session:
    return Session(engine)
```

### 2.2 `models.py`

```python
from datetime import datetime
from enum import StrEnum
from sqlmodel import SQLModel, Field

class TicketStatus(StrEnum):
    OPEN = "open"
    WIP = "wip"
    CLOSED = "closed"

class Registration(SQLModel, table=True):
    chat_id: int = Field(primary_key=True)
    group_name: str = Field(index=True)
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    registered_at: datetime = Field(default_factory=datetime.utcnow)

class Ticket(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    status: TicketStatus = Field(default=TicketStatus.OPEN, index=True)
    category: str
    text: str
    group_requesting: str
    group_tasked: str = Field(index=True)
    who_wip: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: datetime | None = None

    def display(self) -> str:
        emoji = {"open": "🟠 OPEN", "wip": "🟢 WIP", "closed": "✅ CLOSED"}[self.status]
        return f"{emoji} #{self.id}: {self.text}"

class AuditEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow)
    kind: str       # 'open' | 'wip' | 'close' | 'move' | 'register' | 'unregister' | 'message'
    ticket_id: int | None = Field(default=None, foreign_key="ticket.id")
    actor_chat_id: int | None = None
    payload_json: str | None = None
```

Why `StrEnum` for `TicketStatus`: SQLModel stores enums by their string
value, so the DB column is human-readable in `sqlite3` CLI. The legacy
code stored them as Python repr strings — opaque.

### 2.3 `repo.py`

Pure functions, take a `Session`. No global state. Audit events written
inline with the action they describe so the log is never out of sync.

```python
from sqlmodel import Session, select
from .models import Ticket, TicketStatus, Registration, AuditEvent

# --- Registration ----------------------------------------------------------

def upsert_registration(s: Session, reg: Registration) -> None:
    existing = s.get(Registration, reg.chat_id)
    if existing:
        existing.group_name = reg.group_name
        existing.username = reg.username
        existing.first_name = reg.first_name
        existing.last_name = reg.last_name
    else:
        s.add(reg)
    s.add(AuditEvent(kind="register", actor_chat_id=reg.chat_id,
                     payload_json=reg.model_dump_json(include={"group_name"})))
    s.commit()

def unregister(s: Session, chat_id: int) -> str | None:
    """Returns the group_name the user was in, or None."""
    reg = s.get(Registration, chat_id)
    if not reg:
        return None
    group = reg.group_name
    s.delete(reg)
    s.add(AuditEvent(kind="unregister", actor_chat_id=chat_id,
                     payload_json=f'{{"group_name":"{group}"}}'))
    s.commit()
    return group

def group_members(s: Session, group_name: str) -> list[int]:
    return list(s.exec(
        select(Registration.chat_id).where(Registration.group_name == group_name)
    ))

def registration_for(s: Session, chat_id: int) -> Registration | None:
    return s.get(Registration, chat_id)

# --- Tickets ---------------------------------------------------------------

def create_ticket(s: Session, *, category: str, text: str,
                  group_requesting: str, group_tasked: str,
                  actor_chat_id: int) -> Ticket:
    t = Ticket(category=category, text=text,
               group_requesting=group_requesting, group_tasked=group_tasked)
    s.add(t)
    s.flush()  # get t.id
    s.add(AuditEvent(kind="open", ticket_id=t.id, actor_chat_id=actor_chat_id))
    s.commit()
    return t

def set_wip(s: Session, ticket_id: int, *, who: str, actor_chat_id: int) -> Ticket:
    t = s.get(Ticket, ticket_id)
    if not t or t.status != TicketStatus.OPEN:
        raise ValueError(f"ticket {ticket_id} is not open")
    t.status = TicketStatus.WIP
    t.who_wip = who
    s.add(AuditEvent(kind="wip", ticket_id=t.id, actor_chat_id=actor_chat_id))
    s.commit()
    return t

def close_ticket(s: Session, ticket_id: int, *, actor_chat_id: int) -> Ticket:
    t = s.get(Ticket, ticket_id)
    if not t or t.status == TicketStatus.CLOSED:
        raise ValueError(f"ticket {ticket_id} already closed or missing")
    t.status = TicketStatus.CLOSED
    t.closed_at = datetime.utcnow()
    s.add(AuditEvent(kind="close", ticket_id=t.id, actor_chat_id=actor_chat_id))
    s.commit()
    return t

def move_ticket(s: Session, ticket_id: int, *, new_group: str,
                actor_chat_id: int) -> Ticket:
    t = s.get(Ticket, ticket_id)
    if not t or t.status != TicketStatus.OPEN:
        raise ValueError(f"ticket {ticket_id} is not open")
    t.group_tasked = new_group
    s.add(AuditEvent(kind="move", ticket_id=t.id, actor_chat_id=actor_chat_id,
                     payload_json=f'{{"new_group":"{new_group}"}}'))
    s.commit()
    return t

def active_tickets(s: Session, *, group_tasked: str | None = None) -> list[Ticket]:
    stmt = select(Ticket).where(Ticket.status != TicketStatus.CLOSED)
    if group_tasked:
        stmt = stmt.where(Ticket.group_tasked == group_tasked)
    return list(s.exec(stmt.order_by(Ticket.id)))

def tickets_by_requesting_group(s: Session, group: str) -> list[Ticket]:
    return list(s.exec(
        select(Ticket)
        .where(Ticket.group_requesting == group)
        .where(Ticket.status != TicketStatus.CLOSED)
        .order_by(Ticket.id)
    ))
```

Important: callers don't manage sessions; they get one per handler via
the dependency in §3.4.

---

## 3. Bot (aiogram v3)

### 3.1 Top-level wiring — `bot/__init__.py`

```python
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from ..settings import settings
from . import register, request, orga, admin

def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_routers(
        register.router,
        request.router,
        orga.router,
        admin.router,
    )
    return dp

def build_bot() -> Bot:
    return Bot(
        token=settings.telegram_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
```

### 3.2 Routers and command organization

Each flow file owns its handlers and registers them on its own `Router`.
This replaces the centralized `main.py` registration block.

```python
# bot/register.py
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

router = Router(name="register")

@router.message(Command("register"))
async def cmd_register(msg: Message, config: AppConfig, db_session: Session) -> None:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"reg:{name}")]
        for name in config.stall_names()
    ] + [[InlineKeyboardButton(text="❌ Abbrechen", callback_data="reg:_cancel")]])
    await msg.answer("Mögliche Gruppen:", reply_markup=kb)

@router.callback_query(F.data.startswith("reg:"))
async def on_register_choice(cb: CallbackQuery, config: AppConfig, db_session: Session) -> None:
    choice = cb.data.removeprefix("reg:")
    if choice == "_cancel":
        await cb.message.edit_text("Gruppenauswahl abgebrochen.")
        await cb.answer()
        return
    if not config.stall(choice) and choice not in config.orga_names():
        await cb.answer("Unbekannte Gruppe.", show_alert=True)
        return
    repo.upsert_registration(db_session, Registration(
        chat_id=cb.from_user.id,
        group_name=choice,
        username=cb.from_user.username,
        first_name=cb.from_user.first_name,
        last_name=cb.from_user.last_name,
    ))
    await cb.message.edit_text(f"Anmelden bei Gruppe [{choice}] erfolgreich.")
    await cb.answer()
```

### 3.3 Keyboards: when to use which

The `/request` conversation works well in the field with reply keyboards
+ free-text fallback (suggested options always visible above the input,
but the user can type an arbitrary value when needed). That UX stays.
Inline keyboards are used where the choices are *data the bot just
fetched* — a list of existing tickets, the list of stalls during
registration — and where stable `callback_data` matters.

Rule of thumb:

| Use case                                       | Keyboard kind                |
| ---------------------------------------------- | ---------------------------- |
| Main / orga / initial command menus            | Reply (persistent)           |
| `/request` flow steps (category, money, cups…) | Reply + free-text fallback   |
| Free-text-only steps (Sonstiges, Helfer text)  | `ReplyKeyboardRemove`        |
| `/register` group picker                       | Inline                       |
| `/wip` / `/close` / `/move` ticket picker      | Inline (callback = ticket id)|

aiogram's filters cover both cleanly:

```python
@router.message(RequestFSM.category, F.text.in_(CATEGORY_LABELS))
async def pick_category(msg, state, config):
    ...

@router.callback_query(F.data.startswith("close:"))
async def on_close_choice(cb, state, db_session, config):
    ...
```

`F.text == "Geld"` is just as testable as a `callback_data` match —
the previous code's fragility came from regex handlers scattered across
files, not from the reply-keyboard affordance itself.

### 3.4 FSM for `/request` — `bot/request.py`

States mirror the current flow: `category`, `money`, `money_change`,
`cups`, `amount`, `free`, `helper`. Each state has one handler for the
known buttons and a fallback for free text or unrecognized input.

```python
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

class RequestFSM(StatesGroup):
    category = State()
    money = State()
    money_change = State()
    cups = State()
    amount = State()
    free = State()
    helper = State()

CATEGORY_LABELS = {"Geld", "Becher", "Bier", "Cocktail", "Sonstiges", "Helfer"}

CATEGORY_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Becher"), KeyboardButton(text="Geld")],
        [KeyboardButton(text="Bier"), KeyboardButton(text="Cocktail")],
        [KeyboardButton(text="Helfer"), KeyboardButton(text="Sonstiges")],
        [KeyboardButton(text="/cancel")],
    ],
    resize_keyboard=True,
)

MONEY_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Geld Abholen"), KeyboardButton(text="Wechselgeld")],
        [KeyboardButton(text="Freitext"), KeyboardButton(text="/cancel")],
    ],
    resize_keyboard=True,
)

AMOUNT_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="0"), KeyboardButton(text="Freitext"), KeyboardButton(text="/cancel")],
        [KeyboardButton(text="~10"), KeyboardButton(text="~20"), KeyboardButton(text="~50")],
    ],
    resize_keyboard=True,
)
# … etc for CUPS_KB, MONEY_CHANGE_KB, HELPER_KB

@router.message(Command("request"))
async def cmd_request(msg, state, db_session, config):
    reg = repo.registration_for(db_session, msg.from_user.id)
    if not reg:
        await msg.answer("Bitte /register zuerst.", reply_markup=keyboards.initial())
        return
    await state.set_state(RequestFSM.category)
    await state.update_data(group=reg.group_name)
    await msg.answer("Kategorie?", reply_markup=CATEGORY_KB)

@router.message(RequestFSM.category, F.text.in_(CATEGORY_LABELS))
async def pick_category(msg, state, config):
    category = msg.text
    await state.update_data(category=category)
    # Table-driven branch. Adding a category means adding one row.
    next_state, keyboard, prompt = FOLLOWUPS[category]
    await state.set_state(next_state)
    await msg.answer(prompt, reply_markup=keyboard)

@router.message(RequestFSM.category)
async def category_unrecognized(msg, state):
    await msg.answer("Bitte wähle eine Option oder /cancel.", reply_markup=CATEGORY_KB)
```

Free-text branches use `ReplyKeyboardRemove()` so the input field is
unobstructed, and accept any text:

```python
@router.message(RequestFSM.free)
async def take_free_text(msg, state, db_session, config, events):
    await state.update_data(detail=msg.text)
    await _finalize_ticket(msg, state, db_session, config, events)
```

The amount step accepts either the suggested buttons (`~10`, `~20`,
`~50`, `0`) or arbitrary text the user types:

```python
@router.message(RequestFSM.amount, F.text == "Freitext")
async def amount_freetext(msg, state):
    await state.set_state(RequestFSM.free)
    await msg.answer("Was braucht ihr genau?", reply_markup=ReplyKeyboardRemove())

@router.message(RequestFSM.amount)
async def take_amount(msg, state, db_session, config, events):
    await state.update_data(amount=msg.text)
    await _finalize_ticket(msg, state, db_session, config, events)
```

The `FOLLOWUPS` table is the only place that knows the per-category
sub-flow. Adding `"Eis"` to `config.yaml` plus one entry in this table is
the entire change.

Final step (any branch that resolves to a ticket):

```python
async def _finalize_ticket(msg, state: FSMContext, db_session: Session,
                           config: AppConfig, events: EventBus) -> None:
    data = await state.get_data()
    group_tasked = config.route_category(data["category"])
    stall = config.stall(data["group"])
    location = stall.location if stall else data["group"]
    text = _render_text(data, location)

    ticket = repo.create_ticket(db_session,
        category=data["category"],
        text=text,
        group_requesting=data["group"],
        group_tasked=group_tasked,
        actor_chat_id=msg.from_user.id,
    )
    await state.clear()
    await events.publish_ticket(ticket)
    await _broadcast_to_orga(msg.bot, db_session, group_tasked, ticket)
    await msg.answer(f"Ticket #{ticket.id} erstellt.",
                     reply_markup=keyboards.for_registration(data["group"], config))
```

### 3.5 Ticket pickers (inline)

For `/wip`, `/close`, `/move` without an explicit ticket id argument,
show the candidate tickets as an inline keyboard — one button per ticket
with the ticket id baked into `callback_data`:

```python
@router.message(Command("close"), IsOrga())
async def cmd_close(msg, db_session):
    if (parts := msg.text.split()) and len(parts) > 1 and parts[1].isdigit():
        await _close_by_id(msg, db_session, int(parts[1]))
        return
    reg = repo.registration_for(db_session, msg.from_user.id)
    candidates = [t for t in repo.active_tickets(db_session, group_tasked=reg.group_name)
                  if t.status == TicketStatus.WIP]
    if not candidates:
        await msg.answer(f"Keine WIP Tickets für [{reg.group_name}].")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.display(), callback_data=f"close:{t.id}")]
        for t in candidates
    ] + [[InlineKeyboardButton(text="❌ Abbrechen", callback_data="close:_cancel")]])
    await msg.answer("WIP Tickets:", reply_markup=kb)
```

### 3.6 Cross-cutting dependencies

aiogram supports per-update dependency injection via a middleware-like
mechanism (`workflow_data` and parameters declared on the handler). Wire
the session and config so handlers can declare them as parameters:

```python
# bot/middleware.py
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from sqlmodel import Session
from ..db import engine

class SessionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data: dict[str, Any]):
        with Session(engine) as s:
            data["db_session"] = s
            return await handler(event, data)
```

And at startup:

```python
dp = build_dispatcher()
dp.message.middleware(SessionMiddleware())
dp.callback_query.middleware(SessionMiddleware())
dp.workflow_data.update(config=config, events=events)
```

### 3.7 Permission decorators

Replace `@developer_command` / `@orga_command` (which read state via
`context.user_data`) with aiogram filters:

```python
# bot/filters.py
from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

class IsOrga(BaseFilter):
    async def __call__(self, event: TelegramObject, db_session, config) -> bool:
        chat_id = event.from_user.id
        reg = repo.registration_for(db_session, chat_id)
        return bool(reg) and reg.group_name in config.orga_names()

class IsDeveloper(BaseFilter):
    async def __call__(self, event: TelegramObject) -> bool:
        return event.from_user.id == settings.developer_chat_id
```

Used as:

```python
@router.message(Command("close"), IsOrga())
async def cmd_close(msg: Message, ...):
    ...
```

This makes permissions part of the route signature, not a runtime guard
inside the handler — and they're testable in isolation.

---

## 4. Dashboard (FastAPI + SSE)

### 4.1 In-process event bus — `events.py`

```python
import asyncio
from collections.abc import AsyncIterator
from .models import Ticket

class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()

    async def publish_ticket(self, ticket: Ticket) -> None:
        payload = ticket.model_dump_json()
        for q in list(self._subscribers):
            q.put_nowait(payload)

    async def subscribe(self) -> AsyncIterator[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=128)
        self._subscribers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.discard(q)
```

One process, one bus, no broker. If a subscriber's queue is full
(`put_nowait` raises), drop it — that browser will re-snapshot on
reconnect.

### 4.2 FastAPI app — `web.py`

```python
from fastapi import FastAPI, Depends, Query
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .db import session
from .repo import active_tickets
from .events import EventBus

STATIC_DIR = Path(__file__).parent / "static"

def build_web_app(events: EventBus) -> FastAPI:
    app = FastAPI()

    @app.get("/api/tickets")
    def tickets(group: str | None = Query(None)):
        with session() as s:
            return [t.model_dump() for t in active_tickets(s, group_tasked=group)]

    @app.get("/api/stream")
    async def stream(group: str | None = Query(None)):
        async def gen():
            async for payload in events.subscribe():
                # filter on the server side so browsers can't see other groups' tickets
                if group is None or f'"group_tasked":"{group}"' in payload:
                    yield f"event: ticket\ndata: {payload}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
```

### 4.3 Static page — `static/index.html` + `static/main.js`

```html
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>UnifestBestellBot</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div id="tickets"></div>
  <audio id="ding" src="sound_a.mp3"></audio>
  <script src="main.js" type="module"></script>
</body>
</html>
```

```js
// main.js
const params = new URLSearchParams(location.search);
const group = params.get("group");
const qs = group ? `?group=${encodeURIComponent(group)}` : "";

const container = document.getElementById("tickets");
const ding = document.getElementById("ding");
let allowSound = false;
document.body.addEventListener("click", () => {
  document.documentElement.requestFullscreen?.();
  allowSound = true;
}, { once: true });

function render(ticket) {
  let el = document.getElementById(`t-${ticket.id}`);
  if (ticket.status === "closed") { el?.remove(); return; }
  if (!el) {
    el = document.createElement("div");
    el.id = `t-${ticket.id}`;
    container.prepend(el);
    if (allowSound) ding.play().catch(() => {});
  }
  el.className = `ticket ${ticket.status}`;
  el.innerHTML = `<p class="text">${ticket.text}</p>
                  <p class="meta">${ticket.who_wip ?? ""} #${ticket.id}</p>`;
}

async function snapshot() {
  const r = await fetch(`/api/tickets${qs}`);
  (await r.json()).forEach(render);
}

function subscribe() {
  const es = new EventSource(`/api/stream${qs}`);
  es.addEventListener("ticket", (e) => render(JSON.parse(e.data)));
  es.addEventListener("error", () => setTimeout(snapshot, 1000));
}

snapshot().then(subscribe);
```

~50 lines of JS, no build step, edit-and-reload.

---

## 5. Process model — `__main__.py`

aiogram polling + uvicorn run in the same event loop:

```python
import asyncio, logging, uvicorn
from .settings import settings
from .config import load_config
from .db import init_db
from .events import EventBus
from .bot import build_bot, build_dispatcher

async def amain() -> None:
    logging.basicConfig(level=settings.log_level)
    config = load_config(settings.config_path)
    init_db()

    events = EventBus()
    bot = build_bot()
    dp = build_dispatcher()
    dp.workflow_data.update(config=config, events=events)

    from .web import build_web_app
    web = build_web_app(events)
    host, port = settings.web_bind.rsplit(":", 1)
    web_server = uvicorn.Server(uvicorn.Config(web, host=host, port=int(port), log_level=settings.log_level.lower()))

    await asyncio.gather(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        web_server.serve(),
    )

if __name__ == "__main__":
    asyncio.run(amain())
```

Crashes propagate to `asyncio.gather` and kill the process; systemd
restarts it. That's the entire supervision strategy.

---

## 6. Engelsystem integration — `engelsystem.py`

```python
from datetime import datetime, timezone, timedelta
import httpx
from .settings import settings
from .config import AppConfig

class EngelsystemClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 5.0):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Accept": "application/json", "x-api-key": api_key},
            timeout=timeout,
        )

    async def shifts_at(self, location_id: int) -> list[dict]:
        r = await self._client.get(f"locations/{location_id}/shifts")
        r.raise_for_status()
        return r.json()["data"]

def summarize_shifts(shifts: list[dict], *, now: datetime,
                     next_window: timedelta = timedelta(minutes=20)) -> str:
    """Pure function. Easy to unit test against fixtures."""
    ...
```

`summarize_shifts` is pure: no I/O, takes `now` as a parameter. The
fixture-based test feeds it `engelsystem_shifts.json` and a known `now`.

---

## 7. Tests

### 7.1 `conftest.py`

```python
import pytest
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool

@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng

@pytest.fixture
def s(engine):
    with Session(engine) as session:
        yield session

@pytest.fixture
def config():
    from unifestbestellbot.config import AppConfig
    return AppConfig.model_validate({
        "stalls": [
            {"name": "Cocktailbar", "location": "Innenhof"},
            {"name": "Tickets", "location": "Eingang", "hidden": True},
        ],
        "orga_groups": [
            {"name": "Finanz", "categories": ["Geld"]},
            {"name": "BiMi", "categories": ["Bier", "Becher"]},
            {"name": "Zentrale", "categories": ["Sonstiges"], "default": True},
        ],
    })
```

### 7.2 Repo tests — `test_repo.py`

```python
import pytest
from unifestbestellbot import repo
from unifestbestellbot.models import Registration, Ticket, TicketStatus

def test_create_and_close_ticket(s):
    t = repo.create_ticket(s, category="Geld", text="Wechselgeld Münzen",
                           group_requesting="Cocktailbar", group_tasked="Finanz",
                           actor_chat_id=42)
    assert t.id is not None and t.status == TicketStatus.OPEN

    repo.set_wip(s, t.id, who="Alice", actor_chat_id=99)
    repo.close_ticket(s, t.id, actor_chat_id=99)

    assert s.get(Ticket, t.id).status == TicketStatus.CLOSED

def test_cannot_wip_closed_ticket(s):
    t = repo.create_ticket(s, category="Geld", text="x",
                           group_requesting="A", group_tasked="B", actor_chat_id=1)
    repo.close_ticket(s, t.id, actor_chat_id=1)
    with pytest.raises(ValueError):
        repo.set_wip(s, t.id, who="x", actor_chat_id=1)
```

### 7.3 Config tests — `test_config.py`

```python
def test_route_category_matches_explicit_orga(config):
    assert config.route_category("Geld") == "Finanz"
    assert config.route_category("Becher") == "BiMi"

def test_route_category_falls_back_to_default(config):
    assert config.route_category("Eis") == "Zentrale"

def test_exactly_one_default_required():
    from unifestbestellbot.config import AppConfig
    with pytest.raises(ValueError):
        AppConfig.model_validate({
            "stalls": [],
            "orga_groups": [
                {"name": "A", "categories": ["x"], "default": True},
                {"name": "B", "categories": ["y"], "default": True},
            ],
        })
```

### 7.4 Handler tests — `test_request_flow.py`

aiogram handlers are async functions; we can call them directly with
`MagicMock`s for `Message`/`CallbackQuery` and a real `FSMContext` over
`MemoryStorage`. End-to-end shape:

```python
@pytest.mark.asyncio
async def test_request_geld_wechselgeld_muenzen_lands_in_finanz(s, config):
    # Pre-register the user.
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar"))

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key=StorageKey(bot_id=1, chat_id=1, user_id=1))

    await cmd_request(_fake_msg(1), state, db_session=s, config=config)
    await pick_category(_fake_cb(1, "req:cat:Geld"), state, config)
    await pick_money_kind(_fake_cb(1, "req:money:Wechselgeld"), state, config)
    await pick_change(_fake_cb(1, "req:change:Münzen"), state, s, config, events=_noop_events())

    tickets = repo.active_tickets(s, group_tasked="Finanz")
    assert len(tickets) == 1
    assert "Münzen" in tickets[0].text
```

### 7.5 Permission tests — `test_permissions.py`

```python
@pytest.mark.asyncio
async def test_orga_filter_rejects_non_orga(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar"))
    assert await IsOrga()(_fake_event(1), db_session=s, config=config) is False

@pytest.mark.asyncio
async def test_orga_filter_accepts_orga(s, config):
    repo.upsert_registration(s, Registration(chat_id=2, group_name="Finanz"))
    assert await IsOrga()(_fake_event(2), db_session=s, config=config) is True
```

### 7.6 SSE test — `test_web.py`

```python
@pytest.mark.asyncio
async def test_sse_broadcasts_new_ticket(engine):
    events = EventBus()
    app = build_web_app(events)

    async with httpx.AsyncClient(app=app, base_url="http://t") as client:
        async with client.stream("GET", "/api/stream") as resp:
            with Session(engine) as s:
                t = repo.create_ticket(s, category="Geld", text="x",
                                       group_requesting="A", group_tasked="B",
                                       actor_chat_id=1)
            await events.publish_ticket(t)
            line = await anext(resp.aiter_lines())
            assert line.startswith("event: ticket")
```

---

## 8. Build sequence

Each step is a self-contained PR that lands green. Tests written in the
same step as the code they cover.

1. **Scaffold.** `pyproject.toml` (uv), package skeleton, `.env.example`,
   `config.yaml.example`, CI workflow (`uv run pytest`).
2. **Config layer.** `settings.py`, `config.py`, tests for routing /
   default validation.
3. **DB layer.** `db.py`, `models.py`, `repo.py`, repo tests.
4. **Bot skeleton.** `bot/__init__.py`, `bot/register.py`, session
   middleware, `IsOrga`/`IsDeveloper` filters and their tests.
5. **Request flow.** `bot/request.py` with FSM, follow-up table, finalize
   helper, end-to-end test per category.
6. **Orga flow.** `bot/orga.py` (`/wip`, `/close`, `/move`, `/message`,
   `/all`, `/tickets`), permission tests, transition tests.
7. **Engelsystem.** `engelsystem.py`, fixture, `summarize_shifts` test.
8. **Dashboard.** `events.py`, `web.py`, `static/*`, SSE test.
9. **Process glue.** `__main__.py`, manual smoke against the dev bot
   token. `docs/OPERATIONS.md` covering deploy, backup (cp bot.db),
   restore, common fixes.
10. **Cutover.** Run new bot on the debug token alongside the old one,
    verify on a staging chat, swap tokens, delete legacy code.

---

## 9. Risks and explicit non-handling

- **A handler that raises mid-FSM leaves a user stuck in a state.**
  Acceptable: `/cancel` resets the state, and aiogram clears state on
  process restart since storage is `MemoryStorage`. Documented in user
  help text.
- **The bot drops Telegram updates while restarting.** Long polling
  resumes from the last `update_id`, so missed updates are picked up on
  reconnect (within Telegram's ~24h retention). No queue, no DLQ.
- **`config.yaml` typos take down the bot at startup.** Intentional. A
  bad config should fail loudly before traffic, not silently mis-route
  tickets.
- **SSE subscribers that fall behind get dropped.** They re-snapshot on
  reconnect via the browser's native EventSource retry. No backpressure.
- **DB file corruption.** Backup with `cp bot.db bot.db.bak` periodically
  during the event (cron, every 15 min). Restore is a file copy.

---

## 10. File-by-file size targets

Sanity check: this whole rewrite should be smaller than what it replaces.

| File                  | Target LOC |
| --------------------- | ---------- |
| `settings.py`         | ~20        |
| `config.py`           | ~80        |
| `db.py`               | ~30        |
| `models.py`           | ~50        |
| `repo.py`             | ~150       |
| `events.py`           | ~30        |
| `bot/__init__.py`     | ~30        |
| `bot/register.py`     | ~80        |
| `bot/request.py`     | ~200       |
| `bot/orga.py`         | ~200       |
| `bot/admin.py`        | ~50        |
| `bot/filters.py`      | ~30        |
| `bot/middleware.py`   | ~20        |
| `engelsystem.py`      | ~80        |
| `web.py`              | ~60        |
| `i18n.py`             | ~80        |
| `__main__.py`         | ~40        |
| `static/main.js`      | ~50        |
| `static/index.html`   | ~20        |
| `static/style.css`    | ~50        |
| **Total**             | **~1350**  |
| Tests (rough)         | **~800**   |

For comparison, the current `src/` + `main.py` is ~1100 LOC of
production code, no tests.

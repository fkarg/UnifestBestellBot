# Design: `/close` auf eigene WIP-Tickets begrenzen (+ `who_wip_chat_id`-Fundament)

Datum: 2026-06-30
Branch: unifest2026
Status: Spec, vor Implementierung

## Problem

Während des Events laufen oft so viele WIP-Tickets gleichzeitig, dass man den
Überblick verliert. Der `/close`-Picker (ohne Argument) listet aktuell **alle**
WIP-Tickets der Gruppe — diese Liste läuft über. Man will primär *seine eigenen*
Tickets schließen.

## Scope dieser Runde (Commit 1)

Nur zwei Dinge:

1. **`who_wip_chat_id`** als additives Fundament am Ticket — stabile, eindeutige
   Per-User-Identität (Telegram `chat_id`) für „wer bearbeitet dieses Ticket".
2. **`/close`** begrenzt den Picker zunächst auf die eigenen WIP-Tickets, mit
   Toggle auf die volle Gruppenliste.

**Bewusst NICHT in dieser Runde** (eigene Folge-Commits, separat gespect):
- `/self` (eigene Perspektive + Statistiken über vergangene Tickets)
- Anzeigename-Override
- Notification-Granularität

## Warum `who_wip_chat_id` (statt Namen-String-Matching)

`ticket.who_wip` ist heute ein **Anzeige-Name-String** (`caller.display()`, z.B.
`"Felix Karg <@felix>"`). Daran „meine Tickets" zu matchen ist fragil: ändert
jemand seinen Telegram-Namen, matchen Alttickets nicht mehr.

`chat_id` ist dagegen ein stabiler, eindeutiger Per-User-Key (bereits PRIMARY KEY
von `registration`). Wir hängen deshalb **additiv** eine neue Spalte
`ticket.who_wip_chat_id INTEGER` an:

- Bestehende Spalte `who_wip` (String) bleibt unverändert → **keine Python-Parität
  gebrochen**, Anzeige/Digests laufen weiter über den String.
- Neues Matching/Filtern läuft über `who_wip_chat_id`.
- `/self` (nächste Runde) baut direkt auf diesem Feld auf → keine Doppelarbeit.

> **Stack-Hinweis:** Implementiert in der **Python**-Version unter
> `src/unifestbestellbot/` (aiogram v3 + SQLModel). Die `rust/`-Variante wird
> ignoriert.

## Architektur / Änderungen

### Schema (`models.py` + `db.py`)
- `Ticket` bekommt Feld
  `who_wip_chat_id: int | None = Field(default=None, index=True)`.
- **Migration:** Die DB wird normal zwischen Events gelöscht, also baut
  `SQLModel.metadata.create_all()` das Schema beim Eventstart frisch inkl. der
  neuen Spalte. **Für Mid-Event-Deploys** (DB-File bleibt erhalten) reicht
  `create_all()` nicht — es legt keine Spalten in bestehenden Tabellen an.
  Deshalb additiv und idempotent in `init_db()`: `_ensure_ticket_columns()`
  prüft via `PRAGMA table_info(ticket)` und führt bei Bedarf
  `ALTER TABLE ticket ADD COLUMN who_wip_chat_id INTEGER` aus (SQLite only).

### `/wip` (`repo.py`)
- `set_wip()` setzt `who_wip_chat_id = actor_chat_id` im selben conditional
  UPDATE. **Keine Signaturänderung nötig:** der `actor_chat_id` ist per
  Definition genau die Person, die das Ticket übernimmt — `who_wip_chat_id` ==
  `actor_chat_id`. Bestehende Aufrufer/Tests bleiben unverändert.

### Repo (`repo.py`)
- `active_tickets()` bekommt optionalen Parameter `who_wip_chat_id: int | None`,
  der `WHERE ticket.who_wip_chat_id == ?` anhängt (gleiches Muster wie die
  bestehenden `group_tasked`/`status`-Filter). Keine neue Funktion nötig.

### `/close` (`bot/orga.py`)
`cmd_close()` umgebaut (Direktform `/close <id>` bleibt unverändert):

- **Picker ohne Argument:**
  - `own = active_tickets(group_tasked=group, status=WIP, who_wip_chat_id=user.id)`
  - **own nicht leer:** Inline-Buttons `close:{id}` je eigenem Ticket
    + `close:_all` („Alle der Gruppe anzeigen") + cancel.
  - **own leer:** direkt die volle Gruppenliste
    (`active_tickets(group, status=WIP)`), Buttons `close:{id}` + cancel, mit
    Hinweis „keine eigenen WIP — zeige alle der Gruppe". Ist auch die
    Gruppenliste leer → bestehende „keine WIP Tickets"-Meldung. (Kein Dead-End.)

- **Callback `on_close_choice()`:**
  - `close:_cancel` → abbrechen (unverändert)
  - `close:_all` → volle Gruppenliste rendern (`close:{id}` + cancel, **ohne**
    erneuten `_all`-Button)
  - `close:{id}` → `_do_close()` (unverändert)

### i18n (`i18n.py`)
- `PICKER_SHOW_ALL` (Button „📋 Alle der Gruppe anzeigen").
- `MY_WIP_TICKETS_LIST` („Deine WIP Tickets:") und
  `NO_OWN_WIP_SHOWING_GROUP` (Fallback-Hinweis).

## Tests (behavioural, wie im Repo etabliert; `tests/`)

- **repo:** `set_wip` schreibt `who_wip_chat_id == actor_chat_id`.
- **`/close` ohne Argument, eigene vorhanden:** Picker zeigt nur eigene + den
  `_all`-Button; fremde WIP-Tickets fehlen.
- **`close:_all`-Callback:** rendert die volle Gruppenliste (inkl. fremder),
  ohne erneuten `_all`-Button.
- **`/close` ohne Argument, keine eigenen:** Fallback direkt auf Gruppenliste mit
  Hinweis „Keine eigenen".
- **`/close` ohne WIP überhaupt:** „Keine WIP Tickets"-Meldung.
- **`/close <id>` direkt:** unverändert (bestehende Tests bleiben grün).
- **Migration (`test_db_migration.py`):** `_ensure_ticket_columns` ergänzt die
  fehlende Spalte auf einer Legacy-DB und ist idempotent.

## Migrationsrisiko / Betrieb

Additive Spalte ist risikoarm. `_ensure_ticket_columns()` ist idempotent (prüft
`PRAGMA table_info` vor dem `ALTER`). Keine Datenmigration nötig — Alttickets
haben `who_wip_chat_id = NULL` und tauchen damit korrekt nicht in „meine" auf
(sie sind ohnehin meist schon geschlossen).

## Folge-Runden (Kontext, nicht Teil dieses Commits)

- **Commit 2 — `/self`:** eigene laufende WIP (Liste) + Anzahl offen, geschlossen
  heute/gesamt, ⌀ Bearbeitungszeit. Matcht über `who_wip_chat_id`. Orga-only,
  Button auf der Orga-Tastatur.
- **Commit 3 — Settings:** Anzeigename-Override und Notification-Granularität;
  Speicherung als Spalten an `registration` (gleiches Muster wie
  `mute_peer_until`).

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

## Architektur / Änderungen

### Schema (`db.rs`)
- `ticket` bekommt Spalte `who_wip_chat_id INTEGER` (nullable).
- **Migration für die bestehende Live-DB:** additive `ALTER TABLE ticket ADD
  COLUMN who_wip_chat_id INTEGER`, idempotent (gegen „duplicate column"-Fehler
  geguardet bzw. via `pragma table_info`-Check). `CREATE TABLE IF NOT EXISTS`
  allein reicht nicht, da die Tabelle bereits existiert.
- Optionaler Index `ix_ticket_who_wip_chat_id` (klein, hilft dem Eigen-Filter).

### Model (`models.rs`)
- `Ticket` bekommt Feld `who_wip_chat_id: Option<i64>`.
- Alle SELECT/INSERT/UPDATE-Mappings in `repo.rs`/`db.rs` entsprechend erweitern.

### `/wip` (`bot/orga.rs`)
- `set_wip` schreibt zusätzlich `who_wip_chat_id = caller.chat_id`. Der Aufrufer
  hat `caller.chat_id` bereits (wird heute schon an `set_wip` übergeben).

### Repo (`repo.rs`)
- Neue Query analog zum bestehenden `active_tickets`-Muster, gefiltert nach
  bearbeitendem User:
  ```rust
  pub async fn wip_tickets_for_chat_id(
      pool: &SqlitePool, who_wip_chat_id: i64,
  ) -> Result<Vec<Ticket>, RepoError>
  // WHERE status = 'wip' AND who_wip_chat_id = ? ORDER BY id
  ```

### `/close` (`bot/orga.rs`)
`cmd_close()` umgebaut (Direktform `/close <id>` bleibt unverändert):

- **Picker ohne Argument:**
  - `own = wip_tickets_for_chat_id(caller.chat_id)`
  - **own nicht leer:** Inline-Buttons `close:{id}` je eigenem Ticket
    + `close:_all` („Alle der Gruppe anzeigen") + cancel.
  - **own leer:** direkt die volle Gruppenliste
    (`active_tickets(group, Wip)`), Buttons `close:{id}` + cancel, mit Hinweis
    „keine eigenen WIP — zeige alle der Gruppe". Ist auch die Gruppenliste leer →
    bestehende „keine offenen Tickets"-Meldung. (Kein Dead-End.)

- **Callback `on_close_choice()`:**
  - `close:_cancel` → abbrechen (unverändert)
  - `close:_all` → volle Gruppenliste rendern (`close:{id}` + cancel, **ohne**
    erneuten `_all`-Button)
  - `close:{id}` → `do_close()` (unverändert)

### i18n (`i18n.rs`)
- Button-Label „Alle der Gruppe anzeigen".
- Header/Hinweis für „eigene WIP-Tickets" bzw. „keine eigenen, zeige Gruppe".

## Tests (behavioural, wie im Repo etabliert)

- **repo:** `wip_tickets_for_chat_id` liefert nur WIP-Tickets des gegebenen
  `chat_id`; ignoriert fremde und nicht-WIP-Tickets.
- **`/wip`:** setzt `who_wip_chat_id` auf `caller.chat_id` (und `who_wip` weiter
  auf den String).
- **`/close` ohne Argument, eigene vorhanden:** Picker zeigt nur eigene + den
  `_all`-Button.
- **`close:_all`-Callback:** rendert die volle Gruppenliste.
- **`/close` ohne Argument, keine eigenen:** Fallback direkt auf Gruppenliste mit
  Hinweis.
- **`/close <id>` direkt:** unverändert funktionsfähig.

## Migrationsrisiko / Betrieb

Additive Spalte auf bestehender SQLite-DB ist risikoarm. Einzige Sorgfalt: die
`ALTER TABLE` muss idempotent sein (Bot startet ggf. gegen eine DB, in der die
Spalte schon existiert). Keine Datenmigration nötig — Alttickets haben
`who_wip_chat_id = NULL` und tauchen damit korrekt nicht in „meine" auf (sie sind
ohnehin meist schon geschlossen).

## Folge-Runden (Kontext, nicht Teil dieses Commits)

- **Commit 2 — `/self`:** eigene laufende WIP (Liste) + Anzahl offen, geschlossen
  heute/gesamt, ⌀ Bearbeitungszeit. Matcht über `who_wip_chat_id`. Orga-only,
  Button auf der Orga-Tastatur.
- **Commit 3 — Settings:** Anzeigename-Override und Notification-Granularität;
  Speicherung als Spalten an `registration` (gleiches Muster wie
  `mute_peer_until`).

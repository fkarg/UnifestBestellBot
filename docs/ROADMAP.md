# Roadmap

Open GitHub issues, the case for each, and a sketch for how to land them.
Reviewed against the current state of the rewrite (`unifest2026` branch).

## #19 — Clearer indication of which orga group receives a ticket

**Issue.** After `/request → … → ticket created`, the confirmation
says only `"Ticket #N erstellt."` — the user doesn't see which orga
team will handle it.

**Worth doing?** Yes. Trivial change, real UX benefit. Reduces "did
this even reach Finanz?" anxiety.

**Plan.** Change the finalize confirmation in
`bot/request.py:_finalize` to include the routed group:

```
i18n.REQUEST_TICKET_CREATED = "Ticket #{uid} erstellt. Geht an [{orga}]."
```

Plus a small test that the confirmation contains the routed group's name.

**Effort.** ~5 LOC + 1 test. Half an hour.

---

## #17 — Opt out of peer activity messages

**Issue.** Orga members get pinged for every peer action (someone else
in their team started/closed a ticket). On a busy night this is noisy.

**Worth doing?** Marginal. The peer message exists *for a reason* — it
prevents two people from grabbing the same ticket. A permanent mute
would be dangerous (volunteer toggles it during a calm moment, forgets,
misses real tickets). A **time-boxed** mute is safer.

**Plan.**

- Add `notifications_quiet_until: datetime | None` to `Registration`.
- Two new commands:
  - `/quiet [minutes=30]` — set `notifications_quiet_until = now + N`
  - `/loud` — clear the field
- Modify `notify.group_msg` to skip chat_ids whose registration has
  `quiet_until > now`.
- Mute auto-expires; no risk of permanent silence.
- Maybe also: tickets-to-the-requester (CLOSED notification on your own
  ticket) bypass the mute, since the user is waiting for that one.

**Effort.** ~60 LOC + 4–5 tests. Half a day. No schema migration needed
(DB is wiped between events; `create_all` adds the column).

**Risk.** Low. Worst case a volunteer mutes during a real event — but
30 min is short and they get loud back automatically.

---

## #16 — Ticket history with who closed them

**Issue.** Orga wants to look back at recent closed tickets and see who
did what.

**State.** The data is fully captured in the `auditevent` table —
every `open`, `wip`, `close`, `move`, `register`, `unregister`, and
`message` event has a timestamp, ticket id, actor chat id, and a JSON
payload. An operator with `sqlite3 bot.db` can already query this. The
issue is the *user-facing surface* for orga.

**Worth doing?** Yes — the audit data was added precisely to be useful
on the operator side, but right now only the dev can read it.

**Plan.**

- New orga command `/history [n=10]`. Returns the last *n* closed
  tickets with the closer's name and timestamp. Defaults to the user's
  orga group; takes an optional `all` flag to span every group.
- Optional follow-up command `/audit <ticket-id>`. Returns the full
  transition log of one ticket.

Both pull from `auditevent JOIN ticket` via small repo helpers.
Implementation in `bot/orga.py`, gated by `IsOrga()`.

**Effort.** ~80 LOC + 4–5 tests.

---

## #20 + #21 — Engelsystem shift digest to Helfen

**Issues.** Helfen / orga teams want to be notified about which helpers
should be on the current and next shifts. (#20 is generic; #21 is the
same scoped to Helfen.)

**State.** `/helpers` exists as a pull command — orga has to ask. The
issue is about *push*.

**Worth doing?** Yes for #20/21 — modest effort, real value on event
days when the Helfen team is the one chasing missing volunteers.

**Plan.**

- Add a `scheduler.py` module with one task: every 5 minutes (during
  operational hours, configurable in `config.yaml`), call
  `engelsystem.summarize_shifts` for every `locations:` entry, and if a
  shift is starting in the next 10 min, fan out a digest DM to all
  Helfen members.
- Suppress duplicates — track "last digested shift id" in memory so
  the same shift isn't announced every 5 min.
- Run inside the same asyncio loop via `asyncio.create_task` from
  `__main__`; no new dep (no APScheduler needed for a single recurring
  task).
- Operational hours: a `digest_window:` block in `config.yaml`
  (e.g. start: "18:00", end: "02:00") so the bot doesn't ping Helfen
  at 4 a.m. with the next-day rota.

**Effort.** ~150 LOC + tests (with the existing engelsystem fixture).
A focused day.

**Open question.** Should it also notify on shift END? Helfen handover
ceremony etc. Defer until first event week feedback.

---

## #22 — Idling and missing helpers

**Issue.** Notify Helfen about helpers who are idling or who didn't
show up to their shift.

**Worth doing?** *Probably not* in the bot. The bot has no
ground-truth signal for "actually present" — Engelsystem records who
was *scheduled*, not who *showed up*. To detect "missing", you'd need
one of:

- Engelsystem to expose attendance (it doesn't, as of last check).
- A check-in flow inside the bot (volunteer DMs "/checkin" on arrival).
  Adds friction to every shift, easy to forget, likely worse than the
  current self-report flow.
- Manual reports from stands — which **already exists**:
  `/request → Helfer → Helfer nicht da` produces a ticket to Helfen
  with the missing volunteer's username.

"Idling" is even harder: no signal at all.

**Recommendation.** Close as **wontfix**, pointing at the existing
`/request → Helfer` flow. If we want to make that path more obvious,
that's better tracked as a separate UX ticket.

If kept open: the most we could reasonably do is, at the start of a
shift, list the scheduled helpers and ask Helfen to confirm presence
(reply "alle da" / "Anna fehlt"). That's a manual confirmation flow
disguised as a notification — not really push detection.

---

## Suggested order

1. **#19** — half an hour, immediate UX win.
2. **#17** — half a day, with timed auto-revert.
3. **#16** — half a day. `/history` is the more useful of the two
   commands; `/audit` can wait.
4. **#20/#21 (combined)** — focused day with tests.
5. **#22** — close as wontfix; reopen if event ops reveal a concrete need.

Items 1–3 fit comfortably before the event. #20/21 is the only one
that needs a meaningful design pass.

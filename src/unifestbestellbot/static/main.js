const params = new URLSearchParams(location.search);
const group = params.get("group");
const qs = group ? `?group=${encodeURIComponent(group)}` : "";

const container = document.getElementById("tickets");
const empty = document.getElementById("empty");
const ding = document.getElementById("ding");
const conn = document.getElementById("connection");
document.getElementById("group-label").textContent = group ? `· ${group}` : "";

const RECONNECT_DELAY_MS = 10000;
const ONLINE_GRACE_MS = 2000;
const STALE_AFTER_MS = 25000;
const STALE_CHECK_MS = 1000;

let allowSound = false;
document.body.addEventListener(
  "click",
  () => {
    document.documentElement.requestFullscreen?.();
    allowSound = true;
  },
  { once: true }
);

// Ticket aging / SLA: a ticket sitting unhandled turns amber, then red.
// Thresholds are wall-clock since the ticket was created (WIP included —
// a claimed-but-not-delivered ticket aging is also a failure the TV should
// show). Tune here.
const AGE_WARN_MS = 8 * 60 * 1000;
const AGE_CRIT_MS = 15 * 60 * 1000;
const AGE_REFRESH_MS = 15000;

// Current in-scope, non-closed tickets by id, plus the ids we've already
// seen (so re-snapshotting on reconnect never re-dings). Both live at module
// scope so they survive a stream reconnect.
const tickets = new Map();
const seen = new Set();

function updateEmpty() {
  empty.hidden = tickets.size !== 0;
}

function inScope(t) {
  // Unfiltered board shows everything; a ?group= board shows only tickets
  // currently tasked to that group (so a moved-away ticket drops off).
  if (!group) return true;
  return (t.group_tasked ?? "").toLowerCase() === group.toLowerCase();
}

function createdMs(t) {
  // created_at is naive UTC (SQLite drops tz). Append "Z" so the browser
  // parses it as UTC — without it, JS reads the string as local time and
  // skews every age by the timezone offset (all tickets would look old).
  return t.created_at ? Date.parse(t.created_at + "Z") : NaN;
}

function ageInfo(t, now) {
  const started = createdMs(t);
  if (Number.isNaN(started)) return { label: "", level: "" };
  const ms = Math.max(0, now - started);
  const mins = Math.floor(ms / 60000);
  const label = mins < 60 ? `${mins} min` : `${Math.floor(mins / 60)} h ${mins % 60} min`;
  const level = ms >= AGE_CRIT_MS ? "crit" : ms >= AGE_WARN_MS ? "warn" : "";
  return { label, level };
}

function sortedTickets() {
  // OPEN before WIP, oldest first within each — the ticket that's been
  // waiting longest rises to the top of the board.
  return [...tickets.values()].sort((a, b) => {
    const rank = (a.status === "open" ? 0 : 1) - (b.status === "open" ? 0 : 1);
    if (rank !== 0) return rank;
    return (a.created_at ?? "").localeCompare(b.created_at ?? "");
  });
}

function applyAge(el, t, now) {
  const { label, level } = ageInfo(t, now);
  el.className = `ticket ${t.status}${level ? " " + level : ""}`;
  el.querySelector(".age").textContent = label;
}

function ticketEl(t, now) {
  const el = document.createElement("article");
  el.id = `t-${t.id}`;
  el.innerHTML = `
    <p class="text"></p>
    <p class="meta"><span class="who"></span><span class="age"></span><span class="uid">#${t.id}</span></p>
  `;
  el.querySelector(".text").textContent = t.text;
  el.querySelector(".who").textContent = t.who_wip ?? "";
  applyAge(el, t, now);
  return el;
}

function renderAll() {
  const now = Date.now();
  const frag = document.createDocumentFragment();
  for (const t of sortedTickets()) frag.appendChild(ticketEl(t, now));
  container.replaceChildren(frag);
  updateEmpty();
}

// Re-evaluate ages in place (no DOM rebuild) so colors escalate without
// waiting for the next ticket event.
setInterval(() => {
  const now = Date.now();
  for (const t of tickets.values()) {
    const el = document.getElementById(`t-${t.id}`);
    if (el) applyAge(el, t, now);
  }
}, AGE_REFRESH_MS);

function ingest(t) {
  if (t.status === "closed" || !inScope(t)) {
    tickets.delete(t.id);
    return;
  }
  if (allowSound && t.status === "open" && !seen.has(t.id)) {
    ding.play().catch(() => {});
  }
  seen.add(t.id);
  tickets.set(t.id, t);
}

// Live events that arrive before the initial snapshot has been applied are
// buffered, then replayed once the snapshot is in. ingest() is keyed by
// ticket id, so replaying over the snapshot can only correct it, never
// duplicate. This closes the gap where a ticket created between the snapshot
// fetch and the stream subscription would otherwise be lost until reload.
let snapshotted = false;
let buffer = [];
let currentStream = null;
let reconnectTimer = null;
let streamOpened = false;
let offlineTimer = null;
let lastServerActivityAt = 0;

function markOnline() {
  lastServerActivityAt = Date.now();
  conn.textContent = "online";
  conn.className = "on";
}

function markReconnecting() {
  conn.textContent = "reconnecting…";
  conn.className = "off";
}

function checkStaleConnection() {
  if (!streamOpened || lastServerActivityAt === 0) return;
  if (Date.now() - lastServerActivityAt > STALE_AFTER_MS) {
    markReconnecting();
  }
}

setInterval(checkStaleConnection, STALE_CHECK_MS);

function onTicket(t) {
  if (!snapshotted) {
    buffer.push(t);
    return;
  }
  ingest(t);
  renderAll();
}

async function snapshot() {
  const r = await fetch(`/api/tickets${qs}`);
  const arr = await r.json();
  tickets.clear();
  for (const t of arr) ingest(t);
  snapshotted = true;
  for (const t of buffer) ingest(t);
  buffer = [];
  renderAll();
}

function subscribe() {
  currentStream?.close();
  const es = new EventSource(`/api/stream${qs}`);
  currentStream = es;
  es.addEventListener("open", () => {
    if (offlineTimer !== null) {
      clearTimeout(offlineTimer);
      offlineTimer = null;
    }
    streamOpened = true;
    markOnline();
  });
  es.addEventListener("heartbeat", () => markOnline());
  es.addEventListener("ticket", (e) => {
    markOnline();
    onTicket(JSON.parse(e.data));
  });
  es.addEventListener("error", () => {
    if (currentStream !== es) return;
    if (!streamOpened) {
      markReconnecting();
    } else {
      offlineTimer ??= setTimeout(() => {
        if (currentStream !== es) return;
        markReconnecting();
        offlineTimer = null;
      }, ONLINE_GRACE_MS);
    }
    es.close();
    reconnectTimer ??= setTimeout(() => {
      reconnectTimer = null;
      start();
    }, RECONNECT_DELAY_MS);
  });
}

function start() {
  // Subscribe first (registers the stream synchronously), then snapshot.
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (offlineTimer !== null) {
    clearTimeout(offlineTimer);
    offlineTimer = null;
  }
  snapshotted = false;
  buffer = [];
  lastServerActivityAt = 0;
  subscribe();
  snapshot();
}

start();

const params = new URLSearchParams(location.search);
const group = params.get("group");
const qs = group ? `?group=${encodeURIComponent(group)}` : "";

const container = document.getElementById("tickets");
const empty = document.getElementById("empty");
const ding = document.getElementById("ding");
const conn = document.getElementById("connection");
document.getElementById("group-label").textContent = group ? `· ${group}` : "";

let allowSound = false;
document.body.addEventListener(
  "click",
  () => {
    document.documentElement.requestFullscreen?.();
    allowSound = true;
  },
  { once: true }
);

function updateEmpty() {
  empty.hidden = container.querySelector(".ticket") !== null;
}

function render(t) {
  let el = document.getElementById(`t-${t.id}`);
  if (t.status === "closed") {
    el?.remove();
    updateEmpty();
    return;
  }
  const isNew = !el;
  if (isNew) {
    el = document.createElement("article");
    el.id = `t-${t.id}`;
    container.prepend(el);
    if (allowSound && t.status === "open") {
      ding.play().catch(() => {});
    }
  }
  el.className = `ticket ${t.status}`;
  el.innerHTML = `
    <p class="text"></p>
    <p class="meta"><span class="who"></span><span class="uid">#${t.id}</span></p>
  `;
  el.querySelector(".text").textContent = t.text;
  el.querySelector(".who").textContent = t.who_wip ?? "";
  updateEmpty();
}

async function snapshot() {
  const r = await fetch(`/api/tickets${qs}`);
  const tickets = await r.json();
  container.replaceChildren();
  for (const t of tickets) render(t);
  updateEmpty();
}

function subscribe() {
  const es = new EventSource(`/api/stream${qs}`);
  es.addEventListener("open", () => {
    conn.textContent = "live";
    conn.className = "on";
  });
  es.addEventListener("ticket", (e) => render(JSON.parse(e.data)));
  es.addEventListener("error", () => {
    conn.textContent = "reconnecting…";
    conn.className = "off";
    es.close();
    setTimeout(start, 1500);
  });
}

async function start() {
  await snapshot();
  subscribe();
}

start();

// Game page (specification 7.2): renders the view the server sends and sends actions back.
// It holds no game logic: what may be done comes from the legal actions in each message.
"use strict";

const $ = (id) => document.getElementById(id);
const gameId = decodeURIComponent(location.pathname.split("/").pop());
const key = (name) => `nv:${gameId}:${name}`;
const store = {
  get: (name) => { try { return localStorage.getItem(key(name)) || ""; } catch { return ""; } },
  set: (name, value) => { try { localStorage.setItem(key(name), value); } catch { /* private window */ } },
};

// A host link carries the host token (#host=...); a seat link the seat token (#seat=...), so a
// player can take their seat to another device.
for (const [prefix, name] of [["#host=", "host"], ["#seat=", "seat"]]) {
  if (location.hash.startsWith(prefix)) {
    store.set(name, location.hash.slice(prefix.length));
    history.replaceState(null, "", location.pathname);
  }
}

let msg = null;          // what the page shows: the live message, or a replayed view
let live = null;         // the latest message from the server
let replay = null;       // spectators: the replayed state being shown (specification 7.3)
let rounds = null;       // spectators: where each round starts, for the replay controls
let socket = null;
let lobbyOptions = null; // seat kinds, for the host's "hand over" control
let refused = false;     // the server would not let this browser in

// Small helpers -----------------------------------------------------------------------------------
function fill(node, ...children) {  // append children, skipping empty ones (null would show as "null")
  node.innerHTML = "";
  node.append(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
}
function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k.startsWith("on")) node[k] = v;
    else if (k === "class") node.className = v;
    else if (v !== false && v !== null && v !== undefined) node.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
function showError(text) {
  const bar = $("error");
  bar.textContent = text || "";
  bar.style.display = text ? "block" : "none";
}
const view = () => msg && msg.view;
const nameOf = (seat) => (view() ? view().players[seat] : `seat ${seat + 1}`);
const colourOf = (seat) => (msg && msg.seats[seat] ? msg.seats[seat].colour : "gray");
const chip = (seat) => h("span", { class: "chip", style: `background:${colourOf(seat)}` }, nameOf(seat));
const values = (obj) => Object.entries(obj || {}).map(([k, v]) => `${k}=${v === null ? "blank" : v}`).join(", ");
function table(headers, rows) {
  return h("table", {}, h("tr", {}, headers.map((x) => h("th", {}, x))), rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c)))));
}
function send(action) {
  showError("");
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "action", action }));
}
function mustAct() {
  const v = view();
  return v && msg.status === "running" && msg.you !== null && (v.current === msg.you || v.waiting.includes(msg.you));
}

// Joining ------------------------------------------------------------------------------------------
async function showJoin() {
  $("board").style.display = "none";
  const box = $("join");
  box.style.display = "flex";
  const response = await fetch(`/api/games/${gameId}`);
  const info = await response.json();
  if (!response.ok) { box.textContent = info.detail || "No such game."; return; }
  const free = info.seats.filter((s) => s.human_seat && !s.taken);
  const panel = h("section", { class: "panel" }, h("h2", {}, `Join: ${info.title} (${info.world})`));
  if (!free.length) {
    panel.append(h("p", {}, "All seats for people are taken."));
  } else {
    const seat = h("select", {}, free.map((s) => h("option", { value: s.seat }, `Seat ${s.seat + 1}`)));
    const nickname = h("input", { placeholder: "your nickname", maxlength: 30 });
    const colour = h("select", {}, info.colours.map((c) => h("option", { value: c }, c)));
    const password = h("input", { type: "password", placeholder: "join password" });
    const button = h("button", { class: "primary", onclick: async () => {
      const r = await fetch(`/api/games/${gameId}/join`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seat: Number(seat.value), nickname: nickname.value, colour: colour.value, password: password.value }),
      });
      const data = await r.json();
      if (!r.ok) { showError(data.detail); return; }
      store.set("seat", data.seat_token);
      location.reload();
    } }, "Join");
    panel.append(
      h("div", { class: "form-row" }, "Seat ", seat, " Nickname ", nickname, " Colour ", colour),
      info.join_password ? h("div", { class: "form-row" }, "Password ", password) : null,
      button,
    );
  }
  if (store.get("host")) panel.append(h("p", {}, h("button", { onclick: () => { box.style.display = "none"; $("board").style.display = ""; connect(); } }, "Continue as host without a seat (you spectate)")));
  const watch = h("input", { type: "password", placeholder: "spectator password" });
  panel.append(h("h3", {}, "Or watch as a spectator"), h("div", { class: "form-row" }, watch, " ",
    h("button", { onclick: () => {
      store.set("spectator", watch.value);
      store.set("spectate", "1");
      refused = false;
      box.style.display = "none";
      $("board").style.display = "";
      connect();
    } }, "Watch")),
  h("p", { class: "small muted" }, "Spectators see everything, including every lab and the hidden world, so the host decides who may watch."));
  box.innerHTML = "";
  box.append(panel);
}

// Connection ------------------------------------------------------------------------------------
function connect() {
  const query = new URLSearchParams({
    seat_token: store.get("seat"), host_token: store.get("host"),
    spectate: store.get("spectate") === "1" ? "1" : "0", spectator_password: store.get("spectator"),
  });
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${location.host}/ws/${gameId}?${query}`);
  const this_socket = socket;
  socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "error") {
      showError(data.message);
      task.afterSend = null;  // refused: the draft stays
      if (!msg) refused = true;  // no seat and not the host: show the join form instead of reconnecting
      return;
    }
    if (data.type === "accepted") { showError(""); return; }
    if (data.type === "state" && (!live || data.seq >= live.seq || data.status !== live.status || data.you !== live.you)) {
      live = data;
      if (!live.spectator) replay = null;
      msg = replay ? { ...live, view: replay.view, text: replay.text, events: replay.events } : live;
      render();
    }
  };
  socket.onclose = () => {
    if (socket !== this_socket) return;  // replaced by a new connection
    if (refused) { store.set("seat", ""); store.set("spectator", ""); store.set("spectate", ""); showJoin(); return; }
    $("status").textContent = "Connection lost; reconnecting...";
    setTimeout(connect, 1500);
  };
}

// Rendering ---------------------------------------------------------------------------------------
function render() {
  const asText = $("as-text").checked;
  $("board").style.display = asText ? "none" : "";
  $("text-view").style.display = asText ? "block" : "none";
  $("text").textContent = msg.text || "(no view yet)";
  renderStatus();
  renderBanner();
  renderHost();
  renderLog();
  renderPhaseBar();
  renderColumns();
  const spectator = Boolean(msg.spectator);
  if (spectator) { setTaskHeading(); $("actions-title").textContent = "Replay"; }
  $("lab-title").textContent = spectator ? "Every lab" : "Your lab";
  if (!spectator) $("lab-title").append(" ", h("span", { class: "h-note" }, "behind your lab shield"));
  $("world-panel").style.display = spectator ? "" : "none";
  $("notes-panel").style.display = spectator && Object.keys(msg.ai_notes || {}).length ? "" : "none";
  const v = view();
  if (spectator || !v) actionsShown = null;  // the actions panel shows something else now
  if (!v) {
    for (const id of ["actions", "grid", "records", "ideas", "literature", "portal", "methods", "predictions", "lab", "tracks", "alliances"]) $(id).innerHTML = "";
    selected = null;
    setTaskHeading();
    refreshHighlights();
    $("actions").append(h("p", { class: "muted" }, msg.status === "lobby"
      ? "Waiting for the host to start the game. Seats: " + msg.seats.map((s) => `${s.name} (${s.kind}${s.taken ? ", joined" : ""})`).join(", ")
      : "You have no seat in this game; you see the public event log."));
    return;
  }
  loadIcons(v.scenario.id);
  if (spectator) { renderReplay(); renderWorld(); renderNotes(); } else renderActions();
  renderGrid();
  renderRecords();
  renderIdeas();
  renderLab();
  renderLiterature();
  renderPortal();
  renderMethods();
  renderPredictions();
  renderTracks();
  renderAlliances();
  refreshHighlights();
  layoutPins();
}

function renderStatus() {
  const v = view();
  const parts = [];
  if (v) {
    parts.push(h("b", {}, `Round ${v.round}`), ` \u00b7 ${v.phase} \u00b7 `, periodStatus(v), " \u00b7 ");
    const waiting = v.current !== null && v.current !== undefined ? [v.current] : v.waiting;
    if (v.result) parts.push("game over");
    else if (msg.status !== "running") parts.push(`game ${msg.status}`);
    else parts.push("waiting for: ", ...waiting.map((s) => chip(s)));
    if (mustAct()) parts.push(" ", h("span", { class: "you-act" }, "your move"));
  } else {
    parts.push(`${msg.title} \u00b7 ${msg.status}`);
  }
  const cost = Object.values(msg.ai_cost || {}).reduce((a, b) => a + b, 0);
  if (cost > 0) parts.push(h("span", { class: "muted" }, ` \u00b7 AI cost ${cost.toFixed(4)} USD`));
  if (msg.you !== null) parts.push(h("span", { class: "muted" }, " \u00b7 you are "), chip(msg.you));
  if (msg.spectator) parts.push(h("span", { class: "you-act" }, replay ? `replay: action ${replay.at} of ${replay.total}` : "spectating"));
  $("status").innerHTML = "";
  $("status").append(...parts);
  $("actions-panel").classList.toggle("act", mustAct());
}

// The Game Period Deck and the Warning shot or Crisis, always in view in the top row.
function periodStatus(v) {
  const deck = ` (Game Period Deck: ${v.period_deck} left)`;
  if (v.crisis) {
    const c = v.crisis;
    return h("span", { class: "bad" }, h("b", {}, "CRISIS"),
      ` round ${c.rounds_in_crisis} of ${c.crisis_length}, unsuccessful predictions ${c.unsuccessful} of ${c.crisis_condition}${deck}`);
  }
  if (v.warning_revealed) return h("span", { class: "warn-shot" }, h("b", {}, "Warning shot revealed"), deck);
  return h("span", {}, `Calm period${deck}`);
}

function renderBanner() {
  const v = view();
  const box = $("banner");
  box.innerHTML = "";
  const debrief = h("a", { href: `/game/${encodeURIComponent(gameId)}/debrief` }, "Open the debrief");
  if (v && v.result && !replay) {
    const r = v.result;
    const winners = (r.winners || []).map((s) => nameOf(s)).join(", ") || "nobody";
    box.append(h("div", { class: "banner" }, `Game over: ${String(r.ending).replace("_", " ")}. Winners: ${winners}. `, debrief));
  } else if (msg.status === "ended") {
    box.append(h("div", { class: "banner" }, "The host ended this game. ", debrief));
  } else if (msg.status === "paused") {
    box.append(h("div", { class: "banner" }, "The game is paused by the host."));
  }
}

// The phases of a round, as the phase bar shows them, each with the engine's steps (nv_core.state.Phase)
// that belong to it. The last two have no step: they run by themselves at the end of the round.
const ROUND_PHASES = [
  ["Hiring", ["Hiring and task allocation phase", "Alliance: last chance to leave", "Student task check phase"]],
  ["Experimentation", ["Experimentation and equipment phase"]],
  ["Probe time", ["Probe time"]],
  ["Observation and prediction", ["Formulating predictions and preregistration", "Outcome and Prediction Reveal", "Scoring predictions: order"]],
  ["Development", ["Development phase"]],
  ["Publication", ["Publication: submission and revisions", "Publication: peer review"]],
  ["Talent development", []],
  ["Clean-up", []],
];
// The engine's steps in round order, and the steps where each staff task works. Talent development
// and Grants work after the last step (Talent development and Clean-up phases), so they are never
// "past" within a round.
const STEP_ORDER = ROUND_PHASES.flatMap(([, steps]) => steps);

function renderPhaseBar() {
  const v = view();
  const bar = $("phase-bar");
  bar.style.display = v ? "" : "none";
  if (!v) return;
  const now = v.result ? -1 : ROUND_PHASES.findIndex(([, steps]) => steps.includes(v.phase));
  fill(bar, h("span", { class: "phase-label" }, "This round"), ROUND_PHASES.map(([name], i) =>
    h("span", { class: `phase-step${now < 0 ? "" : i < now ? " done" : i === now ? " now" : ""}`, title: i === now ? "The current phase" : null }, h("b", {}, String(i + 1)), name)));
}
const TASK_STEPS = {
  experimentation: ["Experimentation and equipment phase"],
  data_collection: ["Formulating predictions and preregistration", "Outcome and Prediction Reveal", "Scoring predictions: order"],
  development: ["Development phase"],
  write_up: ["Publication: submission and revisions"],
  peer_review: ["Publication: peer review"],
};
const TASK_WHEN = {
  experimentation: "Experimentation", data_collection: "Observation and prediction", development: "Development",
  write_up: "Publication: submission", peer_review: "Publication: peer review",
  talent_development: "Talent development", grants: "Clean-up (grants)",
};
const TASK_ORDER = ["experimentation", "data_collection", "development", "write_up", "peer_review", "talent_development", "grants"];
const taskOrder = (t) => (TASK_ORDER.includes(t) ? TASK_ORDER.indexOf(t) : TASK_ORDER.length);

function renderLab() {
  const v = view();
  const box = $("lab");
  box.innerHTML = "";
  if (msg.spectator) {
    for (const lab of v.labs) {
      const part = h("div", { class: "option" }, h("h3", {}, chip(lab.seat)));
      labInto(part, v, v.researchers[lab.seat], lab);
      box.append(part);
    }
    return;
  }
  labInto(box, v, v.researchers[msg.you], v.lab);
}

function labInto(box, v, me, lab) {
  box.append(h("p", {}, `Credit ${me.credit} \u00b7 money ${me.money} \u00b7 Grant ${me.grant_position} \u00b7 Talent ${me.talent_position}`,
    h("br"), `${me.postdocs} postdoc(s), ${me.students} student(s) \u00b7 ${me.patents} patent(s)`));
  const staff = Object.entries(me.staff).filter(([, c]) => c.postdocs + c.students)
    .sort(([a], [b]) => taskOrder(a) - taskOrder(b));
  if (staff.length) {
    const now = STEP_ORDER.indexOf(v.phase);
    box.append(h("table", {},
      h("tr", {}, ["Task", "P", "S", "Used"].map((x) => h("th", {}, x))),
      staff.map(([t, c]) => {
        const steps = TASK_STEPS[t] || [];
        const first = Math.min(...steps.map((p) => STEP_ORDER.indexOf(p)));
        const last = Math.max(...steps.map((p) => STEP_ORDER.indexOf(p)));
        const cls = now < 0 || !steps.length ? "" : now > last ? "past" : now >= first ? "current" : "";
        const name = t.replace("_", " ");
        const when = TASK_WHEN[t] && TASK_WHEN[t].toLowerCase() !== name ? h("div", { class: "muted" }, TASK_WHEN[t]) : null;
        return h("tr", { class: cls }, h("td", {}, name, when), [c.postdocs, c.students, c.used].map((x) => h("td", {}, x)));
      })));
  }
  if (lab.leaving_students) box.append(h("p", { class: "bad" }, `${lab.leaving_students} student(s) must leave.`));
  const pending = lab.pending;
  if (pending.allocation) {
    const a = pending.allocation;
    box.append(h("p", { class: "small" }, `Planned staff: hire ${a.hire_postdocs} postdoc(s), fire ${a.fire_postdocs}, hire ${a.hire_students} student(s); `
      + Object.entries(a.allocation).map(([t, c]) => `${t} ${c.postdocs}p+${c.students}s`).join(", ")));
  }
  if (pending.leaving_students) box.append(h("p", { class: "small" }, `Leaving students chosen: ${values(pending.leaving_students)}`));
}

function renderTracks() {
  const v = view();
  const rows = v.researchers.map((r) => [
    h("span", {}, chip(r.seat), r.committed ? h("span", { class: "muted" }, " ready") : null),
    r.credit, r.money, r.grant_position, r.talent_position, `${r.postdocs}p ${r.students}s`, r.patents,
  ]);
  fill($("tracks"), table(["", "Credit", "Money", "Grant", "Talent", "Staff", "Pat."], rows));
}

function renderAlliances() {
  const v = view();
  const allies = v.alliances.map((pair) => `${nameOf(pair[0])} + ${nameOf(pair[1])}`);
  const option = msg.options.find((o) => o.type === "alliance");
  fill($("alliances"),
    h("p", { class: allies.length ? "" : "muted" }, allies.length ? allies.join(", ") : "No alliances."),
    v.proposals.length ? h("p", {}, "Proposed: " + v.proposals.map(([a, b]) => `${nameOf(a)} -> ${nameOf(b)}`).join(", ")) : null,
    option ? completeActions(option) : null,
  );
}

function renderMethods() {
  const methods = view().published.filter((p) => p.kind === "method").sort((a, b) => ownFirst(a, b) || a.id - b.id);
  fill($("methods"), methods.length ? methods.map((m) => h("div", {}, `M${m.id} ${m.parameter} `, chip(m.author), ` tier ${m.tier}`,
    m.open_access ? " open access" : "", m.fresh ? " fresh" : "")) : h("span", { class: "muted" }, "None published yet."));
}

function renderPredictions() {
  const v = view();
  const rows = v.predictions.map((p) => h("div", {}, `Q${p.id} `, chip(p.seat), ` T${p.theory} on P${p.probe + 1}`, p.preregistered ? ", preregistered" : "",
    p.success === null || p.success === undefined ? ` (${p.status})` : (p.success ? ": success" : ": failed")));
  const hidden = Object.entries(v.hidden_predictions || {}).map(([seat, probes]) =>
    `${nameOf(Number(seat))}: ${Object.entries(probes).map(([p, n]) => `${n} on P${Number(p) + 1}`).join(", ")}`);
  fill($("predictions"), rows.length ? rows : h("span", { class: "muted" }, "None visible yet."),
    hidden.length ? h("p", { class: "small" }, "Hidden predictions: " + hidden.join("; ")) : null);
}

function renderLog() {
  const filter = $("log-filter").value.toLowerCase();
  const box = $("log");
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 5;
  box.innerHTML = "";
  for (const line of msg.events) if (!filter || line.toLowerCase().includes(filter)) box.append(h("div", {}, line));
  if (atBottom) box.scrollTop = box.scrollHeight;
}
$("log-filter").oninput = () => msg && renderLog();
$("as-text").onchange = () => msg && render();

// Spectators: replay, World Table, AI notes (specification 7.3) ---------------------------------
function reconnect() {
  const old = socket;
  socket = null;
  if (old) old.close();
  msg = live = replay = rounds = null;
  connect();
}

async function loadReplay(at) {
  const r = await fetch(`/api/games/${gameId}/replay`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ host_token: store.get("host"), spectator_password: store.get("spectator"), at }),
  });
  const data = await r.json();
  if (!r.ok) { showError(data.detail || r.statusText); return null; }
  rounds = data.rounds;
  return data;
}

async function showReplay(at) {
  const data = await loadReplay(at);
  if (!data) return;
  replay = data;
  showError(data.problem || "");
  msg = { ...live, view: data.view, text: data.text, events: data.events };
  render();
}

function goLive() {
  replay = null;
  showError("");
  msg = live;
  render();
}

function renderReplay() {
  const box = $("actions");
  box.innerHTML = "";
  if (rounds === null) { rounds = []; loadReplay(live.seq).then(() => msg && renderReplay()); }
  const total = replay ? replay.total : live.seq;
  const at = replay ? replay.at : live.seq;
  const number = h("input", { type: "number", min: 0, max: total, value: at });
  const roundOf = (seq) => [...(rounds || [])].reverse().find((r) => r.seq <= seq);
  const current = roundOf(at);
  const select = h("select", { onchange: () => showReplay(Number(select.value)) },
    h("option", { value: "" }, "jump to round..."),
    (rounds || []).map((r) => h("option", { value: r.seq, selected: current && current.seq === r.seq && replay ? true : null }, `round ${r.round} (action ${r.seq})`)));
  box.append(
    h("p", {}, replay ? `Showing the game after action ${at} of ${total}.` : `Live: ${total} action(s) so far.`),
    h("div", { class: "replay" },
      h("button", { onclick: () => showReplay(0) }, "|< start"),
      h("button", { onclick: () => showReplay(Math.max(0, at - 1)) }, "< back"),
      h("button", { onclick: () => showReplay(Math.min(total, at + 1)) }, "forward >"),
      h("button", { class: replay ? "primary" : "", onclick: goLive }, "live >|"),
      select,
      "action ", number, ` of ${total} `,
      h("button", { onclick: () => showReplay(Number(number.value)) }, "go")),
    h("p", { class: "small" }, h("a", { href: `/game/${encodeURIComponent(gameId)}/debrief` }, "Open the debrief"),
      msg.view && msg.view.result ? "" : " (so far: spectators may look before the end)"),
  );
}

function renderNotes() {
  fill($("notes"), Object.entries(msg.ai_notes || {}).map(([name, text]) => h("div", {}, h("h3", {}, name), h("pre", {}, text))));
}

// Host controls ---------------------------------------------------------------------------------
async function hostCommand(command, extra) {
  const r = await fetch(`/api/games/${gameId}/host/${command}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ host_token: store.get("host"), ...(extra || {}) }),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) showError(data.detail || r.statusText);
}

async function renderHost() {
  $("host-panel").style.display = msg.host ? "" : "none";
  if (!msg.host) return;
  if (!lobbyOptions) lobbyOptions = await (await fetch("/api/options")).json();
  const box = $("host");
  box.innerHTML = "";
  const link = `${location.origin}/game/${gameId}`;
  box.append(h("p", { class: "small" }, "Join link: ", h("input", { value: link, readonly: true, size: 40 })));
  const buttons = [];
  if (msg.status === "lobby") buttons.push(h("button", { class: "primary", onclick: () => hostCommand("start") }, "Start the game"));
  if (msg.status === "running") buttons.push(h("button", { onclick: () => hostCommand("pause") }, "Pause"));
  if (msg.status === "paused") buttons.push(h("button", { class: "primary", onclick: () => hostCommand("resume") }, "Resume"));
  if (["running", "paused"].includes(msg.status)) buttons.push(h("button", { onclick: () => { if (confirm("End the game for everyone?")) hostCommand("end"); } }, "End the game"));
  box.append(h("div", {}, buttons));
  const rows = msg.seats.map((s) => {
    const controls = [];
    if (s.human_seat) {
      const kinds = h("select", {}, lobbyOptions.seat_kinds.filter((k) => k !== "human").map((k) => h("option", { value: k }, k)));
      if (s.kind === "human") controls.push(kinds, h("button", { onclick: () => hostCommand("automate", { seat: s.seat, kind: kinds.value }) }, "Hand to automated player"));
      else controls.push(h("button", { onclick: () => hostCommand("release", { seat: s.seat }) }, "Give back to the person"));
      if (s.taken) controls.push(h("button", { onclick: () => hostCommand("remove", { seat: s.seat }) }, "Free the seat"));
    }
    return [chip(s.seat), s.kind, s.human_seat ? (s.taken ? (s.connected ? "connected" : "joined, not connected") : "free") : "automated", h("span", {}, controls)];
  });
  box.append(table(["Seat", "Played by", "Person", ""], rows));
  if (msg.you === null && store.get("seat") === "") box.append(h("p", {}, h("button", { onclick: showJoin }, "Take a seat yourself")));
  if (store.get("seat")) {
    const watching = store.get("spectate") === "1";
    box.append(h("p", {}, h("button", { onclick: () => { store.set("spectate", watching ? "" : "1"); reconnect(); } },
      watching ? "Back to my seat" : "Watch as spectator (see every lab and the hidden world)")));
  }
}

// Start ------------------------------------------------------------------------------------------
initPanels();
if (store.get("seat") || store.get("host")) {
  if (!store.get("seat") && store.get("host")) {
    fetch(`/api/games/${gameId}`).then((r) => r.json()).then((info) => {
      if (info.status === "lobby" && info.seats.some((s) => s.human_seat && !s.taken)) showJoin(); else connect();
    });
  } else {
    connect();
  }
} else {
  showJoin();
}

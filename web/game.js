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
const nameOf = (seat) => (view() ? view().players[seat] : t("seat {n}", { n: seat + 1 }));
const colourOf = (seat) => (msg && msg.seats[seat] ? msg.seats[seat].colour : "gray");
const chip = (seat) => h("span", { class: "chip", style: `background:${colourOf(seat)}` }, nameOf(seat));
const values = (obj) => Object.entries(obj || {}).map(([k, v]) => `${t(k.replace("_", " "))}=${v === null ? t("blank") : v}`).join(", ");
function table(headers, rows) {
  return h("table", {}, h("tr", {}, headers.map((x) => h("th", {}, x))), rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c)))));
}
function send(action) {
  showError("");
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "action", action }));
}
// Send a choice and commit it in one click. The commit goes only once the server has accepted the
// choice (it answers each action in order), so a refused choice never commits an earlier one.
let commitAfter = false;
function sendAndCommit(action) {
  commitAfter = true;
  send(action);
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
  if (!response.ok) { box.textContent = info.detail || t("No such game."); return; }
  const free = info.seats.filter((s) => s.human_seat && !s.taken);
  const panel = h("section", { class: "panel" }, h("h2", {}, t("Join: {title} ({world})", { title: info.title, world: info.world })));
  if (!free.length) {
    panel.append(h("p", {}, t("All seats for people are taken.")));
  } else {
    const seat = h("select", {}, free.map((s) => h("option", { value: s.seat }, t("Seat {n}", { n: s.seat + 1 }))));
    const nickname = h("input", { placeholder: t("your nickname"), maxlength: 30 });
    const colour = h("select", {}, info.colours.map((c) => h("option", { value: c }, t(c))));
    const password = h("input", { type: "password", placeholder: t("join password") });
    const button = h("button", { class: "primary", onclick: async () => {
      const r = await fetch(`/api/games/${gameId}/join`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seat: Number(seat.value), nickname: nickname.value, colour: colour.value, password: password.value }),
      });
      const data = await r.json();
      if (!r.ok) { showError(data.detail); return; }
      store.set("seat", data.seat_token);
      location.reload();
    } }, t("Join"));
    panel.append(
      h("div", { class: "form-row" }, t("Seat"), " ", seat, " ", t("Nickname"), " ", nickname, " ", t("Colour"), " ", colour),
      info.join_password ? h("div", { class: "form-row" }, t("Password"), " ", password) : null,
      button,
    );
  }
  if (store.get("host")) panel.append(h("p", {}, h("button", { onclick: () => { box.style.display = "none"; $("board").style.display = ""; connect(); } }, t("Continue as host without a seat (you spectate)"))));
  const watch = h("input", { type: "password", placeholder: t("spectator password") });
  panel.append(h("h3", {}, t("Or watch as a spectator")), h("div", { class: "form-row" }, watch, " ",
    h("button", { onclick: () => {
      store.set("spectator", watch.value);
      store.set("spectate", "1");
      refused = false;
      box.style.display = "none";
      $("board").style.display = "";
      connect();
    } }, t("Watch"))),
  h("p", { class: "small muted" }, t("Spectators see everything, including every lab and the hidden world, so the host decides who may watch.")));
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
      commitAfter = false;
      task.afterSend = null;  // refused: the draft stays
      if (!msg) refused = true;  // no seat and not the host: show the join form instead of reconnecting
      return;
    }
    if (data.type === "accepted") {
      showError("");
      if (commitAfter) { commitAfter = false; send({ type: "commit" }); }
      return;
    }
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
    $("status").textContent = t("Connection lost; reconnecting...");
    setTimeout(connect, 1500);
  };
}

// Rendering ---------------------------------------------------------------------------------------
function render() {
  const asText = $("as-text").checked;
  $("board").style.display = asText ? "none" : "";
  $("text-view").style.display = asText ? "block" : "none";
  $("text").textContent = msg.text || t("(no view yet)");
  if (view()) I18N.useScenario(view().scenario.translations);
  renderStatus();
  renderBanner();
  renderHost();
  renderLog();
  renderPhaseBar();
  renderColumns();
  renderReportsPanel();
  const spectator = Boolean(msg.spectator);
  if (spectator) { setTaskHeading(); $("actions-title").textContent = t("Replay"); }
  $("lab-title").textContent = spectator ? t("Every lab") : t("Your lab");
  if (!spectator) $("lab-title").append(" ", h("span", { class: "h-note" }, t("behind your lab shield")));
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
      ? t("Waiting for the host to start the game. Seats: ") + msg.seats.map((s) => `${s.name} (${kindName(s.kind)}${s.taken ? t(", joined") : ""})`).join(", ")
      : t("You have no seat in this game; you see the public event log.")));
    return;
  }
  loadIcons(v.scenario.id);
  for (const id of ["portal", "alliances"]) $(id).closest(".panel").style.display = simplified() ? "none" : "";  // normal game only
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
    parts.push(h("b", {}, t("Round {n}", { n: v.round })), simplified() ? t(" (simplified game)") : "", ` \u00b7 ${t(v.phase)} \u00b7 `, periodStatus(v), " \u00b7 ");
    const waiting = v.current !== null && v.current !== undefined ? [v.current] : v.waiting;
    if (v.result) parts.push(t("game over"));
    else if (msg.status !== "running") parts.push(t("game {status}", { status: t(msg.status) }));
    else parts.push(t("waiting for: "), ...waiting.map((s) => chip(s)));
    if (mustAct()) parts.push(" ", h("span", { class: "you-act" }, t("your move")));
  } else {
    parts.push(`${msg.title} \u00b7 ${t(msg.status)}`);
  }
  const cost = Object.values(msg.ai_cost || {}).reduce((a, b) => a + b, 0);
  if (cost > 0) parts.push(h("span", { class: "muted" }, ` \u00b7 ${t("AI cost {cost} USD", { cost: cost.toFixed(4) })}`));
  if (msg.you !== null) parts.push(h("span", { class: "muted" }, ` \u00b7 ${t("you are")} `), chip(msg.you));
  if (msg.spectator) parts.push(h("span", { class: "you-act" }, replay ? t("replay: action {at} of {total}", { at: replay.at, total: replay.total }) : t("spectating")));
  $("status").innerHTML = "";
  $("status").append(...parts);
  $("actions-panel").classList.toggle("act", mustAct());
}

// The Game Period Deck and the Warning shot or Crisis, always in view in the top row.
function periodStatus(v) {
  const deck = ` (${t("Game Period Deck: {n} left", { n: v.period_deck })})`;
  if (v.crisis) {
    const c = v.crisis;
    return h("span", { class: "bad" }, h("b", {}, t("CRISIS")), " ",
      t("round {round} of {length}, unsuccessful predictions {unsuccessful} of {condition}",
        { round: c.rounds_in_crisis, length: c.crisis_length, unsuccessful: c.unsuccessful, condition: c.crisis_condition }), deck);
  }
  if (v.warning_revealed) return h("span", { class: "warn-shot" }, h("b", {}, t("Warning shot revealed")), deck);
  return h("span", {}, t("Calm period"), deck);
}

function renderBanner() {
  const v = view();
  const box = $("banner");
  box.innerHTML = "";
  const debrief = h("a", { href: `/game/${encodeURIComponent(gameId)}/debrief` }, t("Open the debrief"));
  if (v && v.result && !replay) {
    const r = v.result;
    const winners = (r.winners || []).map((s) => nameOf(s)).join(", ") || t("nobody");
    box.append(h("div", { class: "banner" }, t("Game over: {ending}. Winners: {winners}.", { ending: t(String(r.ending).replace("_", " ")), winners }), " ", debrief));
  } else if (msg.status === "ended") {
    box.append(h("div", { class: "banner" }, t("The host ended this game."), " ", debrief));
  } else if (msg.status === "paused") {
    box.append(h("div", { class: "banner" }, t("The game is paused by the host.")));
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
// Basic mechanics: the simplified game (no publication steps, Talent development, grants, patents,
// students or alliances; new theories and methods are published in Clean-up).
const simplified = () => Boolean(view() && view().mode === "simplified");
const NORMAL_ONLY_PHASES = ["Publication", "Talent development"];
const roundPhases = () => (simplified() ? ROUND_PHASES.filter(([name]) => !NORMAL_ONLY_PHASES.includes(name)) : ROUND_PHASES);

function renderPhaseBar() {
  const v = view();
  const bar = $("phase-bar");
  bar.style.display = v ? "" : "none";
  if (!v) return;
  const phases = roundPhases();
  const now = v.result ? -1 : phases.findIndex(([, steps]) => steps.includes(v.phase));
  fill(bar, h("span", { class: "phase-label" }, t("This round")), phases.map(([name], i) =>
    h("span", { class: `phase-step${now < 0 ? "" : i < now ? " done" : i === now ? " now" : ""}`, title: i === now ? t("The current phase") : null }, h("b", {}, String(i + 1)), t(name))));
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
const taskOrder = (task) => (TASK_ORDER.includes(task) ? TASK_ORDER.indexOf(task) : TASK_ORDER.length);
const tTask = (task) => t(task.replace("_", " "));      // a staff task's name, translated
const tWhen = (task) => (TASK_WHEN[task] ? t(TASK_WHEN[task]) : "");

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
  const capacity = me.lab_capacity === null ? "" : ` \u00b7 ${t("Lab capacity {n}", { n: me.lab_capacity })}`;
  const money = t("Credit {credit} \u00b7 money {money}", { credit: me.credit, money: me.money });
  if (simplified()) box.append(h("p", {}, money, capacity, h("br"), t("{n} postdoc(s)", { n: me.postdocs })));
  else box.append(h("p", {}, money, ` \u00b7 ${t("Grant {grant} \u00b7 Talent {talent}", { grant: me.grant_position, talent: me.talent_position })}`, capacity,
    h("br"), t("{postdocs} postdoc(s), {students} student(s) \u00b7 {patents} patent(s)", { postdocs: me.postdocs, students: me.students, patents: me.patents })));
  const staff = Object.entries(me.staff).filter(([, c]) => c.postdocs + c.students)
    .sort(([a], [b]) => taskOrder(a) - taskOrder(b));
  if (staff.length) {
    const now = STEP_ORDER.indexOf(v.phase);
    box.append(h("table", {},
      h("tr", {}, [t("Task"), t("P"), t("S"), t("Used")].map((x) => h("th", {}, x))),
      staff.map(([task, c]) => {
        const steps = TASK_STEPS[task] || [];
        const first = Math.min(...steps.map((p) => STEP_ORDER.indexOf(p)));
        const last = Math.max(...steps.map((p) => STEP_ORDER.indexOf(p)));
        const cls = now < 0 || !steps.length ? "" : now > last ? "past" : now >= first ? "current" : "";
        const name = task.replace("_", " ");
        const when = TASK_WHEN[task] && TASK_WHEN[task].toLowerCase() !== name ? h("div", { class: "muted" }, tWhen(task)) : null;
        return h("tr", { class: cls }, h("td", {}, tTask(task), when), [c.postdocs, c.students, c.used].map((x) => h("td", {}, x)));
      })));
  }
  if (lab.leaving_students) box.append(h("p", { class: "bad" }, t("{n} student(s) must leave.", { n: lab.leaving_students })));
  const pending = lab.pending;
  if (pending.allocation) {
    const a = pending.allocation;
    box.append(h("p", { class: "small" }, t("Planned staff: hire {hire} postdoc(s), fire {fire}, hire {students} student(s); ",
      { hire: a.hire_postdocs, fire: a.fire_postdocs, students: a.hire_students })
      + Object.entries(a.allocation).map(([task, c]) => `${tTask(task)} ${t("{p}p+{s}s", { p: c.postdocs, s: c.students })}`).join(", ")));
  }
  if (pending.leaving_students) box.append(h("p", { class: "small" }, t("Leaving students chosen: {list}", { list: values(pending.leaving_students) })));
}

function renderTracks() {
  const v = view();
  const who = (r) => h("span", {}, chip(r.seat), r.committed ? h("span", { class: "muted" }, ` ${t("ready")}`) : null);
  if (simplified()) {
    fill($("tracks"), table(["", t("Credit"), t("Money"), t("Lab"), t("Postdocs")],
      v.researchers.map((r) => [who(r), r.credit, r.money, r.lab_capacity ?? "\u2013", r.postdocs])));
    return;
  }
  const rows = v.researchers.map((r) => [
    who(r), r.credit, r.money, r.grant_position, r.talent_position, r.lab_capacity ?? "\u2013", t("{p}p {s}s", { p: r.postdocs, s: r.students }), r.patents,
  ]);
  fill($("tracks"), table(["", t("Credit"), t("Money"), t("Grant"), t("Talent"), t("Lab"), t("Staff"), t("Pat.")], rows));
}

function renderAlliances() {
  const v = view();
  const allies = v.alliances.map((pair) => `${nameOf(pair[0])} + ${nameOf(pair[1])}`);
  const option = msg.options.find((o) => o.type === "alliance");
  fill($("alliances"),
    h("p", { class: allies.length ? "" : "muted" }, allies.length ? allies.join(", ") : t("No alliances.")),
    v.proposals.length ? h("p", {}, t("Proposed: ") + v.proposals.map(([a, b]) => `${nameOf(a)} -> ${nameOf(b)}`).join(", ")) : null,
    option ? completeActions(option) : null,
  );
}

function renderMethods() {
  const methods = view().published.filter((p) => p.kind === "method").sort((a, b) => ownFirst(a, b) || a.id - b.id);
  fill($("methods"), methods.length ? methods.map((m) => h("div", {}, `M${m.id} ${m.parameter} `, chip(m.author), " ", t("tier {n}", { n: m.tier }),
    m.open_access ? ` ${t("open access")}` : "", m.fresh ? ` ${t("fresh")}` : "")) : h("span", { class: "muted" }, t("None published yet.")));
}

function renderPredictions() {
  const v = view();
  const rows = v.predictions.map((p) => h("div", {}, `Q${p.id} `, chip(p.seat), " ", t("T{theory} on P{probe}", { theory: p.theory, probe: p.probe + 1 }),
    p.preregistered ? `, ${t("preregistered")}` : "",
    p.success === null || p.success === undefined ? ` (${t(p.status)})` : `: ${p.success ? t("success") : t("failed")}`));
  const hidden = Object.entries(v.hidden_predictions || {}).map(([seat, probes]) =>
    `${nameOf(Number(seat))}: ${Object.entries(probes).map(([p, n]) => t("{n} on P{probe}", { n, probe: Number(p) + 1 })).join(", ")}`);
  fill($("predictions"), rows.length ? rows : h("span", { class: "muted" }, t("None visible yet.")),
    hidden.length ? h("p", { class: "small" }, t("Hidden predictions: ") + hidden.join("; ")) : null);
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
    h("option", { value: "" }, t("jump to round...")),
    (rounds || []).map((r) => h("option", { value: r.seq, selected: current && current.seq === r.seq && replay ? true : null }, t("round {round} (action {seq})", { round: r.round, seq: r.seq }))));
  box.append(
    h("p", {}, replay ? t("Showing the game after action {at} of {total}.", { at, total }) : t("Live: {total} action(s) so far.", { total })),
    h("div", { class: "replay" },
      h("button", { onclick: () => showReplay(0) }, t("|< start")),
      h("button", { onclick: () => showReplay(Math.max(0, at - 1)) }, t("< back")),
      h("button", { onclick: () => showReplay(Math.min(total, at + 1)) }, t("forward >")),
      h("button", { class: replay ? "primary" : "", onclick: goLive }, t("live >|")),
      select,
      ` ${t("action")} `, number, ` ${t("of {total}", { total })} `,
      h("button", { onclick: () => showReplay(Number(number.value)) }, t("go"))),
    h("p", { class: "small" }, h("a", { href: `/game/${encodeURIComponent(gameId)}/debrief` }, t("Open the debrief")),
      msg.view && msg.view.result ? "" : ` ${t("(so far: spectators may look before the end)")}`),
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
  box.append(h("p", { class: "small" }, t("Join link:"), " ", h("input", { value: link, readonly: true, size: 40 })));
  const buttons = [];
  if (msg.status === "lobby") buttons.push(h("button", { class: "primary", onclick: () => hostCommand("start") }, t("Start the game")));
  if (msg.status === "running") buttons.push(h("button", { onclick: () => hostCommand("pause") }, t("Pause")));
  if (msg.status === "paused") buttons.push(h("button", { class: "primary", onclick: () => hostCommand("resume") }, t("Resume")));
  if (["running", "paused"].includes(msg.status)) buttons.push(h("button", { onclick: () => { if (confirm(t("End the game for everyone?"))) hostCommand("end"); } }, t("End the game")));
  box.append(h("div", {}, buttons));
  const rows = msg.seats.map((s) => {
    const controls = [];
    if (s.human_seat) {
      const kinds = h("select", {}, lobbyOptions.seat_kinds.filter((k) => k !== "human").map((k) => h("option", { value: k }, kindName(k))));
      if (s.kind === "human") controls.push(kinds, h("button", { onclick: () => hostCommand("automate", { seat: s.seat, kind: kinds.value }) }, t("Hand to automated player")));
      else controls.push(h("button", { onclick: () => hostCommand("release", { seat: s.seat }) }, t("Give back to the person")));
      if (s.taken) controls.push(h("button", { onclick: () => hostCommand("remove", { seat: s.seat }) }, t("Free the seat")));
    }
    return [chip(s.seat), kindName(s.kind), s.human_seat ? (s.taken ? (s.connected ? t("connected") : t("joined, not connected")) : t("free")) : t("automated"), h("span", {}, controls)];
  });
  box.append(table([t("Seat"), t("Played by"), t("Person"), ""], rows));
  if (msg.you === null && store.get("seat") === "") box.append(h("p", {}, h("button", { onclick: showJoin }, t("Take a seat yourself"))));
  if (store.get("seat")) {
    const watching = store.get("spectate") === "1";
    box.append(h("p", {}, h("button", { onclick: () => { store.set("spectate", watching ? "" : "1"); reconnect(); } },
      watching ? t("Back to my seat") : t("Watch as spectator (see every lab and the hidden world)"))));
  }
}

// Start ------------------------------------------------------------------------------------------
I18N.translatePage();
I18N.initChoice();
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

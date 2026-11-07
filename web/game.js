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

let msg = null;          // the latest message from the server
let socket = null;
let lobbyOptions = null; // seat kinds, for the host's "hand over" control
let refused = false;     // the server would not let this browser in

// Small helpers -----------------------------------------------------------------------------------
function fill(node, ...children) {  // append children, skipping empty ones (null would show as "null")
  node.innerHTML = "";
  node.append(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
}
function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "onclick" || k === "onchange" || k === "oninput") node[k] = v;
    else if (k === "class") node.className = v;
    else if (v !== false && v !== null && v !== undefined) node.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children.flat()) {
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
const theoryText = (i) => (i.kind === "method" ? `method for ${i.parameter}` : `${values(i.inputs)} -> ${values(i.outcomes)}`);
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
  if (store.get("host")) panel.append(h("p", {}, h("button", { onclick: () => { box.style.display = "none"; $("board").style.display = ""; connect(); } }, "Continue as host without a seat")));
  box.innerHTML = "";
  box.append(panel);
}

// Connection ------------------------------------------------------------------------------------
function connect() {
  const query = new URLSearchParams({ seat_token: store.get("seat"), host_token: store.get("host") });
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${location.host}/ws/${gameId}?${query}`);
  socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "error") {
      showError(data.message);
      if (!msg) refused = true;  // no seat and not the host: show the join form instead of reconnecting
      return;
    }
    if (data.type === "accepted") { showError(""); return; }
    if (data.type === "state" && (!msg || data.seq >= msg.seq || data.status !== msg.status || data.you !== msg.you)) {
      msg = data;
      render();
    }
  };
  socket.onclose = () => {
    if (refused) { store.set("seat", ""); showJoin(); return; }
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
  const v = view();
  if (!v) {
    for (const id of ["actions", "grid", "literature", "portal", "predictions", "lab", "tracks"]) $(id).innerHTML = "";
    $("actions").append(h("p", { class: "muted" }, msg.status === "lobby"
      ? "Waiting for the host to start the game. Seats: " + msg.seats.map((s) => `${s.name} (${s.kind}${s.taken ? ", joined" : ""})`).join(", ")
      : "You have no seat in this game; you see the public event log."));
    return;
  }
  renderActions();
  renderGrid();
  renderLab();
  renderLiterature();
  renderPortal();
  renderPredictions();
  renderTracks();
}

function renderStatus() {
  const v = view();
  const parts = [];
  if (v) {
    parts.push(h("b", {}, `Round ${v.round}`), ` \u00b7 ${v.phase} \u00b7 ${v.period === "crisis" ? "CRISIS" : "Calm period"} \u00b7 `);
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
  $("status").innerHTML = "";
  $("status").append(...parts);
  $("actions-panel").classList.toggle("act", mustAct());
}

function renderBanner() {
  const v = view();
  const box = $("banner");
  box.innerHTML = "";
  if (v && v.result) {
    const r = v.result;
    const winners = (r.winners || []).map((s) => nameOf(s)).join(", ") || "nobody";
    box.append(h("div", { class: "banner" }, `Game over: ${String(r.ending).replace("_", " ")}. Winners: ${winners}.`));
  } else if (msg.status === "ended") {
    box.append(h("div", { class: "banner" }, "The host ended this game."));
  } else if (msg.status === "paused") {
    box.append(h("div", { class: "banner" }, "The game is paused by the host."));
  }
}

function renderGrid() {
  const v = view();
  const head = [h("th", {}, "")];
  for (const p of v.probes) {
    const marks = [];
    if (p.hot_topic) marks.push("hot topic");
    head.push(h("th", { class: p.hot_topic ? "hot" : "" }, `P${p.index + 1}`,
      marks.length ? h("div", { class: "small" }, marks.join(", ")) : null,
      p.probe_time !== null ? h("div", {}, chip(p.probe_time)) : null));
  }
  const rows = v.variables.map((variable) => {
    const cells = [h("th", {}, `${variable.id} ${variable.name}`)];
    for (const p of v.probes) {
      let text = "";
      let cls = "";
      if (variable.kind === "input") {
        // Before the Probe stacks are dealt, say what each slot will show: Specialty (always
        // revealed), a sensor of some level (revealed, with noise), or nothing (a blank card).
        const sensor = p.sensors[variable.id];
        const specialty = p.specialty.includes(variable.id);
        cls = specialty ? "specialty" : sensor ? "sensor" : "unsensed";
        const status = specialty ? "revealed" : sensor ? `sensor L${sensor}` : "no sensor";
        if (p.readings) text = (p.readings[variable.id] ?? "blank") + (sensor ? ` (sensor L${sensor})` : "");
        else text = status;
      } else {
        text = p.outcomes ? p.outcomes[variable.id] : "hidden";
        if (!p.outcomes) cls = "hidden";
      }
      cells.push(h("td", { class: cls }, text));
    }
    return h("tr", {}, cells);
  });
  fill($("grid"), h("table", { class: "grid" }, h("tr", {}, head), rows),
    h("p", { class: "muted small legend" },
      h("span", { class: "specialty" }, "Specialty"), " always revealed and true \u00b7 ",
      h("span", { class: "sensor" }, "sensor L1-L3"), " revealed, may be noise \u00b7 ",
      h("span", { class: "unsensed" }, "no sensor"), " shows blank: a sensor can go here"));
}

// The engine's steps in round order (nv_core.state.Phase), and the steps where each staff task
// works. Talent development and Grants work after the last step (Talent development and
// Clean-up phases), so they are never "past" within a round.
const STEP_ORDER = ["Hiring and task allocation phase", "Alliance: last chance to leave", "Student task check phase",
  "Experimentation and equipment phase", "Probe time", "Formulating predictions and preregistration",
  "Outcome and Prediction Reveal", "Scoring predictions: order", "Development phase",
  "Publication: submission and revisions", "Publication: peer review"];
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
  const me = v.researchers[msg.you];
  const lab = v.lab;
  const box = $("lab");
  box.innerHTML = "";
  box.append(h("p", {}, `Academic credit ${me.credit} \u00b7 money ${me.money} \u00b7 Grant position ${me.grant_position} \u00b7 `
    + `Talent ${me.talent_position} \u00b7 ${me.postdocs} postdoc(s), ${me.students} student(s) \u00b7 ${me.patents} patent(s)`));
  const staff = Object.entries(me.staff).filter(([, c]) => c.postdocs + c.students)
    .sort(([a], [b]) => taskOrder(a) - taskOrder(b));
  if (staff.length) {
    const now = STEP_ORDER.indexOf(v.phase);
    box.append(h("h3", {}, "Staff this round"), h("table", {},
      h("tr", {}, ["Task", "When", "Postdocs", "Students", "Used"].map((x) => h("th", {}, x))),
      staff.map(([t, c]) => {
        const steps = TASK_STEPS[t] || [];
        const first = Math.min(...steps.map((p) => STEP_ORDER.indexOf(p)));
        const last = Math.max(...steps.map((p) => STEP_ORDER.indexOf(p)));
        const cls = now < 0 || !steps.length ? "" : now > last ? "past" : now >= first ? "current" : "";
        return h("tr", { class: cls }, [t.replace("_", " "), TASK_WHEN[t] || "", c.postdocs, c.students, c.used].map((x) => h("td", {}, x)));
      })));
  }
  if (lab.leaving_students) box.append(h("p", { class: "bad" }, `${lab.leaving_students} student(s) must leave.`));
  if (lab.ideas.length) {
    box.append(h("h3", {}, "Development stacks (unpublished)"),
      h("ul", {}, lab.ideas.map((i) => h("li", {}, `D${i.id}: ${theoryText(i)}`))));
  }
  const pending = lab.pending;
  if (pending.development.length) {
    box.append(h("h3", {}, "Chosen this phase"), h("ul", {}, pending.development.map((i) => h("li", {}, theoryText(i)))));
  }
  if (pending.allocation) {
    const a = pending.allocation;
    box.append(h("p", { class: "small" }, `Planned staff: hire ${a.hire_postdocs} postdoc(s), fire ${a.fire_postdocs}, hire ${a.hire_students} student(s); `
      + Object.entries(a.allocation).map(([t, c]) => `${t} ${c.postdocs}p+${c.students}s`).join(", ")));
  }
  if (pending.leaving_students) box.append(h("p", { class: "small" }, `Leaving students chosen: ${values(pending.leaving_students)}`));
  if (lab.experiments.length) {
    box.append(h("h3", {}, "This round's experiments"),
      table(["Experiment", "Inputs", "Outcomes", "Specified"], lab.experiments.map((e) => [`E${e.id}`, values(e.inputs), values(e.outcomes), Object.keys(e.specified).join(", ")])));
  }
  for (const area of ["fresh", "stale"]) {
    const records = lab[area];
    const rows = [
      ...records.observations.map((o) => [`O${o.id}`, `P${o.probe + 1}, round ${o.round}`, values(o.cards)]),
      ...records.experiments.map((e) => [`E${e.id}`, "experiment", values(e.cards)]),
    ];
    if (rows.length) box.append(h("h3", {}, `${area} records`), table(["Record", "From", "Cards"], rows));
  }
  const mine = v.predictions.filter((p) => p.seat === msg.you);
  if (mine.length) {
    box.append(h("h3", {}, "Your predictions this round"),
      table(["Prediction", "Theory", "Probe", "Preregistered", "Status", "Result"],
        mine.map((p) => [`Q${p.id}`, `T${p.theory}`, `P${p.probe + 1}`, p.preregistered ? "yes" : "no", p.status, p.success === null ? "" : (p.success ? "success" : "failed")])));
  }
}

function renderLiterature() {
  const v = view();
  const rows = v.published.map((p) => [
    `${p.kind === "theory" ? "T" : "M"}${p.id}`, chip(p.author), p.tier + (p.open_access ? " (open access)" : ""),
    theoryText(p), p.kind === "theory" ? `${p.nobel} / ${v.nobel_condition}` : "",
    p.kind === "theory" ? `${p.retraction} / ${v.retraction_threshold}` : "",
    [p.fresh ? "fresh out of print" : "", p.sideways ? "cited this round" : "", p.patents.length ? `${p.patents.length} patent(s)` : ""].filter(Boolean).join(", "),
  ]);
  fill($("literature"), rows.length ? table(["Paper", "Author", "Tier", "Content", "Nobel", "Retraction", ""], rows) : h("p", { class: "muted" }, "Nothing published yet."));
}

// Peer review: each of my non-zero allocation cards names a position in the Awaiting peer review area.
function myReviewCards() {
  const v = view();
  return (msg.you !== null && v.review_cards && v.review_cards[String(msg.you)]) || [];
}
const manuscriptUnderReview = (position) => view().manuscripts.find((m) => m.area === "review" && m.position === position);
function reviewLabel(card) {
  const position = myReviewCards()[card];
  const m = manuscriptUnderReview(position);
  const twice = myReviewCards().filter((c) => c === position).length > 1 ? `, your card ${card + 1}` : "";
  return (m ? `D${m.id} (awaiting peer review #${position}${twice})` : `awaiting peer review #${position}${twice}`);
}
function recordList(m) {
  if (!m.record_cards) return m.records;
  return h("div", {}, `${m.records} record(s):`, m.record_cards.map((r) => h("div", { class: "small" }, `${r.kind}: ${values(r.cards)}`)));
}

function renderPortal() {
  const v = view();
  const reviewing = new Set(myReviewCards().filter(Boolean));
  const rows = v.manuscripts.map((m) => [
    `D${m.id}`, chip(m.author), m.tier,
    h("span", {}, m.area + (m.position ? ` #${m.position}` : ""),
      m.area === "review" && reviewing.has(m.position) ? h("div", { class: "hot" }, "you review this") : null),
    m.area === "accept" ? `${m.tokens} round(s) to go` : "", m.votes, recordList(m),
    m.content ? theoryText(m.content) : "(face down)",
  ]);
  fill($("portal"), rows.length ? table(["Manuscript", "Author", "Tier", "Area", "Processing", "Votes", "Records", "Content"], rows) : h("p", { class: "muted" }, "No manuscripts."));
}

function renderPredictions() {
  const v = view();
  const rows = v.predictions.filter((p) => p.seat !== msg.you || !["hidden"].includes(p.status)).map((p) => [
    `Q${p.id}`, chip(p.seat), `T${p.theory}`, `P${p.probe + 1}`, p.preregistered ? "preregistered" : "", p.status,
    p.success === null || p.success === undefined ? "" : (p.success ? "success" : "failed"),
  ]);
  const hidden = Object.entries(v.hidden_predictions || {}).map(([seat, probes]) =>
    `${nameOf(Number(seat))}: ${Object.entries(probes).map(([p, n]) => `${n} on P${Number(p) + 1}`).join(", ")}`);
  fill($("predictions"), rows.length ? table(["Prediction", "Researcher", "Theory", "Probe", "", "Status", "Result"], rows) : h("p", { class: "muted" }, "No public predictions this round."),
    hidden.length ? h("p", { class: "small" }, "Hidden predictions: " + hidden.join("; ")) : null);
}

function renderTracks() {
  const v = view();
  const rows = v.researchers.map((r) => [
    chip(r.seat), r.credit, r.money, r.grant_position, r.talent_position, `${r.postdocs}p / ${r.students}s`, r.patents,
    v.alliances.filter((pair) => pair.includes(r.seat)).map((pair) => nameOf(pair[0] === r.seat ? pair[1] : pair[0])).join(", "),
    r.committed ? "ready" : "",
  ]);
  const crisis = v.crisis
    ? `Crisis: round ${v.crisis.rounds_in_crisis} of ${v.crisis.crisis_length}, unsuccessful predictions ${v.crisis.unsuccessful} of ${v.crisis.crisis_condition}`
    : (v.warning_revealed ? "The Warning shot has been revealed." : "Calm period.");
  fill($("tracks"),
    table(["Researcher", "Credit", "Money", "Grant", "Talent", "Staff", "Patents", "Allies", ""], rows),
    h("p", {}, `Game Period Deck: ${v.period_deck} card(s) left. ${crisis}`),
    v.proposals.length ? h("p", { class: "small" }, "Alliance proposals: " + v.proposals.map(([a, b]) => `${nameOf(a)} -> ${nameOf(b)}`).join(", ")) : null,
  );
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

// Actions ---------------------------------------------------------------------------------------
function describe(a) {
  const n = (seat) => nameOf(seat);
  switch (a.type) {
    case "commit": return "Commit: my choices for this step are final";
    case "pass": return "Pass: stop experimenting this round";
    case "claim_probe_time": return `Take Probe time on P${a.probe + 1}`;
    case "make_prediction": return `Predict with T${a.theory}${paperAuthor(a.theory)} on P${a.probe + 1}${a.preregister ? " (preregistered)" : ""}`;
    case "cancel_prediction": return `Withdraw prediction Q${a.prediction}`;
    case "set_preregistered": return `${a.preregister ? "Preregister" : "Un-preregister"} Q${a.prediction}`;
    case "reveal_prediction": return a.reveal ? `Reveal Q${a.prediction}` : `Keep Q${a.prediction} hidden after all`;
    case "develop_method": return `Develop a method for ${a.parameter}`;
    case "cancel_development": return `Drop development choice ${a.index + 1}`;
    case "revise": return `Revise manuscript D${a.manuscript}`;
    case "withdraw_submission": return `Withdraw D${a.manuscript} (undo this step's submission or revision)`;
    case "review_vote": return `Review ${reviewLabel(a.card)}: ${a.vote}`;
    case "propose_alliance": return `Propose an alliance to ${n(a.partner)}`;
    case "accept_alliance": return `Accept the alliance with ${n(a.partner)}`;
    case "leave_alliance": return `Leave the alliance with ${n(a.partner)}`;
    case "stay_in_alliance": return `Stay in the alliance with ${n(a.partner)}`;
    default: return JSON.stringify(a);
  }
}

function paperAuthor(id) {  // " (name)" or " (name, your own)" for a published paper
  const paper = view().published.find((p) => p.id === id);
  if (!paper) return "";
  return ` (${nameOf(paper.author)}${paper.author === msg.you ? ", your own" : ""})`;
}

function predictionContext(a) {  // what a theory says, for prediction choices
  const paper = view().published.find((p) => p.id === a.theory);
  return paper ? ` - ${theoryText(paper)}` : "";
}

function reviewForm(option) {  // one block per allocation card: the manuscript, its records, the two votes
  const chosen = view().lab.pending.votes || {};
  const cards = [...new Set(option.actions.map((a) => a.card))];
  return cards.map((card) => {
    const m = manuscriptUnderReview(myReviewCards()[card]);
    const vote = chosen[String(card)];
    return h("div", { class: "form-row" },
      h("b", {}, reviewLabel(card)),
      m ? h("div", { class: "small" }, chip(m.author), ` tier ${m.tier}: `, m.content ? theoryText(m.content) : "(face down)") : null,
      m ? h("div", { class: "small" }, recordList(m)) : null,
      option.actions.filter((a) => a.card === card).map((a) =>
        h("button", { class: vote === a.vote ? "primary" : "", onclick: () => send(a) }, a.vote)),
      h("span", { class: "muted small" }, vote ? ` chosen: ${vote}` : " not voted yet"));
  });
}

function completeActions(option) {
  const items = option.actions;
  if (items.length <= 8) {
    return items.map((a) => h("button", { class: a.type === "commit" ? "primary" : "", onclick: () => send(a) },
      describe(a) + (a.type === "make_prediction" ? predictionContext(a) : "")));
  }
  const select = h("select", {}, items.map((a, i) => h("option", { value: i }, describe(a) + (a.type === "make_prediction" ? predictionContext(a) : ""))));
  return [select, h("button", { onclick: () => send(items[Number(select.value)]) }, "Do it")];
}

function numberInput(value, min, max) {
  return h("input", { type: "number", value, min, max: max === null || max === undefined ? false : max });
}

function allocateForm(t) {
  const pending = view().lab.pending.allocation;
  const now = t.postdocs_now;
  const [low, high] = t.postdocs_after;
  const postdocs = numberInput(pending ? now + pending.hire_postdocs - pending.fire_postdocs : now, low, high);
  const students = numberInput(pending ? pending.hire_students : 0, 0, t.max_students);
  const inputs = {};
  const rows = [...t.tasks].sort((a, b) => taskOrder(a) - taskOrder(b)).map((task) => {
    const current = pending && pending.allocation[task] ? pending.allocation[task] : { postdocs: 0, students: 0 };
    const p = numberInput(current.postdocs, 0, task === "talent_development" ? 1 : null);
    const s = numberInput(current.students, 0, null);
    if (t.postdoc_only.includes(task)) s.disabled = true;
    inputs[task] = [p, s];
    return [task.replace("_", " "), TASK_WHEN[task] || "", p, s];
  });
  const button = h("button", { onclick: () => {
    const after = Number(postdocs.value);
    const allocation = {};
    for (const [task, [p, s]] of Object.entries(inputs)) {
      const count = { postdocs: Number(p.value) || 0, students: Number(s.value) || 0 };
      if (count.postdocs || count.students) allocation[task] = count;
    }
    send({ type: "allocate_staff", hire_postdocs: Math.max(0, after - now), fire_postdocs: Math.max(0, now - after),
      hire_students: Number(students.value) || 0, allocation });
  } }, "Set staff allocation");
  return [
    h("div", { class: "form-row" }, `You have ${now} postdoc(s). Postdocs after hiring/firing: `, postdocs,
      ` (${low} to ${high === null ? "any" : high}) \u00b7 students to hire: `, students, ` (at most ${t.max_students})`),
    table(["Task", "When", "Postdocs", "Students"], rows),
    h("div", { class: "small muted" }, "Every staff member needs a task; Development and Talent development take postdocs only; at most one on Talent development."),
    button,
  ];
}

function leavingForm(t) {
  const inputs = Object.entries(t.students_by_task).sort(([a], [b]) => taskOrder(a) - taskOrder(b))
    .map(([task, n]) => [task, numberInput(0, 0, n), n]);
  return [
    h("p", {}, `${t.count} student(s) must leave. Choose from which tasks:`),
    table(["Task", "When", "Students there", "Leaving"], inputs.map(([task, input, n]) => [task.replace("_", " "), TASK_WHEN[task] || "", n, input])),
    h("button", { onclick: () => {
      const by_task = {};
      for (const [task, input] of inputs) if (Number(input.value)) by_task[task] = Number(input.value);
      send({ type: "choose_leaving_students", by_task });
    } }, "Choose"),
  ];
}

function experimentForm(t) {
  const selects = Object.entries(t.states).map(([param, states]) =>
    [param, h("select", {}, h("option", { value: "" }, "drawn at random"), states.map((s) => h("option", { value: s }, s)))]);
  const methods = t.methods.map((m) => [m, h("input", { type: "checkbox" })]);
  return [
    h("p", { class: "small" }, `Specify up to ${t.free_input_parameters} input states for free, plus one per cited method (${t.rule}).`),
    table(["Input parameter", "State"], selects.map(([p, s]) => [p, s])),
    methods.length ? h("div", { class: "form-row" }, "Cite methods: ", methods.map(([m, box]) => h("label", {}, box, ` M${m.id} (${m.parameter}) `))) : null,
    h("button", { onclick: () => {
      const specified = {};
      for (const [param, select] of selects) if (select.value) specified[param] = select.value;
      send({ type: "run_experiment", specified, cited_methods: methods.filter(([, box]) => box.checked).map(([m]) => m.id) });
    } }, "Run the experiment"),
  ];
}

function sensorForm(t) {
  return t.choices.map((c) => {
    const boxes = c.methods.map((id) => [id, h("input", { type: "checkbox" })]);
    return h("div", { class: "form-row" }, `P${c.probe + 1} ${c.parameter}: cite ${c.methods_needed} method(s) `,
      boxes.map(([id, box]) => h("label", {}, box, ` M${id} `)),
      h("button", { onclick: () => send({ type: "install_sensor", probe: c.probe, parameter: c.parameter,
        cited_methods: boxes.filter(([, b]) => b.checked).map(([id]) => id) }) }, "Install / upgrade sensor"));
  });
}

function theoryForm(t) {
  const pick = (group) => Object.entries(group).map(([v, states]) =>
    [v, h("select", {}, h("option", { value: "" }, "blank"), states.map((s) => h("option", { value: s }, s)))]);
  const inputs = pick(t.inputs);
  const outcomes = pick(t.outcomes);
  const chosen = (list) => Object.fromEntries(list.filter(([, s]) => s.value).map(([v, s]) => [v, s.value]));
  return [
    table(["Row", "State"], [...inputs, ...outcomes].map(([v, s]) => [v, s])),
    h("button", { onclick: () => send({ type: "formulate_theory", inputs: chosen(inputs), outcomes: chosen(outcomes) }) }, "Formulate this theory"),
  ];
}

function recordText(r) {
  return r.kind === "observation" ? `O${r.observation}` : `experiment cards ${r.cards.map(([e, v]) => `E${e}:${v}`).join(" ")}`;
}

function submitForm(option) {
  const t = option.template;
  return option.actions.map((a) => {
    const spare = (t.spare_records[`${a.manuscript}/${a.tier}`] || []).map((r) => [r, h("input", { type: "checkbox" })]);
    const apc = t.apc[String(a.tier)];
    const apcBox = h("input", { type: "checkbox" });
    return h("div", { class: "option" },
      `D${a.manuscript} to tier ${a.tier} with ${a.records.length ? a.records.map(recordText).join(", ") : "no records"}. `,
      spare.length ? h("div", { class: "small" }, "Add spare records (each extra record shortens processing): ",
        spare.map(([r, box]) => h("label", {}, box, ` ${recordText(r)} `))) : null,
      apc > 0 ? h("label", { class: "small" }, apcBox, ` pay the article processing charge (${apc}; you can spend ${t.spendable}) `) : null,
      h("button", { onclick: () => send({ ...a, records: [...a.records, ...spare.filter(([, b]) => b.checked).map(([r]) => r)], pay_apc: apcBox.checked }) }, "Submit"));
  });
}

function orderForm(t) {
  const input = h("input", { value: t.predictions.map((id) => `Q${id}`).join(", "), size: 30 });
  return [h("p", { class: "small" }, "Several of your predictions are on the same Probe: the order in which they are scored."), input,
    h("button", { onclick: () => send({ type: "order_predictions", order: input.value.split(",").map((x) => Number(x.trim().replace(/^Q/, ""))) }) }, "Set the order")];
}

const TITLES = {
  allocate_staff: "Hiring and task allocation", choose_leaving_students: "Student task check", run_experiment: "Run an experiment",
  install_sensor: "Install or upgrade a sensor", pass: "Pass", claim_probe_time: "Probe time", make_prediction: "Make a prediction",
  cancel_prediction: "Withdraw a prediction", set_preregistered: "Preregistration", reveal_prediction: "Reveal predictions",
  order_predictions: "Scoring order", formulate_theory: "Formulate a theory", develop_method: "Develop a method",
  cancel_development: "Change your development choices", submit: "Submit a manuscript", revise: "Revise a manuscript", withdraw_submission: "Change your mind",
  review_vote: "Peer review", alliance: "Alliances", leave_alliance: "Last chance to leave an alliance",
  stay_in_alliance: "Stay in an alliance", commit: "Done?",
};

function renderActions() {
  const box = $("actions");
  box.innerHTML = "";
  if (view().result || msg.status !== "running") { box.append(h("p", { class: "muted" }, "Nothing to do.")); return; }
  if (!msg.options.length) {
    box.append(h("p", { class: "muted" }, msg.seats[msg.you] && msg.seats[msg.you].kind !== "human"
      ? `Your seat is played by an automated player (${msg.seats[msg.you].kind}) for now.` : "Nothing to do right now; others are deciding."));
    return;
  }
  const order = (o) => (o.type === "commit" ? 2 : o.type === "alliance" ? 1 : 0);
  for (const option of [...msg.options].sort((a, b) => order(a) - order(b))) {
    let body;
    if (option.type === "allocate_staff") body = allocateForm(option.template);
    else if (option.type === "choose_leaving_students") body = leavingForm(option.template);
    else if (option.type === "run_experiment") body = experimentForm(option.template);
    else if (option.type === "install_sensor") body = sensorForm(option.template);
    else if (option.type === "formulate_theory") body = theoryForm(option.template);
    else if (option.type === "submit") body = submitForm(option);
    else if (option.type === "order_predictions") body = orderForm(option.template);
    else if (option.type === "review_vote") body = reviewForm(option);
    else body = completeActions(option);
    box.append(h("div", { class: "option" }, h("h3", {}, TITLES[option.type] || option.type), body));
  }
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
}

// Start ------------------------------------------------------------------------------------------
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

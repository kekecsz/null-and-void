// The board (specification 7.4): everything that holds world states is one horizontal strip, in
// one shared column order, so the panels line up. This file draws the strips and the panels that
// are lists of strips; tasks.js draws what the player can do now; game.js connects them.
"use strict";

// Remembered for each player in this browser, across games: tile style, pinning, minimised panels.
const prefs = (() => {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("nv:board") || "{}") || {}; } catch { /* private window */ }
  return { tiles: saved.tiles === "compact" ? "compact" : "tall", pinTask: saved.pinTask !== false, pinSelection: saved.pinSelection !== false, closed: saved.closed || {} };
})();
function savePrefs() {
  try { localStorage.setItem("nv:board", JSON.stringify(prefs)); } catch { /* private window */ }
}

// Icons: one tile per state, made by asset_generation/make_icons.py. A scenario without icons
// simply shows the state names.
let iconScenario = null;
let iconColours = {};
async function loadIcons(scenario) {
  if (scenario === iconScenario) return;
  iconScenario = scenario;
  iconColours = {};
  try {
    const response = await fetch(`/web/icons/${encodeURIComponent(scenario)}/colours.json`);
    if (!response.ok) return;
    iconColours = await response.json();
    actionsShown = null;  // the task panel is otherwise kept as it is
    if (msg) render();
  } catch { /* names only */ }
}
const iconUrl = (state) => `/web/icons/${encodeURIComponent(iconScenario)}/${encodeURIComponent(state.replaceAll(" ", "_"))}.png`;

const inputVars = () => view().variables.filter((x) => x.kind === "input");
const outcomeVars = () => view().variables.filter((x) => x.kind !== "input");
const hasStates = (slots) => Object.values(slots || {}).some(Boolean);
const ideaSlots = (i) => ({ ...i.inputs, ...i.outcomes });

// "off": a slot where both strips have a state and the states differ; "same": every slot equal,
// blanks included; otherwise "fits".
function compareSlots(a, b) {
  const ids = view().variables.map((x) => x.id);
  if (ids.some((id) => a[id] && b[id] && a[id] !== b[id])) return "off";
  return ids.every((id) => (a[id] || null) === (b[id] || null)) ? "same" : "fits";
}

// Tiles -------------------------------------------------------------------------------------------
function tile(state, emptyText, kind) {
  if (!state) {
    return h("div", { class: `t empty${kind ? ` ${kind}` : ""}` },
      h("div", { class: "ph" }, emptyText === "hidden" ? "?" : ""), h("span", { class: "n" }, emptyText || "blank"));
  }
  const colours = iconColours[state];
  return h("div", { class: "t", style: colours ? `--c:${colours.background};--ct:${colours.text}` : false },
    colours ? h("img", { src: iconUrl(state), alt: "" }) : h("div", { class: "ph" }, ""),
    h("span", { class: "n" }, state));
}
const cell = (...content) => h("div", { class: "cell" }, content);

// Strips ------------------------------------------------------------------------------------------
const CONTROLS = "button, input, select, label, a";

// o: head, sub, slots, tail; key (what makes two strips "the same strip", default head);
// cellFor(variable) to draw a cell differently; hide (ids shown as "?"); text (a line instead of
// the cells, for what has no world states); toggle (control before the head); inert (no selecting).
function strip(o) {
  const key = o.key || o.head;
  const selectable = !o.inert && hasStates(o.slots);
  const draw = (variable) => {
    if (o.cellFor) return o.cellFor(variable);
    return cell(tile((o.slots || {})[variable.id], o.hide && o.hide.includes(variable.id) ? "hidden" : null));
  };
  const node = h("div", { class: `strip cols${selectable ? " can-select" : ""}`, tabindex: selectable ? 0 : null, role: selectable ? "button" : null },
    h("div", { class: "head" }, o.toggle, h("b", {}, o.head), o.sub ? h("span", { class: "sub" }, o.sub) : null),
    o.text ? h("div", { class: "row-text" }, o.text) : [inputVars().map(draw), h("div", { class: "arrow" }, "\u2192"), outcomeVars().map(draw)],
    h("div", { class: "tail" }, o.tail));
  if (selectable) {
    node.stripInfo = { id: key, slots: o.slots, label: o.head, sub: o.sub };
    const select = () => { selected = selected && selected.id === key ? null : node.stripInfo; refreshHighlights(); };
    node.onclick = (e) => { if (!e.target.closest(CONTROLS)) select(); };
    node.onkeydown = (e) => { if (e.key === "Enter" && e.target === node) select(); };
  }
  return node;
}

// A submission or a manuscript: a strip that opens into a box showing its records. o: id, top
// (what strip() takes), records (rows for strip()), foot, target.
function boxView(o) {
  const isOpen = task.open.has(o.id);
  const toggle = o.records.length || o.foot
    ? h("button", { class: "toggle", title: isOpen ? "Minimise to a strip" : "Show the supporting records",
      onclick: () => { if (isOpen) task.open.delete(o.id); else task.open.add(o.id); redraw(); } }, isOpen ? "\u25be" : "\u25b8")
    : null;
  return h("div", { class: `box${o.target ? " is-target" : ""}`, onclick: o.onclick },
    strip({ ...o.top, toggle }),
    isOpen && o.records.length ? h("div", { class: "box-rows" }, o.records.map((r) => strip(r))) : null,
    isOpen && o.foot ? h("div", { class: "box-foot" }, o.foot) : null,
    !isOpen && o.records.length ? h("div", { class: "muted small box-count" }, `${o.records.length} supporting record(s)`) : null);
}

// Selecting and highlighting ------------------------------------------------------------------------
let selected = null;  // {id, slots, label, sub}: the strip the others are compared with

// Runs after every redraw. The selection follows its strip (a strip being formulated changes),
// and ends when the strip is gone.
function refreshHighlights() {
  const strips = [...document.querySelectorAll("#board .strip.can-select")];
  if (selected) {
    const now = strips.find((n) => n.stripInfo.id === selected.id);
    selected = now ? now.stripInfo : null;
  }
  for (const node of strips) {
    node.classList.remove("is-sel", "is-same", "is-fits", "is-off");
    if (selected) node.classList.add(node.stripInfo.id === selected.id ? "is-sel" : `is-${compareSlots(selected.slots, node.stripInfo.slots)}`);
  }
  renderSelection();
}

function renderSelection() {
  const box = $("selection");
  if (!selected) {
    fill(box, h("div", { class: "slot-hint" }, "Nothing selected. Click any Probe, record, theory or manuscript to compare the others with it."));
    return;
  }
  const use = selectionUse();
  fill(box, strip({ head: selected.label, sub: selected.sub, slots: selected.slots, inert: true, tail: [
    use ? h("button", { class: "primary", onclick: use }, "use") : null,
    h("button", { onclick: () => { selected = null; refreshHighlights(); } }, "Clear"),
  ] }));
}

// Panels: minimising, pinning, tile style -------------------------------------------------------------
const PIN_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 3h6l-1 6 4 4v2H6v-2l4-4L9 3z"/><path d="M12 15v6"/></svg>';

// A panel opens and closes by a click anywhere on its title line, except on a control there.
function initPanels() {
  for (const panel of document.querySelectorAll("#board .panel[data-panel]")) {
    const id = panel.dataset.panel;
    const title = panel.querySelector("h2");
    const arrow = h("button", { class: "flip" });
    title.prepend(arrow);
    const show = () => {
      const closed = Boolean(prefs.closed[id]);
      panel.classList.toggle("closed", closed);
      arrow.textContent = closed ? "\u25b8" : "\u25be";
      arrow.title = closed ? "Show this panel" : "Minimise this panel";
    };
    title.onclick = (e) => {
      const control = e.target.closest(CONTROLS);
      if (control && control !== arrow) return;
      prefs.closed[id] = !prefs.closed[id];
      savePrefs();
      show();
    };
    show();
  }
  for (const [button, setting, name] of [[$("pin-task"), "pinTask", "the current task"], [$("pin-selection"), "pinSelection", "the selected strip"]]) {
    button.innerHTML = PIN_ICON;
    const show = () => {
      button.classList.toggle("on", prefs[setting]);
      button.title = prefs[setting] ? `Unpin ${name}` : `Pin ${name} to the top`;
      button.setAttribute("aria-pressed", String(prefs[setting]));
      $(setting === "pinTask" ? "actions-panel" : "selection-panel").classList.toggle("pinned", prefs[setting]);
      layoutPins();
    };
    button.onclick = () => { prefs[setting] = !prefs[setting]; savePrefs(); show(); };
    show();
  }
  const tiles = $("tile-style");
  tiles.value = prefs.tiles;
  tiles.onchange = () => { prefs.tiles = tiles.value; savePrefs(); applyTileStyle(); };
  applyTileStyle();
  const observer = new ResizeObserver(layoutPins);
  observer.observe($("top"));
  observer.observe($("actions-panel"));
}
function applyTileStyle() {
  document.body.classList.toggle("tiles-compact", prefs.tiles === "compact");
  document.body.classList.toggle("tiles-tall", prefs.tiles !== "compact");
}

// Pinned panels stick right under what is above them, so their offsets depend on measured heights.
function layoutPins() {
  const root = document.documentElement.style;
  root.setProperty("--top-h", `${$("top").offsetHeight}px`);
  root.setProperty("--task-h", prefs.pinTask ? `${$("actions-panel").offsetHeight}px` : "0px");
}

function renderColumns() {
  const v = view();
  const box = $("columns");
  box.style.display = v && !$("as-text").checked ? "" : "none";
  if (!v) return;
  const root = document.documentElement.style;
  root.setProperty("--ni", inputVars().length);
  root.setProperty("--no", outcomeVars().length);
  const name = (x) => h("div", { class: "c" }, h("b", {}, x.id), x.name);
  fill(box, h("div", { class: "cols" }, h("div", {}), inputVars().map(name), h("div", {}), outcomeVars().map(name), h("div", {})));
}

const showPanel = (id, visible) => { $(id).style.display = visible ? "" : "none"; };
const info = (text) => h("span", {}, text);
const authorLabel = (p) => (p.author === msg.you ? "your own" : nameOf(p.author));
const groupLabel = (...content) => h("div", { class: "group-label" }, content);

// World Grid --------------------------------------------------------------------------------------
function probeStrip(p) {
  const v = view();
  const known = Boolean(p.readings);
  const seen = { ...(p.readings || {}), ...(p.outcomes || {}) };
  const truth = v.probe_truth && v.probe_truth[p.index];
  const sensorOption = msg.options.find((o) => o.type === "install_sensor");
  const choices = sensorOption ? sensorOption.template.choices.filter((c) => c.probe === p.index) : [];
  return strip({
    key: `R${v.round}P${p.index}`,  // a new round's Probe is a different strip
    head: `P${p.index + 1}`, sub: p.hot_topic ? "hot topic" : "", slots: seen,
    cellFor: (variable) => {
      if (variable.kind !== "input") return cell(tile(seen[variable.id], "hidden"));
      const level = p.sensors[variable.id];
      const specialty = p.specialty.includes(variable.id);
      const choice = choices.find((c) => c.parameter === variable.id);
      const slot = `${p.index}/${variable.id}`;
      const wrong = truth && (!p.readings || p.readings[variable.id] !== truth[variable.id]);
      return cell(
        known ? tile(seen[variable.id], "blank")
          : tile(null, specialty ? "revealed" : level ? "sensor" : "no sensor", specialty ? "is-specialty" : level ? "is-sensor" : null),
        level ? h("span", { class: "badge", title: `sensor level ${level}: may be noise` }, `L${level}`) : null,
        wrong ? h("div", { class: "truth" }, `true: ${truth[variable.id]}`) : null,
        choice ? h("button", { class: `plus${task.sensor === slot ? " on" : ""}`, title: `${level ? "Upgrade" : "Install"} this sensor: cite ${choice.methods_needed} method(s)`,
          onclick: () => { task.sensor = task.sensor === slot ? null : slot; task.sensorCited = new Set(); redraw(); } }, "+") : null);
    },
    tail: p.probe_time !== null && p.probe_time !== undefined ? [info("Probe time"), chip(p.probe_time)] : null,
  });
}
function renderGrid() {
  fill($("grid"), view().probes.map(probeStrip));
}

// Records and unpublished work -----------------------------------------------------------------------
const shownLabs = () => (msg.spectator ? view().labs : [view().lab]);

function labRecords(lab) {
  const specified = (id) => {
    const e = lab.experiments.find((x) => x.id === id);
    return e && Object.keys(e.specified).length ? `, specified ${Object.keys(e.specified).join(" ")}` : "";
  };
  return ["fresh", "stale"].map((area) => [area, [
    ...lab[area].observations.map((o) => ({ id: o.id, kind: "observation", head: `O${o.id}`, sub: `P${o.probe + 1}, round ${o.round}`, slots: o.cards })),
    ...lab[area].experiments.map((e) => ({ id: e.id, kind: "experiment", head: `E${e.id}`, sub: `experiment${specified(e.id)}`, slots: e.cards })),
  ]]);
}
const recordArea = (owner, title, strips) => h("div", { class: "record-area" }, groupLabel(owner, title), strips);
function renderRecords() {
  const rows = [];
  for (const lab of shownLabs()) {
    const owner = () => (msg.spectator ? [chip(lab.seat), " "] : []);
    for (const [area, records] of labRecords(lab)) {
      if (!records.length) continue;
      rows.push(recordArea(owner(), area === "fresh" ? "Fresh records" : "Stale records",
        records.map((r) => strip({ key: `${lab.seat}/${r.head}`, head: r.head, sub: r.sub, slots: r.slots, tail: msg.spectator ? null : useRecordButton(r) }))));
    }
    if (msg.spectator && lab.experiments.length) {
      rows.push(recordArea(owner(), "Experiments, every round", lab.experiments.map((e) =>
        strip({ key: `${lab.seat}/run${e.id}`, head: `E${e.id}`, sub: `round ${e.round}`, slots: { ...e.inputs, ...e.outcomes },
          tail: Object.keys(e.specified).length ? info(`specified ${Object.keys(e.specified).join(" ")}`) : null }))));
    }
  }
  $("records-title").textContent = msg.spectator ? "Records of every lab" : "Your records";
  showPanel("records-panel", rows.length > 0);
  fill($("records"), rows);
}

function ideaStrip(i, o) {
  return strip({ head: `D${i.id}`, sub: "unpublished", slots: i.kind === "theory" ? ideaSlots(i) : {},
    text: i.kind === "method" ? `method for ${i.parameter}` : null, ...o });
}
function renderIdeas() {
  const rows = [];
  for (const lab of shownLabs()) {
    if (msg.spectator && lab.ideas.length) rows.push(groupLabel(chip(lab.seat)));
    for (const i of lab.ideas) rows.push(ideaStrip(i, { tail: msg.spectator ? null : useIdeaButton(i) }));
  }
  $("ideas-title").textContent = msg.spectator ? "Unpublished work of every lab" : "Your unpublished work";
  showPanel("ideas-panel", rows.length > 0);
  fill($("ideas"), rows);
}

// Literature --------------------------------------------------------------------------------------
const ownFirst = (a, b) => (a.author === msg.you ? 0 : 1) - (b.author === msg.you ? 0 : 1);
const closestToNobel = (a, b) => ownFirst(a, b) || b.nobel - a.nobel || a.id - b.id;

function theoryStrip(p, tail) {
  const v = view();
  return strip({ key: `T${p.id}`, head: `T${p.id}`, sub: authorLabel(p), slots: ideaSlots(p), tail: tail || [
    chip(p.author), info(`tier ${p.tier}${p.open_access ? " (open access)" : ""}`),
    info(`Nobel ${p.nobel}/${v.nobel_condition}`), info(`retraction ${p.retraction}/${v.retraction_threshold}`),
    p.patents.length ? info(`patent: ${p.patents.map(nameOf).join(", ")}`) : null,
    p.fresh ? info("fresh out of print") : null, p.sideways ? info("cited this round") : null,
  ] });
}
function renderLiterature() {
  const theories = view().published.filter((p) => p.kind === "theory").sort(closestToNobel);
  fill($("literature"), theories.length ? theories.map((p) => theoryStrip(p)) : h("p", { class: "muted" }, "No theory published yet."));
}

// Submission Portal ------------------------------------------------------------------------------------
const myReviewCards = () => (msg.you !== null && view().review_cards && view().review_cards[String(msg.you)]) || [];
const manuscriptUnderReview = (position) => view().manuscripts.find((m) => m.area === "review" && m.position === position);
const AREA_NAMES = { review: "awaiting peer review", revise: "Revise area", accept: "Accept area" };

function manuscriptBox(m, o) {
  const content = m.content;
  return boxView({
    id: o.id, onclick: o.onclick,
    top: { key: `D${m.id}`, head: `D${m.id}`, sub: o.sub, slots: content && content.kind === "theory" ? ideaSlots(content) : {},
      text: !content ? "(face down)" : content.kind === "method" ? `method for ${content.parameter}` : null, tail: o.tail },
    records: (m.record_cards || []).map((r, n) => ({ key: `D${m.id}/${n}`, head: r.kind === "observation" ? "Observation" : "Experiment", slots: r.cards })),
  });
}
function renderPortal() {
  const reviewing = new Set(myReviewCards().filter(Boolean));
  const boxes = view().manuscripts.map((m) => manuscriptBox(m, {
    id: `portal${m.id}`, sub: `${AREA_NAMES[m.area] || m.area}${m.position ? ` #${m.position}` : ""}`, tail: [
      chip(m.author), info(`tier ${m.tier}`), m.area === "accept" ? info(`${m.tokens} round(s) to go`) : null,
      info(`${m.votes} vote(s)`), info(`${m.records} record(s)`),
      m.area === "review" && reviewing.has(m.position) ? h("b", {}, "you review this") : null,
    ],
  }));
  fill($("portal"), boxes.length ? boxes : h("p", { class: "muted" }, "No manuscripts."));
}

// World Table (spectators) ----------------------------------------------------------------------------
function renderWorld() {
  const v = view();
  const inputs = inputVars();
  fill($("world"), v.world_table.map((row, n) => {
    const probes = (v.probe_truth || []).map((t, i) => (t && inputs.every((x) => t[x.id] === row.inputs[x.id]) ? `P${i + 1}` : null)).filter(Boolean);
    return strip({ key: `world${n}`, head: `#${n + 1}`, slots: { ...row.inputs, ...row.outcomes }, tail: probes.length ? info(`on the grid: ${probes.join(", ")}`) : null });
  }));
}

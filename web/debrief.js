// Debrief page (specification 10): what the hidden world was, and how the literature compared
// with the truth. Everything comes from the server's debrief; this page only lays it out.
"use strict";

const $ = (id) => document.getElementById(id);
const gameId = decodeURIComponent(location.pathname.split("/").slice(-2)[0]);
const stored = (name) => { try { return localStorage.getItem(`nv:${gameId}:${name}`) || ""; } catch { return ""; } };
let joinPassword = "";
let names = [];  // variable id -> "IP1 parent microbe type"

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "onclick") node.onclick = v;
    else if (k === "class") node.className = v;
    else if (v !== false && v !== null && v !== undefined) node.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
function table(headers, rows) {
  if (!rows.length) return h("p", { class: "muted" }, "None.");
  return h("table", {}, h("tr", {}, headers.map((x) => h("th", {}, x))), rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c)))));
}
const pct = (x) => (x === null || x === undefined ? "-" : `${Math.round(x * 100)}%`);
const fraction = (text) => { const [a, b] = String(text).split("/").map(Number); return b ? a / b : Number(text); };
const label = (id) => names[id] || id;
function showError(text) { const bar = $("error"); bar.textContent = text || ""; bar.style.display = text ? "block" : "none"; }
function panel(title, ...body) { return h("section", { class: "panel" }, h("h2", {}, title), ...body); }

function access(extra) {
  return { seat_token: stored("seat"), host_token: stored("host"), spectator_password: stored("spectator"), password: joinPassword, ...extra };
}

async function post(path, extra) {
  return fetch(`/api/games/${gameId}/${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(access(extra)),
  });
}

async function downloadCsv(table) {
  const response = await post("debrief.csv", { table });
  if (!response.ok) { showError((await response.json()).detail); return; }
  const link = h("a", { href: URL.createObjectURL(await response.blob()), download: `${gameId}_${table}.csv` });
  document.body.append(link);
  link.click();
  link.remove();
}
const csvButton = (table) => h("button", { class: "no-print small", onclick: () => downloadCsv(table) }, "CSV");

async function load() {
  const response = await post("debrief", {});
  const data = await response.json();
  if (!response.ok) {
    if (String(data.detail).includes("join password")) { askPassword(); return; }
    $("status").textContent = data.detail;
    return;
  }
  $("password").style.display = "none";
  render(data);
}

function askPassword() {
  const box = $("password");
  const input = h("input", { type: "password", placeholder: "join password" });
  box.innerHTML = "";
  box.append(panel("This game has a join password", h("div", { class: "form-row" }, input, " ",
    h("button", { class: "primary", onclick: () => { joinPassword = input.value; load(); } }, "Open the debrief"))));
  box.style.display = "flex";
  $("status").textContent = "";
}

// Panels -------------------------------------------------------------------------------------------
function render(d) {
  names = Object.fromEntries(d.real_world.variables.map((v) => [v.id, `${v.id} ${v.name}`]));
  $("status").textContent = `${d.scenario.title} \u00b7 world ${d.scenario.world}`;
  const box = $("debrief");
  box.innerHTML = "";
  if (!d.bookkeeping_recorded) {
    box.append(h("p", { class: "warn" }, "This game was played before the debrief bookkeeping existed: retracted papers, "
      + "fabricated records and peer review decisions were not recorded, so those parts are incomplete."));
  }
  box.append(ending(d), literature(d), luck(d), sabotage(d), totals(d), overTime(d), realWorld(d));
  if (Object.keys(d.ai_notes).length) {
    box.append(panel("AI players' notes", Object.entries(d.ai_notes).map(([name, text]) =>
      h("div", {}, h("h3", {}, name), h("pre", {}, text)))));
  }
}

function ending(d) {
  const e = d.ending;
  const what = { nobel: "a Nobel Prize", crisis_crash: "a Crisis Crash: everyone lost", credit: "academic credit at the end of the Crisis",
    ended_early: "the host ending the game" }[e.ending] || e.ending;
  const body = [
    h("p", {}, h("b", {}, `The game ended with ${what}`), ` in round ${e.round}. `,
      e.winners.length ? `Winners: ${e.winners.join(", ")}.` : "Nobody won."),
    table(["Researcher", "Academic credit"], e.ranking.map((r) => [r.name, r.credit])),
  ];
  if (e.alliances.length) body.push(h("p", {}, "Alliances: " + e.alliances.map((a) => a.join(" & ")).join("; ")));
  if (e.nobel) {
    const n = e.nobel;
    body.push(h("h3", {}, "The Nobel Prize theory"),
      h("p", {}, `T${n.theory} by ${n.author}: ${n.content}. True accuracy ${pct(n.true_accuracy)}. `,
        `It won with ${n.streak.length} successes in a row; the chance of such a streak was ${pct(n.chance)}.`),
      table(["Round", "Predicted by", "Probe"], n.streak.map((s) => [s.round, s.predictor, `P${s.probe}`])));
  }
  if (e.crisis) {
    const c = e.crisis;
    body.push(h("h3", {}, "The Crisis"),
      h("p", {}, `It started in round ${c.started}. Unsuccessful predictions: ${c.unsuccessful.length} `
        + `(a Crisis Crash at ${c.condition}).`),
      table(["Round", "What", "Probe", "Predicted by", "Theory"], c.unsuccessful.map((u) =>
        [u.round, u.kind, u.probe ? `P${u.probe}` : "", u.predictor || "", u.theory ? `T${u.theory}` : ""])));
  }
  return panel("How it ended", body);
}

function literature(d) {
  const rows = d.literature.map((t) => [
    `T${t.theory}`, t.author, t.tier, t.round, t.content,
    `${t.successes} of ${t.successes + t.failures}`, pct(t.observed_rate),
    h("b", {}, pct(t.true_accuracy)), pct(t.coverage), t.retracted ? `retracted in round ${t.retracted}` : "",
  ]);
  return panel("The literature vs. the truth",
    h("p", { class: "small muted" }, "Every published theory. Observed: how its predictions fared in this game. True accuracy: "
      + "the share of the World Table rows it covers where it is right. Coverage: the share of rows it applies to."
      + (d.methods_published ? ` Methods published: ${d.methods_published}.` : "")),
    table(["Theory", "Author", "Tier", "Round", "Content", "Successes", "Observed", "True accuracy", "Coverage", ""], rows),
    csvButton("literature"));
}

function luck(d) {
  const l = d.luck;
  const rows = (list) => list.map((x) => [x.round, x.predictor, `T${x.theory}`, `P${x.probe}`, x.content, pct(x.true_accuracy)]);
  const headers = ["Round", "Predicted by", "Theory", "Probe", "Content", "True accuracy"];
  return panel("Luck",
    h("h3", {}, `Lucky successes (true accuracy below ${pct(l.threshold)})`), table(headers, rows(l.lucky_successes)),
    h("h3", {}, `Unlucky failures (true accuracy above ${pct(1 - l.threshold)})`), table(headers, rows(l.unlucky_failures)),
    csvButton("luck"));
}

function sabotage(d) {
  return panel("Sabotage?",
    h("p", { class: "small muted" }, "Revealed predictions that failed despite contrary evidence the predictor held: one of their "
      + "own experiments, matching the theory's inputs and the Probe's readings, had already contradicted the theory. "
      + "This is inferred, not certain."),
    table(["Round", "Predicted by", "Theory", "Theory's author", "Nobel counter at the round's start"],
      d.sabotage.map((s) => [s.round, s.predictor, `T${s.theory}`, s.own_theory ? `${s.author} (own theory)` : s.author || "",
        s.nobel_at_round_start ?? ""])),
    csvButton("sabotage"));
}

function totals(d) {
  const f = d.fabrication, drawer = d.file_drawer, review = d.peer_review;
  return panel("Fabrication, file drawer and peer review (totals only)",
    h("h3", {}, "Fabrication"),
    h("p", {}, `${f.fabricated_records} supporting record(s) were mixed from several experiments. `,
      `${f.published_papers_relying_on_them} published paper(s) relied on them`,
      f.true_accuracy_of_those_theories.length ? `; the true accuracy of those theories: ${f.true_accuracy_of_those_theories.map(pct).join(", ")}.` : "."),
    h("h3", {}, "File drawer"),
    h("p", {}, `${drawer.never_revealed} prediction(s) were made but never revealed; they would have succeeded `
      + `${pct(drawer.never_revealed_success_rate)} of the time. The ${drawer.revealed} revealed prediction(s) succeeded `
      + `${pct(drawer.revealed_success_rate)} of the time.`),
    h("h3", {}, "Peer review"),
    table(["Journal tier", "Decisions", "Accepted", "Acceptance rate"],
      review.by_tier.map((t) => [t.tier, t.decisions, t.accepted, pct(t.acceptance_rate)])),
    h("p", {}, `Accepted with fabricated records: ${review.accepted_with_fabricated_records}.`),
    csvButton("totals"));
}

function overTime(d) {
  const o = d.over_time;
  return panel("Over time",
    h("h3", {}, "Academic credit at the end of each round"),
    table(["Round", ...o.credit.map((c) => c.name)], o.rounds.map((r, i) => [r, ...o.credit.map((c) => c.values[i])])),
    o.nobel.length ? h("h3", {}, `Nobel Prize counters of the leading theories (a prize at ${o.nobel_condition})`) : null,
    o.nobel.length ? table(["Round", ...o.nobel.map((t) => `T${t.theory}`)],
      o.rounds.map((r, i) => [r, ...o.nobel.map((t) => t.values[i] ?? "")])) : null,
    csvButton("credit_by_round"));
}

function realWorld(d) {
  const w = d.real_world;
  const inputs = w.variables.filter((v) => w.input_ids.includes(v.id));
  const outcomes = w.variables.filter((v) => !w.input_ids.includes(v.id));
  const rate = (row, v) => {
    const p = row.probabilities && row.probabilities[v.id];
    return p ? ` (${pct(p[row.outcomes[v.id]])})` : "";
  };
  const body = [
    h("p", { class: "small muted" }, "Every combination of input states and the world outcome it produced in this game"
      + (w.rows.some((r) => r.probabilities) ? " (in brackets: how likely that outcome was when the world was drawn)." : ".")),
    table([...inputs.map((v) => label(v.id)), ...outcomes.map((v) => label(v.id))],
      w.rows.map((row) => [...inputs.map((v) => row.inputs[v.id]), ...outcomes.map((v) => row.outcomes[v.id] + rate(row, v))])),
    h("h3", {}, "Base rates"),
    h("p", {}, Object.entries(w.base_rates).map(([id, states]) =>
      `${label(id)}: ` + Object.entries(states).map(([s, r]) => `${s} ${pct(r)}`).join(", ")).join("; ")),
  ];
  if (w.main_effects) {
    body.push(h("h3", {}, "The designed effects"),
      h("ul", {}, w.main_effects.map((e) => h("li", {},
        `${label(e.input)} = ${e.input_state} makes ${label(e.outcome)} = ${e.outcome_state} `
        + `${e.effect.startsWith("-") ? "less" : "more"} likely (${e.effect.replace(/^[+-]/, "")})`))));
  }
  if (w.interactions && w.interactions.length) {
    body.push(h("h3", {}, "Interactions"),
      h("ul", {}, w.interactions.map((i) => h("li", {},
        `${label(i.input_a)} = ${i.state_a} together with ${label(i.input_b)} = ${i.state_b} makes `
        + `${label(i.outcome)} = ${i.outcome_state} ${i.sign < 0 ? "less" : "more"} likely (${i.size})`))));
  }
  if (w.nobel_grade && w.nobel_grade.length) {
    body.push(h("h3", {}, "Nobel-grade theories of this world"),
      table(["Theory", "True accuracy", "Coverage"], w.nobel_grade.map((t) => [
        Object.entries(t.inputs).map(([k, v]) => `${k}=${v}`).join(", ") + " -> " + Object.entries(t.outcomes).map(([k, v]) => `${k}=${v}`).join(", "),
        pct(fraction(t.accuracy)), pct(fraction(t.coverage))])));
  }
  body.push(csvButton("world_table"));
  return panel("The real world", body);
}

$("back").href = `/game/${encodeURIComponent(gameId)}`;
$("print").onclick = () => window.print();
load();

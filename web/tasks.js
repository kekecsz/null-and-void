// What the player can do now (specification 7.4, "Tasks"). What may be done comes from the legal
// actions in each message; the server judges every action. The forms' drafts live in `task`, so
// redrawing keeps them.
"use strict";

const task = {
  step: null,            // round and phase the drafts belong to
  picks: {},             // the experiment or theory being formulated: variable id -> state
  cited: new Set(),      // methods cited by hand for the experiment
  sensor: null,          // "probe/parameter" whose citation row is open
  sensorCited: new Set(),
  boxes: [],             // submission boxes: {manuscript, tier, records, payApc}
  target: 0,             // the box that receives what the player "uses"
  open: new Set(),       // boxes shown with their records
  afterSend: null,       // clears a draft once the server has taken the action
  keyAtSend: null,
  autoSelected: null,    // the strip selected for the player at the start of the prediction step
};
function clearDrafts() {
  Object.assign(task, { picks: {}, cited: new Set(), sensor: null, sensorCited: new Set(), boxes: [], target: 0, afterSend: null });
}
const optionOf = (type) => msg.options.find((o) => o.type === type);
const none = { actions: [] };

function sendThen(action, clear) {
  task.afterSend = clear;
  task.keyAtSend = actionsKey();
  send(action);
}

// Everything a draft can change.
function redraw() {
  if (!msg.spectator) { actionsShown = null; renderActions(); }
  renderGrid();
  renderRecords();
  renderIdeas();
  renderPortal();
  refreshHighlights();
}

// "use" ---------------------------------------------------------------------------------------------
function copyToExperiment(slots) {
  for (const [id, states] of Object.entries(optionOf("run_experiment").template.states)) task.picks[id] = states.includes(slots[id]) ? slots[id] : null;
  task.cited = new Set();
  redraw();
}
function copyToTheory(slots) {
  const t = optionOf("formulate_theory").template;
  task.picks = {};
  for (const [id, states] of Object.entries({ ...t.inputs, ...t.outcomes })) if (states.includes(slots[id])) task.picks[id] = slots[id];
  redraw();
}
function selectionUse() {  // what "use" on the selected strip does now, if anything
  if (msg.spectator) return null;
  if (optionOf("run_experiment") && selected.id !== "form:experiment") return () => copyToExperiment(selected.slots);
  if (optionOf("formulate_theory") && selected.id !== "form:theory") return () => copyToTheory(selected.slots);
  return null;
}

const useButton = (onclick) => h("button", { onclick }, "use");
function useRecordButton(record) {
  if (optionOf("formulate_theory")) return useButton(() => copyToTheory(record.slots));
  const box = task.boxes[task.target];
  if (!optionOf("submit") || !box || box.tier === null || box.tier === undefined) return null;
  const spec = boxCandidates(box).find((c) => (record.kind === "observation"
    ? c.kind === "observation" && c.observation === record.id
    : c.kind === "experiment" && c.cards.every(([e]) => e === record.id)));
  if (!spec || box.records.some((r) => specKey(r) === specKey(spec))) return null;
  return useButton(() => { box.records.push(spec); task.open.add(`box${task.target}`); redraw(); });
}
function useIdeaButton(idea) {
  const option = optionOf("submit");
  if (!option || !option.actions.some((a) => a.manuscript === idea.id)) return null;
  return useButton(() => {
    task.boxes.forEach((b) => { if (b.manuscript === idea.id) Object.assign(b, emptyBox()); });
    const box = task.boxes[task.target];
    Object.assign(box, emptyBox(), { manuscript: idea.id });
    const tiers = tiersFor(idea.id);
    if (tiers.length === 1) chooseTier(box, tiers[0]);
    task.open.add(`box${task.target}`);
    redraw();
  });
}

// What a choice would lead to: the numbers are the server's (msg.preview, nv_core/preview.py).
const preview = () => msg.preview || {};
const signed = (n) => (n > 0 ? `+${n}` : String(n));
const authorPart = (n) => (n ? `, ${signed(n)} as author` : "");
function patentPart(x) {
  if (x.patent === "new") return ", patent";
  return x.patent_holder === msg.you ? ", you already hold its patent" : `, no patent (${nameOf(x.patent_holder)} holds it)`;
}
function payoffLine(paper) {
  const x = (preview().theories || {})[paper.id];
  if (!x) return null;
  const amounts = (key) => (x.plain ? `${signed(x.plain[key])} AC (preregistered ${signed(x.preregistered[key])})` : `${signed(x.preregistered[key])} AC`);
  return h("div", { class: "payoff" },
    h("span", { class: "good" }, `If right: ${amounts("success")}${authorPart(x.author_success)}${patentPart(x)}.`), " ",
    h("span", { class: "bad" }, `If wrong: ${amounts("failure")}${authorPart(x.author_failure)}, no patent.`));
}
function outcomeNote(x) {  // what a prediction does once revealed
  if (!x) return null;
  if (x.pruned) return h("span", { class: "muted" }, "Pruned: not scored");
  return h("span", { class: x.success ? "good" : "bad" },
    `${x.success ? "Success" : "Failed"}: ${signed(x.credit)} AC${authorPart(x.author_credit)}${x.success ? patentPart(x) : ", no patent"}`);
}

// Predictions: one strip per eligible theory, with a choice for each Probe --------------------------------
function predictionRows(option) {
  const v = view();
  const makes = option ? option.actions : [];
  const cancels = (optionOf("cancel_prediction") || none).actions;
  const current = cancels.map((a) => ({ cancel: a, q: v.predictions.find((q) => q.id === a.prediction) })).filter((x) => x.q);
  const paper = (id) => v.published.find((p) => p.id === id);
  const papers = [...new Set([...makes.map((a) => a.theory), ...current.map((x) => x.q.theory)])].map(paper).filter(Boolean).sort(closestToNobel);
  return papers.map((p) => {
    const probes = [...new Set([...makes.filter((a) => a.theory === p.id).map((a) => a.probe), ...current.filter((x) => x.q.theory === p.id).map((x) => x.q.probe)])].sort((a, b) => a - b);
    const pair = (probe) => {
      const made = current.find((x) => x.q.theory === p.id && x.q.probe === probe);
      const choice = (preregister, label) => {
        const make = makes.find((a) => a.theory === p.id && a.probe === probe && Boolean(a.preregister) === preregister);
        const on = made && made.q.preregistered === preregister;
        if (!make && !on) return null;
        return h("button", { class: on ? "primary" : "", title: on ? "Press again to withdraw" : null, onclick: () => {
          if (made) send(made.cancel);
          if (!on) send(make);
        } }, label);
      };
      return h("span", { class: "pair" }, h("b", {}, `P${probe + 1}`), choice(false, "Predict"), choice(true, "Preregister"));
    };
    return [theoryStrip(p, [info(`Nobel ${p.nobel}/${v.nobel_condition}`), probes.map(pair)]), payoffLine(p)];
  });
}

const predictionStrip = (q, tail) => strip({ key: `Q${q.id}`, head: `Q${q.id}`, sub: `T${q.theory} on P${q.probe + 1}`, slots: { ...q.inputs, ...q.outcomes }, tail });
function revealRows(option) {
  const v = view();
  const reveals = preview().reveals || {};
  return option.actions.map((a) => {
    const q = v.predictions.find((x) => x.id === a.prediction);
    if (!q) return h("button", { onclick: () => send(a) }, describe(a));
    return predictionStrip(q, [outcomeNote(reveals[q.id]),
      h("button", { class: a.reveal ? "primary" : "", onclick: () => send(a) }, a.reveal ? "Reveal" : "Keep hidden after all")]);
  });
}
function preregisteredRows() {  // they need no decision, so they come last
  const reveals = preview().reveals;
  const mine = reveals ? view().predictions.filter((q) => q.seat === msg.you && q.preregistered) : [];
  if (!mine.length) return null;
  return h("div", { class: "rows" }, groupLabel("Preregistered: revealed automatically"), mine.map((q) => predictionStrip(q, outcomeNote(reveals[q.id]))));
}

// Citations -----------------------------------------------------------------------------------------
// Auto-cite prefers (specification 7.4): my own methods; the author with the lowest academic
// credit; the method published first.
function citeRank(id) {
  const v = view();
  const p = v.published.find((x) => x.id === id);
  return [p.author === msg.you ? 0 : 1, v.researchers[p.author].credit, p.round, p.id];
}
function byCitePreference(a, b) {
  const x = citeRank(a), y = citeRank(b);
  for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] - y[i];
  return 0;
}
function methodLabel(id) {
  const p = view().published.find((x) => x.id === id);
  return p ? `M${id} ${p.parameter} (${authorLabel(p)})` : `M${id}`;
}
function citeButtons(ids, chosen, proposed, usable, toggle) {
  return ids.map((id) => h("button", {
    class: chosen.includes(id) ? "on" : proposed.includes(id) ? "auto" : "",
    disabled: usable(id) ? null : true,
    title: proposed.includes(id) ? "Auto-cite would choose this one" : null,
    onclick: () => toggle(id),
  }, methodLabel(id)));
}

// See Experimentation in the rulebook: free parameters, plus one per cited method. Citations made
// by hand are kept; auto-cite only adds what is still missing.
function experimentPlan(t) {
  const specified = inputVars().map((x) => x.id).filter((id) => task.picks[id]);
  const eligible = t.methods.filter((m) => specified.includes(m.parameter));
  const cited = eligible.filter((m) => task.cited.has(m.id));
  const need = Math.max(0, specified.length - t.free_input_parameters);
  const fill_ = [];
  const taken = new Set(cited.map((m) => m.parameter));
  for (const m of [...eligible].sort((a, b) => byCitePreference(a.id, b.id))) {
    if (cited.length + fill_.length >= need) break;
    if (!taken.has(m.parameter)) { taken.add(m.parameter); fill_.push(m); }
  }
  return { specified, cited, need, ready: cited.length >= need, proposed: fill_, possible: cited.length + fill_.length >= need };
}

function pickerCell(variable, states, emptyText) {
  const value = task.picks[variable.id] || null;
  const list = [null, ...states];
  return cell(h("button", { class: "picker", title: "Click to change", onclick: () => {
    task.picks[variable.id] = list[(list.indexOf(value) + 1) % list.length];
    redraw();
  } }, tile(value, emptyText)));
}

function experimentRows(option) {
  const t = option.template;
  const plan = experimentPlan(t);
  const slots = Object.fromEntries(Object.entries(task.picks).filter(([id, s]) => s && t.states[id]));
  const run = () => {
    const specified = Object.fromEntries(plan.specified.map((id) => [id, task.picks[id]]));
    sendThen({ type: "run_experiment", specified, cited_methods: [...plan.cited, ...plan.proposed].map((m) => m.id) },
      () => { task.picks = {}; task.cited = new Set(); });
  };
  const form = strip({ key: "form:experiment", head: "New experiment", sub: "click a tile to choose", slots,
    cellFor: (variable) => (variable.kind === "input" ? pickerCell(variable, t.states[variable.id], "random") : cell(tile(null, "result"))),
    tail: [
      h("button", { class: "primary", disabled: plan.possible ? null : true, onclick: run }, plan.ready ? "Run" : "Auto-cite and run"),
      h("button", { onclick: () => { task.picks = {}; task.cited = new Set(); redraw(); } }, "Clear"),
    ] });
  const parameterOf = (id) => t.methods.find((m) => m.id === id).parameter;
  const toggle = (id) => {
    const had = task.cited.has(id);
    for (const other of [...task.cited]) if (parameterOf(other) === parameterOf(id)) task.cited.delete(other);  // one method per parameter
    if (!had) task.cited.add(id);
    redraw();
  };
  const ids = [...t.methods].map((m) => m.id).sort(byCitePreference);
  return [form,
    h("div", { class: "cite" }, `${plan.specified.length} chosen, ${t.free_input_parameters} free. Cite methods:`,
      ids.length ? citeButtons(ids, plan.cited.map((m) => m.id), plan.proposed.map((m) => m.id), (id) => plan.specified.includes(parameterOf(id)), toggle) : h("span", { class: "muted" }, "none available"),
      plan.possible ? null : h("span", { class: "note-bad" }, "Not enough methods for these parameters: choose fewer.")),
    sensorRow()];
}

function sensorRow() {
  const option = optionOf("install_sensor");
  if (!task.sensor || !option) return null;
  const [probeText, parameter] = task.sensor.split("/");
  const probe = Number(probeText);
  const choice = option.template.choices.find((c) => c.probe === probe && c.parameter === parameter);
  if (!choice) return null;
  const level = view().probes[probe].sensors[parameter] || 0;
  const verb = level ? "Upgrade" : "Install";
  const ids = [...choice.methods].sort(byCitePreference);
  const cited = ids.filter((id) => task.sensorCited.has(id));
  const proposed = ids.filter((id) => !task.sensorCited.has(id)).slice(0, Math.max(0, choice.methods_needed - cited.length));
  const ready = cited.length === choice.methods_needed;
  const toggle = (id) => { if (task.sensorCited.has(id)) task.sensorCited.delete(id); else task.sensorCited.add(id); redraw(); };
  const go = () => sendThen({ type: "install_sensor", probe, parameter, cited_methods: [...cited, ...proposed] },
    () => { task.sensor = null; task.sensorCited = new Set(); });
  return h("div", { class: "cite" }, h("b", {}, `${verb} the ${parameter} sensor on P${probe + 1}:`), `cite ${choice.methods_needed}`,
    citeButtons(ids, cited, proposed, (id) => task.sensorCited.has(id) || !ready, toggle),
    h("button", { class: "primary", onclick: go }, ready ? verb : `Auto-cite and ${verb.toLowerCase()}`),
    h("button", { onclick: () => { task.sensor = null; redraw(); } }, "Cancel"));
}

// Theories ------------------------------------------------------------------------------------------
const theoryKey = (i) => JSON.stringify([Object.entries(i.inputs || {}).sort(), Object.entries(i.outcomes || {}).sort()]);
function publishedCopies(idea) {  // published theories with the same content
  return view().published.filter((p) => p.kind === "theory" && theoryKey(p) === theoryKey(idea));
}
function ownCopies(idea, except) {  // my other theories with the same content: stacks, this phase's choices, manuscripts
  const v = view();
  const key = theoryKey(idea);
  const found = [];
  for (const i of v.lab.ideas) if (i.kind === "theory" && i.id !== except && theoryKey(i) === key) found.push(`D${i.id} (development stack)`);
  v.lab.pending.development.forEach((i, n) => { if (i.kind === "theory" && theoryKey(i) === key) found.push(`choice ${n + 1} of this phase`); });
  for (const m of v.manuscripts) {
    if (m.author === msg.you && m.id !== except && m.content && m.content.kind === "theory" && theoryKey(m.content) === key) {
      found.push(`D${m.id} (submitted, ${AREA_NAMES[m.area] || m.area})`);
    }
  }
  return found;
}

function theoryRows(option) {
  const t = option.template;
  const states = { ...t.inputs, ...t.outcomes };
  const pickedFrom = (group) => Object.fromEntries(Object.keys(group).filter((id) => task.picks[id]).map((id) => [id, task.picks[id]]));
  const idea = { inputs: pickedFrom(t.inputs), outcomes: pickedFrom(t.outcomes) };
  const slots = ideaSlots(idea);
  const published = hasStates(slots) ? publishedCopies(idea) : [];
  const own = hasStates(slots) ? ownCopies(idea) : [];
  const form = strip({ key: "form:theory", head: "Your new theory", sub: "click a tile to change", slots,
    cellFor: (variable) => pickerCell(variable, states[variable.id], "blank"),
    tail: [
      h("button", { class: "primary", disabled: published.length ? true : null, onclick: () => sendThen({ type: "formulate_theory", ...idea }, () => { task.picks = {}; }) }, "Formulate"),
      h("button", { onclick: () => { task.picks = {}; redraw(); } }, "Clear"),
    ] });
  return [form,
    published.length ? h("div", { class: "warn-bad" }, `Already published as ${published.map((p) => `T${p.id} (${nameOf(p.author)})`).join(", ")}: this theory could never be submitted.`) : null,
    own.length ? h("div", { class: "warn" }, `You already have this theory: ${own.join(", ")}.`) : null];
}

function pendingDevelopmentRows(option) {
  const pending = view().lab.pending.development;
  return [groupLabel("Chosen this phase"), option.actions.map((a) => {
    const i = pending[a.index];
    return strip({ key: `pending${a.index}`, head: `Choice ${a.index + 1}`, slots: i.kind === "theory" ? ideaSlots(i) : {},
      text: i.kind === "method" ? `method for ${i.parameter}` : null, tail: h("button", { onclick: () => send(a) }, "Drop") });
  })];
}

// Submission: a box per manuscript, with the theory on top and the records below it -----------------------
const emptyBox = () => ({ manuscript: null, tier: null, records: [], payApc: false });
const specKey = (spec) => JSON.stringify(spec);
const tiersFor = (manuscript) => [...new Set(optionOf("submit").actions.filter((a) => a.manuscript === manuscript).map((a) => a.tier))].sort((a, b) => a - b);
const listedSubmission = (box) => optionOf("submit").actions.find((a) => a.manuscript === box.manuscript && a.tier === box.tier);
function chooseTier(box, tier) {
  Object.assign(box, { tier, payApc: false });
  box.records = [...listedSubmission(box).records];  // the minimum the tier asks for; "use" adds more
}
function boxCandidates(box) {  // every record the engine lists for this manuscript and tier
  const listed = listedSubmission(box);
  return listed ? [...listed.records, ...(optionOf("submit").template.spare_records[`${box.manuscript}/${box.tier}`] || [])] : [];
}

function recordRow(spec) {  // a record as an action names it
  const lab = view().lab;
  const areas = [lab.fresh, lab.stale];
  if (spec.kind === "observation") {
    const o = areas.flatMap((x) => x.observations).find((x) => x.id === spec.observation);
    return { key: `${lab.seat}/O${spec.observation}`, head: `O${spec.observation}`, sub: o ? `P${o.probe + 1}, round ${o.round}` : "", slots: o ? o.cards : {} };
  }
  const experiments = areas.flatMap((x) => x.experiments);
  const slots = {};
  for (const [e, variable] of spec.cards) {
    const found = experiments.find((x) => x.id === e);
    if (found) slots[variable] = found.cards[variable];
  }
  const ids = [...new Set(spec.cards.map(([e]) => e))];
  const head = `E${ids.join("+")}`;
  return { key: `${lab.seat}/${head}`, head, sub: ids.length > 1 ? "cards of different experiments" : "experiment", slots };
}

function chargeControl(box, t) {  // offered only when the fee and the charge together fit the money that may be spent
  const fee = t.submission_fee[String(box.tier)];
  const charge = t.apc[String(box.tier)];
  const text = h("span", {}, `fee ${fee}; you can spend ${t.spendable}`);
  if (!charge) return text;
  if (fee + charge > t.spendable) return [text, h("span", { class: "muted" }, ` (article processing charge ${charge}: not enough money)`)];
  return [text, h("label", {}, h("input", { type: "checkbox", checked: box.payApc ? true : null, onchange: (e) => { box.payApc = e.target.checked; redraw(); } }), ` pay the article processing charge (${charge})`)];
}

function processingLine(box) {  // the projected rounds in processing (nv_core.preview)
  const p = (preview().processing || {})[`${box.manuscript}/${box.tier}`];
  if (!p) return null;
  const i = Math.min(Math.max(0, box.records.length - p.first_records), p.rounds.length - 1);
  const rounds = (box.payApc ? p.rounds_with_apc : p.rounds)[i];
  const bonuses = [
    [p.extra_records[i], "extra record"], [p.extra_elements, "extra element"], [box.payApc ? 1 : 0, "article processing charge"],
    [p.hot_topic, "hot topic"], [p.crisis, "Crisis fast-track"],
  ].filter(([n]) => n);
  const shortened = bonuses.reduce((sum, [n]) => sum + n, 0);
  const parts = p.base ? [`${p.base} for this journal tier`, ...bonuses.map(([n, name]) => `\u2212${n} ${name}`)] : ["none at this journal tier"];
  return h("span", { class: "processing" }, h("b", {}, `Projected processing: ${rounds} round(s)`),
    ` (${parts.join(", ")}${p.base && p.base - shortened !== rounds ? "; cannot be shortened further" : ""}), if accepted this round`);
}

function submitBox(box, index, option) {
  const t = option.template;
  const id = `box${index}`;
  const select = () => { if (task.target !== index) { task.target = index; redraw(); } };
  if (box.manuscript === null) {
    return h("div", { class: `box${task.target === index ? " is-target" : ""}`, onclick: select },
      h("div", { class: "slot-hint" }, 'Empty submission box: press "use" on one of your theories or methods below.'));
  }
  const idea = view().lab.ideas.find((i) => i.id === box.manuscript);
  const listed = box.tier === null ? null : listedSubmission(box);
  const inBox = new Set(box.records.map(specKey));
  const others = boxCandidates(box).filter((c) => !inBox.has(specKey(c)));
  const short = listed ? listed.records.length - box.records.length : 0;
  const own = idea.kind === "theory" ? ownCopies(idea, idea.id) : [];
  const published = idea.kind === "theory" ? publishedCopies(idea) : [];
  const warnings = [
    own.length ? `You already have a theory like this: ${own.join(", ")}.` : "",
    published.length ? `The same theory is already published as ${published.map((p) => `T${p.id} (${nameOf(p.author)})`).join(", ")}.` : "",
  ].filter(Boolean);
  const submit = () => {  // duplicates are allowed (e.g. to fast-track a reformulated theory), so these only warn
    if (warnings.length && !window.confirm(`${warnings.join("\n")}\n\nAre you sure you want to submit D${idea.id}?`)) return;
    send({ ...listed, records: box.records, pay_apc: box.payApc });
  };
  return boxView({
    id, target: task.target === index, onclick: select,
    top: { key: `D${idea.id}`, head: `D${idea.id}`, sub: "submission", slots: idea.kind === "theory" ? ideaSlots(idea) : {},
      text: idea.kind === "method" ? `method for ${idea.parameter}` : null, tail: [
        h("button", { class: "primary", disabled: listed && short <= 0 ? null : true, onclick: submit }, "Submit"),
        h("button", { onclick: () => { Object.assign(box, emptyBox()); task.target = index; redraw(); } }, "Empty"),
      ] },
    records: box.records.map((spec, n) => ({ ...recordRow(spec), tail: h("button", { onclick: () => { box.records.splice(n, 1); redraw(); } }, "Remove") })),
    foot: [
      warnings.map((w) => h("div", { class: "warn" }, w)),
      h("span", {}, "Journal tier: ", tiersFor(idea.id).map((n) => h("button", { class: box.tier === n ? "on" : "", onclick: () => { chooseTier(box, n); redraw(); } }, String(n)))),
      listed ? chargeControl(box, t) : h("span", { class: "muted" }, "choose a tier"),
      listed ? processingLine(box) : null,
      short > 0 ? h("span", { class: "note-bad" }, `at least ${short} more record(s) needed`) : null,
      others.length ? h("span", {}, "Add a record: ", others.map((c) => h("button", { onclick: () => { box.records.push(c); redraw(); } }, recordRow(c).head))) : null,
    ],
  });
}

function submitRows(option) {
  const ideas = view().lab.ideas;
  for (const box of task.boxes) if (box.manuscript !== null && (!ideas.some((i) => i.id === box.manuscript) || !tiersFor(box.manuscript).length)) Object.assign(box, emptyBox());
  if (!task.boxes.length) task.boxes.push(emptyBox());
  task.target = Math.min(task.target, task.boxes.length - 1);
  return [task.boxes.map((box, i) => submitBox(box, i, option)),
    h("div", { class: "box-foot" }, h("button", { onclick: () => { task.boxes.push(emptyBox()); task.target = task.boxes.length - 1; redraw(); } }, "Add a submission box"))];
}

function manuscriptActionRows(option, label) {  // revising and withdrawing: the manuscript's strip with one button
  return option.actions.map((a) => {
    const m = view().manuscripts.find((x) => x.id === a.manuscript);
    const button = h("button", { onclick: () => send(a) }, label);
    return m ? manuscriptBox(m, { id: `${option.type}${m.id}`, sub: AREA_NAMES[m.area] || m.area, tail: button }) : button;
  });
}

function reviewRows(option) {
  const votes = view().lab.pending.votes || {};
  const isOwn = (card) => { const m = manuscriptUnderReview(myReviewCards()[card]); return Boolean(m && m.author === msg.you); };
  const cards = [...new Set(option.actions.map((a) => a.card))].sort((a, b) => isOwn(b) - isOwn(a) || a - b);  // your own on top
  return cards.map((card) => {
    const position = myReviewCards()[card];
    const m = manuscriptUnderReview(position);
    const twice = myReviewCards().filter((c) => c === position).length > 1 ? `, your card ${card + 1}` : "";
    const tail = option.actions.filter((a) => a.card === card).map((a) =>
      h("button", { class: votes[String(card)] === a.vote ? "primary" : "", onclick: () => send(a) }, a.vote));
    if (!m) return h("div", { class: "form-row" }, `awaiting peer review #${position}${twice} `, tail);
    const own = isOwn(card);
    return manuscriptBox(m, { id: `review${card}`, sub: `#${position}${twice}, tier ${m.tier}, ${own ? "" : authorLabel(m)}`, subStrong: own ? authorLabel(m) : null, tail });
  });
}

// Smaller choices -----------------------------------------------------------------------------------
function describe(a) {
  const n = (seat) => nameOf(seat);
  switch (a.type) {
    case "claim_probe_time": return `Take Probe time on P${a.probe + 1}`;
    case "reveal_prediction": return a.reveal ? `Reveal Q${a.prediction}` : `Keep Q${a.prediction} hidden after all`;
    case "develop_method": return `Develop a method for ${a.parameter}`;
    case "propose_alliance": return `Propose an alliance to ${n(a.partner)}`;
    case "accept_alliance": return `Accept the alliance with ${n(a.partner)}`;
    case "leave_alliance": return `Leave the alliance with ${n(a.partner)}`;
    case "stay_in_alliance": return `Stay in the alliance with ${n(a.partner)}`;
    default: return JSON.stringify(a);
  }
}

function completeActions(option) {
  const items = option.actions;
  if (items.length <= 8) return items.map((a) => h("button", { onclick: () => send(a) }, describe(a)));
  const select = h("select", {}, items.map((a, i) => h("option", { value: i }, describe(a))));
  return [select, h("button", { onclick: () => send(items[Number(select.value)]) }, "Do it")];
}

// A number box with a larger - and + on either side. The box itself is in .box; read .value as usual.
function taskLabel(name) {  // a staff task, with what the Grant funding position asks of the Grants row
  const needed = preview().grant_admin_needed;
  const label = name.replace("_", " ");
  return name === "grants" && needed !== undefined ? [label, h("span", { class: "grant-need" }, `grant track needs: ${needed}`)] : label;
}

function numberInput(value, min, max, disabled) {
  const limited = max !== null && max !== undefined;
  const input = h("input", { type: "number", class: "plain", value, min, max: limited ? max : false, disabled: disabled ? true : null });
  const step = (by) => {
    input.value = Math.min(limited ? max : Infinity, Math.max(min, (Number(input.value) || 0) + by));
    input.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const button = (text, by, title) => h("button", { type: "button", title, disabled: disabled ? true : null, onclick: () => step(by) }, text);
  input.box = h("span", { class: "stepper" }, button("\u2212", -1, "One less"), input, button("+", 1, "One more"));
  return input;
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
    const p = numberInput(current.postdocs, 0, t.at_most_one.includes(task) ? 1 : null);
    const s = numberInput(current.students, 0, null, t.postdoc_only.includes(task));
    inputs[task] = [p, s];
    return [taskLabel(task), TASK_WHEN[task] || "", p.box, s.box];
  });
  const totals = { postdocs: h("b", {}), students: h("b", {}) };
  const allocationTable = table(["Task", "When", "Postdocs", "Students"], [...rows, [h("b", {}, "Allocated"), "", totals.postdocs, totals.students]]);
  allocationTable.classList.add("alloc");
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
  // Each staff column: grey until every hired staff member of that type has a task, red if too many do.
  const update = () => {
    const wanted = { postdocs: Number(postdocs.value) || 0, students: Number(students.value) || 0 };
    const given = { postdocs: 0, students: 0 };
    for (const [p, s] of Object.values(inputs)) { given.postdocs += Number(p.value) || 0; given.students += Number(s.value) || 0; }
    for (const kind of Object.keys(wanted)) {
      allocationTable.classList.toggle(`${kind}-over`, given[kind] > wanted[kind]);
      allocationTable.classList.toggle(`${kind}-short`, given[kind] < wanted[kind]);
      totals[kind].textContent = `${given[kind]} of ${wanted[kind]}`;
    }
    button.disabled = given.postdocs !== wanted.postdocs || given.students !== wanted.students;
  };
  for (const input of [postdocs, students, ...Object.values(inputs).flat()]) input.oninput = update;
  const maxButton = (input, limit) => (limit === null ? null : h("button", { type: "button", title: "As many as you can", onclick: () => { input.value = limit; update(); } }, "max"));
  const previous = preview().previous_allocation;
  const repeat = () => {
    for (const [name, [p, s]] of Object.entries(inputs)) {
      const count = previous[name] || { postdocs: 0, students: 0 };
      p.value = count.postdocs;
      if (!s.disabled) s.value = count.students;
    }
    update();
  };
  update();
  return [
    h("div", { class: "form-row hire-row" }, `You have ${now} postdoc(s). Postdocs after hiring/firing: `, postdocs.box, maxButton(postdocs, high),
      ` (${low} to ${high === null ? "any" : high}) \u00b7 students to hire: `, students.box, maxButton(students, t.max_students), ` (at most ${t.max_students}) `,
      h("button", { type: "button", disabled: previous ? null : true, title: "Fill in the task allocation of your last round", onclick: repeat }, "Repeat")),
    allocationTable,
    h("div", { class: "small muted" }, "Every staff member needs a task; Development and Talent development take postdocs only; at most one on Talent development."),
    button,
  ];
}

function leavingForm(t) {
  const inputs = Object.entries(t.students_by_task).sort(([a], [b]) => taskOrder(a) - taskOrder(b))
    .map(([task, n]) => [task, numberInput(0, 0, n), n]);
  return [
    h("p", {}, `${t.count} student(s) must leave. Choose from which tasks:`),
    table(["Task", "When", "Students there", "Leaving"], inputs.map(([task, input, n]) => [taskLabel(task), TASK_WHEN[task] || "", n, input.box])),
    h("button", { onclick: () => {
      const by_task = {};
      for (const [task, input] of inputs) if (Number(input.value)) by_task[task] = Number(input.value);
      send({ type: "choose_leaving_students", by_task });
    } }, "Choose"),
  ];
}

function orderForm(t) {
  const input = h("input", { value: t.predictions.map((id) => `Q${id}`).join(", "), size: 30 });
  return [h("p", { class: "small" }, "Several of your predictions are on the same Probe: the order in which they are scored."), input,
    h("button", { onclick: () => send({ type: "order_predictions", order: input.value.split(",").map((x) => Number(x.trim().replace(/^Q/, ""))) }) }, "Set the order")];
}

// The task panel ------------------------------------------------------------------------------------
// What each option looks like in the panel: its strips and form, without a heading of its own for
// the main task of a phase.
const TASK_ROWS = {
  make_prediction: predictionRows, reveal_prediction: revealRows, run_experiment: experimentRows,
  formulate_theory: theoryRows, cancel_development: pendingDevelopmentRows, submit: submitRows, review_vote: reviewRows,
};
const FORMS = {
  allocate_staff: (o) => allocateForm(o.template), choose_leaving_students: (o) => leavingForm(o.template),
  order_predictions: (o) => orderForm(o.template), revise: (o) => manuscriptActionRows(o, "Revise"),
  withdraw_submission: (o) => manuscriptActionRows(o, "Withdraw"),
};
const TITLES = {
  allocate_staff: "Hiring and task allocation", choose_leaving_students: "Student task check", claim_probe_time: "Probe time",
  order_predictions: "Scoring order", develop_method: "Develop a method", revise: "Revise a manuscript",
  withdraw_submission: "Undo this step's submission or revision", leave_alliance: "Last chance to leave an alliance",
  stay_in_alliance: "Stay in an alliance",
};
const TASK_NAMES = {
  make_prediction: ["make predictions", 'your own theories first, then those closest to the Nobel Prize. Click a Probe in the World Grid to see which theories fit it. Amounts apply if revealed and not pruned.'],
  cancel_prediction: ["make predictions", ""],
  reveal_prediction: ["reveal predictions", "what each would bring, if it is not pruned"],
  run_experiment: ["experiments and sensors", 'press "+" on a Probe tile to install or upgrade its sensor'],
  formulate_theory: ["formulate a theory", 'press "use" on a record, or on the selected strip, to copy its states here'],
  submit: ["submit manuscripts", 'the outlined box receives what you "use"'],
  review_vote: ["peer review", "open a box to see the manuscript's supporting records"],
};
const IN_THE_TITLE = { commit: "Commit", pass: "Pass" };
const COMMIT_HELP = { commit: "My choices for this step are final", pass: "Stop experimenting this round" };

// The server sends a new state after every player's action, also another player's. Rebuilding the
// forms then would throw away what this player has typed but not sent yet, so they are rebuilt
// only when something they show has changed: the choices, the step, this lab, the literature.
let actionsShown = null;
function actionsKey() {
  const v = view();
  const report = pendingReport();
  return JSON.stringify([msg.status, msg.you, msg.seats[msg.you] && msg.seats[msg.you].kind, Boolean(v.result), v.round, v.phase,
    msg.options, v.lab, myReviewCards(), v.published.map((p) => p.id), v.manuscripts.map((m) => [m.id, m.area, m.position]), report && report.round]);
}

// While something could still be submitted or revised, and nothing has been, Commit is greyed and
// asks first: committing ends the step. (Whatever was done this step can be withdrawn, so
// "withdraw_submission" being on offer means something was.)
// Likewise in the Development phase, while staff are there and nothing has been developed
// ("cancel_development" being on offer means something was).
const nothingSubmittedYet = () => Boolean(optionOf("submit") || optionOf("revise")) && !optionOf("withdraw_submission");
const nothingDevelopedYet = () => Boolean(optionOf("formulate_theory")) && !optionOf("cancel_development");
function commitWarning() {
  if (nothingSubmittedYet()) return "You have not submitted or revised a manuscript in this step.";
  if (nothingDevelopedYet()) return "You have staff on Development but have not formulated a theory or developed a method.";
  return null;
}
function titleButton(option) {
  const warning = option.type === "commit" ? commitWarning() : null;
  return h("button", {
    class: warning ? "commit-waiting" : option.type === "commit" ? "primary" : "",
    title: warning || COMMIT_HELP[option.type],
    onclick: () => {
      if (warning && !window.confirm(`${warning}\n\nCommit anyway?`)) return;
      send(option.actions[0]);
    },
  }, IN_THE_TITLE[option.type]);
}

function setTaskHeading(name, note, buttons) {
  const phase = view() ? view().phase : null;
  $("actions-title").textContent = [phase, name].filter(Boolean).join(" \u00b7 ") || "What you can do now";
  $("actions-note").textContent = note || "";
  fill($("task-buttons"), buttons || []);
}

// The prediction report (specification 7.4): each person's own, until they press Next. The game
// does not wait for it; only this panel does. A seat handed to an automated player gets none.
function pendingReport() {
  const report = view().prediction_report;
  if (!report || msg.spectator || msg.you === null || store.get("report") === String(report.round)) return null;
  return msg.seats[msg.you] && msg.seats[msg.you].kind === "human" ? report : null;
}
const REPORT_OUTCOMES = { success: ["good", "Success"], failed: ["bad", "Failed"], pruned: ["muted", "Pruned"], unscored: ["muted", "Not scored: the game ended"] };
function reportEntry(p) {
  const [cls, label] = REPORT_OUTCOMES[p.outcome];
  const patent = p.patent === "new" ? "patent" : p.patent === "held" ? (p.patent_holder === p.seat ? "already holds its patent" : `no patent (${nameOf(p.patent_holder)} holds it)`) : null;
  const row = strip({ key: `report${p.id}`, head: `T${p.theory}`, sub: `P${p.probe + 1}${p.preregistered ? ", preregistered" : ""}`, slots: { ...p.inputs, ...p.outcomes }, tail: [
    h("b", { class: cls }, label),
    p.credit === null ? null : info(`${signed(p.credit)} AC`),
    p.author_credit ? info(`${nameOf(p.author)} ${signed(p.author_credit)} as author`) : null,
    patent ? info(patent) : null,
  ] });
  if (!p.nobel) return row;
  return h("div", { class: "report-nobel" }, row, h("div", { class: "nobel-note" }, `Nobel Prize! This prediction completed the streak of T${p.theory}: ${nameOf(p.author)} wins the Nobel Prize.`));
}
function showReport(box, report) {
  $("actions-title").textContent = `Prediction report, round ${report.round}`;
  fill($("task-buttons"), h("button", { class: "primary", title: "Go on with the game", onclick: () => {
    store.set("report", String(report.round));
    actionsShown = null;
    renderActions();
  } }, "Next"));
  const seats = [...new Set(report.predictions.map((p) => p.seat))].sort((a, b) => a - b);
  const missed = report.missed.map((p) => `P${p + 1}`).join(", ");
  fill(box,
    report.crisis ? h("p", { class: "small bad" }, `Crisis: ${report.unsuccessful} of ${report.crisis_condition} unsuccessful predictions so far.`,
      missed ? ` No prediction on ${missed}: each counts as unsuccessful.` : "") : null,
    seats.length ? h("div", { class: "report" }, seats.map((seat) => recordArea(chip(seat), "", report.predictions.filter((p) => p.seat === seat).map(reportEntry))))
      : h("p", { class: "muted" }, "Nobody revealed a prediction."));
}

function renderActions() {
  const box = $("actions");
  const shown = actionsKey();
  const v = view();
  const step = `${v.round}/${v.phase}`;
  if (task.step !== step) {
    task.step = step;
    clearDrafts();
    if (selected && selected.id === task.autoSelected) selected = null;  // the player did not choose it
    task.autoSelected = null;
    // Which theories fit a Probe is what this step asks, so its first Probe starts out selected.
    if (optionOf("make_prediction") && !selected && v.probes.length) {
      task.autoSelected = `R${v.round}P${v.probes[0].index}`;
      selected = { id: task.autoSelected, slots: {}, label: "", sub: "" };
    }
  }
  if (task.afterSend && shown !== task.keyAtSend) { task.afterSend(); task.afterSend = null; }
  if (shown === actionsShown && box.childElementCount) return;
  actionsShown = shown;
  const scrolled = box.scrollTop;
  box.innerHTML = "";
  const report = pendingReport();
  box.classList.toggle("whole", Boolean(report || optionOf("allocate_staff")));  // these should fit without scrolling
  setTaskHeading();
  if (report) { showReport(box, report); refreshHighlights(); return; }
  if (v.result || msg.status !== "running") { box.append(h("p", { class: "muted" }, "Nothing to do.")); return; }
  if (msg.options.every((o) => o.type === "alliance")) {  // alliances have their own panel
    box.append(h("p", { class: "muted" }, msg.seats[msg.you] && msg.seats[msg.you].kind !== "human"
      ? `Your seat is played by an automated player (${msg.seats[msg.you].kind}) for now.` : "Nothing to do right now; others are deciding."));
    const preregistered = preregisteredRows();
    if (preregistered) box.append(preregistered);
    return;
  }
  const named = msg.options.find((o) => TASK_NAMES[o.type]);
  let [name, note] = named ? TASK_NAMES[named.type] : [null, null];
  const limit = preview().prediction_limit;  // Formulating predictions and preregistration
  if (limit) note = `${limit.made} of ${limit.allowed} predictions made${limit.made >= limit.allowed ? " (no room for more)" : ""}. ${note || ""}`;
  setTaskHeading(name, note, msg.options.filter((o) => IN_THE_TITLE[o.type]).map(titleButton));
  // The sensor choices are drawn with the experiment; withdrawing is done on the prediction strips.
  const listed = msg.options.filter((o) => !IN_THE_TITLE[o.type] && !["install_sensor", "cancel_prediction", "alliance"].includes(o.type));
  if (optionOf("cancel_prediction") && !optionOf("make_prediction")) box.append(h("div", { class: "rows" }, predictionRows(null)));
  for (const option of listed) {
    if (TASK_ROWS[option.type]) box.append(h("div", { class: "rows" }, TASK_ROWS[option.type](option)));
    else box.append(h("div", { class: "option" }, h("h3", {}, TITLES[option.type] || option.type), FORMS[option.type] ? FORMS[option.type](option) : completeActions(option)));
  }
  const preregistered = preregisteredRows();
  if (preregistered) box.append(preregistered);
  box.scrollTop = scrolled;
}

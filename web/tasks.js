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
  const tpl = optionOf("formulate_theory").template;
  task.picks = {};
  for (const [id, states] of Object.entries({ ...tpl.inputs, ...tpl.outcomes })) if (states.includes(slots[id])) task.picks[id] = slots[id];
  redraw();
}
function selectionUse() {  // what "use" on the selected strip does now, if anything
  if (msg.spectator) return null;
  if (optionOf("run_experiment") && selected.id !== "form:experiment") return () => copyToExperiment(selected.slots);
  if (optionOf("formulate_theory") && selected.id !== "form:theory") return () => copyToTheory(selected.slots);
  return null;
}

const useButton = (onclick) => h("button", { onclick }, t("use"));
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
function archiveButton(record) {  // Archiving records (Development phase): add to or take from this phase's choice
  const option = optionOf("archive_records");
  if (!option) return null;
  const chosen = option.template.chosen;
  if (chosen.includes(record.id)) {
    return h("button", { class: "on", title: t("Chosen for the archive; click to take it back"),
      onclick: () => send({ type: "archive_records", records: chosen.filter((x) => x !== record.id) }) }, `${t("archive")} \u2713`);
  }
  if (!option.template.records.includes(record.id)) return null;
  return h("button", { title: t("Archive this record (one development staff member per {n} records)", { n: option.template.per_staff_member }),
    onclick: () => send({ type: "archive_records", records: [...chosen, record.id] }) }, t("archive"));
}
function archiveForm(tpl) {
  const names = tpl.chosen.map((id) => `#${tpl.records.indexOf(id) + 1}`);
  return [
    h("p", { class: "small" }, t("Press \"archive\" on records in the Records panel. Archived records keep no position, so they are not discarded at Clean-up; they can still be used. One development staff member archives up to {n} records.", { n: tpl.per_staff_member })),
    tpl.chosen.length
      ? h("div", {}, t("Chosen: {n} record(s) ({list})", { n: tpl.chosen.length, list: names.join(", ") }), " ", h("button", { onclick: () => send({ type: "archive_records", records: [] }) }, t("Clear")))
      : h("span", { class: "muted" }, t("None chosen.")),
  ];
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
const authorPart = (n) => (n ? `, ${t("{n} as author", { n: signed(n) })}` : "");
function patentPart(x) {
  if (!x.patent) return "";  // no patents in the simplified game
  if (x.patent === "new") return `, ${t("patent")}`;
  return `, ${x.patent_holder === msg.you ? t("you already hold its patent") : t("no patent ({name} holds it)", { name: nameOf(x.patent_holder) })}`;
}
function payoffLine(paper) {
  const x = (preview().theories || {})[paper.id];
  if (!x) return null;
  const amounts = (key) => (x.plain ? t("{n} AC (preregistered {m})", { n: signed(x.plain[key]), m: signed(x.preregistered[key]) }) : t("{n} AC", { n: signed(x.preregistered[key]) }));
  return h("div", { class: "payoff" },
    h("span", { class: "good" }, `${t("If right:")} ${amounts("success")}${authorPart(x.author_success)}${patentPart(x)}.`), " ",
    h("span", { class: "bad" }, `${t("If wrong:")} ${amounts("failure")}${authorPart(x.author_failure)}${simplified() ? "" : `, ${t("no patent")}`}.`));
}
function outcomeNote(x) {  // what a prediction does once revealed
  if (!x) return null;
  return h("span", { class: x.success ? "good" : "bad" },
    `${x.success ? t("Success") : t("Failed")}: ${t("{n} AC", { n: signed(x.credit) })}${authorPart(x.author_credit)}${x.success ? patentPart(x) : simplified() ? "" : `, ${t("no patent")}`}`);
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
        return h("button", { class: on ? "primary" : "", title: on ? t("Press again to withdraw") : null, onclick: () => {
          if (made) send(made.cancel);
          if (!on) send(make);
        } }, label);
      };
      return h("span", { class: "pair" }, h("b", {}, `P${probe + 1}`), choice(false, t("Predict")), choice(true, t("Preregister")));
    };
    return [theoryStrip(p, [info(t("Nobel {n}/{max}", { n: p.nobel, max: v.nobel_condition })), probes.map(pair)]), payoffLine(p)];
  });
}

const predictionStrip = (q, tail) => strip({ key: `Q${q.id}`, head: `Q${q.id}`, sub: t("T{theory} on P{probe}", { theory: q.theory, probe: q.probe + 1 }), slots: { ...q.inputs, ...q.outcomes }, tail });
function revealRows(option) {
  const v = view();
  const reveals = preview().reveals || {};
  return option.actions.map((a) => {
    const q = v.predictions.find((x) => x.id === a.prediction);
    if (!q) return h("button", { onclick: () => send(a) }, describe(a));
    return predictionStrip(q, [outcomeNote(reveals[q.id]),
      h("button", { class: a.reveal ? "primary" : "", onclick: () => send(a) }, a.reveal ? t("Reveal") : t("Keep hidden after all"))]);
  });
}
function preregisteredRows() {  // they need no decision, so they come last
  const reveals = preview().reveals;
  const mine = reveals ? view().predictions.filter((q) => q.seat === msg.you && q.preregistered) : [];
  if (!mine.length) return null;
  return h("div", { class: "rows" }, groupLabel(t("Preregistered: revealed automatically")), mine.map((q) => predictionStrip(q, outcomeNote(reveals[q.id]))));
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
    title: proposed.includes(id) ? t("Auto-cite would choose this one") : null,
    onclick: () => toggle(id),
  }, methodLabel(id)));
}

// See Experimentation in the rulebook: free parameters, plus one per cited method. Citations made
// by hand are kept; auto-cite only adds what is still missing.
function experimentPlan(tpl) {
  const specified = inputVars().map((x) => x.id).filter((id) => task.picks[id]);
  const eligible = tpl.methods.filter((m) => specified.includes(m.parameter));
  const cited = eligible.filter((m) => task.cited.has(m.id));
  const need = Math.max(0, specified.length - tpl.free_input_parameters);
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
  return cell(h("button", { class: "picker", title: t("Click to change"), onclick: () => {
    task.picks[variable.id] = list[(list.indexOf(value) + 1) % list.length];
    redraw();
  } }, tile(value, emptyText)));
}

function experimentRows(option) {
  const tpl = option.template;
  const plan = experimentPlan(tpl);
  const slots = Object.fromEntries(Object.entries(task.picks).filter(([id, s]) => s && tpl.states[id]));
  const run = () => {
    const specified = Object.fromEntries(plan.specified.map((id) => [id, task.picks[id]]));
    sendThen({ type: "run_experiment", specified, cited_methods: [...plan.cited, ...plan.proposed].map((m) => m.id) },
      () => { task.picks = {}; task.cited = new Set(); });
  };
  const form = strip({ key: "form:experiment", head: t("New experiment"), sub: t("click a tile to choose"), slots,
    cellFor: (variable) => (variable.kind === "input" ? pickerCell(variable, tpl.states[variable.id], "random") : cell(tile(null, "result"))),
    tail: [
      h("button", { class: "primary", disabled: plan.possible ? null : true, onclick: run }, plan.ready ? t("Run") : t("Auto-cite and run")),
      h("button", { onclick: () => { task.picks = {}; task.cited = new Set(); redraw(); } }, t("Clear")),
    ] });
  const parameterOf = (id) => tpl.methods.find((m) => m.id === id).parameter;
  const toggle = (id) => {
    const had = task.cited.has(id);
    for (const other of [...task.cited]) if (parameterOf(other) === parameterOf(id)) task.cited.delete(other);  // one method per parameter
    if (!had) task.cited.add(id);
    redraw();
  };
  const ids = [...tpl.methods].map((m) => m.id).sort(byCitePreference);
  return [form,
    h("div", { class: "cite" }, t("{n} chosen, {free} free. Cite methods:", { n: plan.specified.length, free: tpl.free_input_parameters }),
      ids.length ? citeButtons(ids, plan.cited.map((m) => m.id), plan.proposed.map((m) => m.id), (id) => plan.specified.includes(parameterOf(id)), toggle) : h("span", { class: "muted" }, t("none available")),
      plan.possible ? null : h("span", { class: "note-bad" }, t("Not enough methods for these parameters: choose fewer."))),
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
  const verb = level ? t("Upgrade") : t("Install");
  const ids = [...choice.methods].sort(byCitePreference);
  const cited = ids.filter((id) => task.sensorCited.has(id));
  const proposed = ids.filter((id) => !task.sensorCited.has(id)).slice(0, Math.max(0, choice.methods_needed - cited.length));
  const ready = cited.length === choice.methods_needed;
  const toggle = (id) => { if (task.sensorCited.has(id)) task.sensorCited.delete(id); else task.sensorCited.add(id); redraw(); };
  const go = () => sendThen({ type: "install_sensor", probe, parameter, cited_methods: [...cited, ...proposed] },
    () => { task.sensor = null; task.sensorCited = new Set(); });
  const heading = level ? t("Upgrade the {parameter} sensor on P{probe}:", { parameter, probe: probe + 1 }) : t("Install the {parameter} sensor on P{probe}:", { parameter, probe: probe + 1 });
  return h("div", { class: "cite" }, h("b", {}, heading), t("cite {n}", { n: choice.methods_needed }),
    citeButtons(ids, cited, proposed, (id) => task.sensorCited.has(id) || !ready, toggle),
    h("button", { class: "primary", onclick: go }, ready ? verb : level ? t("Auto-cite and upgrade") : t("Auto-cite and install")),
    h("button", { onclick: () => { task.sensor = null; redraw(); } }, t("Cancel")));
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
  for (const i of v.lab.ideas) if (i.kind === "theory" && i.id !== except && theoryKey(i) === key) found.push(t("D{id} (development stack)", { id: i.id }));
  v.lab.pending.development.forEach((i, n) => { if (i.kind === "theory" && theoryKey(i) === key) found.push(t("choice {n} of this phase", { n: n + 1 })); });
  for (const m of v.manuscripts) {
    if (m.author === msg.you && m.id !== except && m.content && m.content.kind === "theory" && theoryKey(m.content) === key) {
      found.push(t("D{id} (submitted, {area})", { id: m.id, area: t(AREA_NAMES[m.area] || m.area) }));
    }
  }
  return found;
}

function theoryRows(option) {
  const tpl = option.template;
  const states = { ...tpl.inputs, ...tpl.outcomes };
  const pickedFrom = (group) => Object.fromEntries(Object.keys(group).filter((id) => task.picks[id]).map((id) => [id, task.picks[id]]));
  const idea = { inputs: pickedFrom(tpl.inputs), outcomes: pickedFrom(tpl.outcomes) };
  const slots = ideaSlots(idea);
  const published = hasStates(slots) ? publishedCopies(idea) : [];
  const own = hasStates(slots) ? ownCopies(idea) : [];
  const form = strip({ key: "form:theory", head: t("Your new theory"), sub: t("click a tile to change"), slots,
    cellFor: (variable) => pickerCell(variable, states[variable.id], "blank"),
    tail: [
      h("button", { class: "primary", disabled: published.length ? true : null, onclick: () => sendThen({ type: "formulate_theory", ...idea }, () => { task.picks = {}; }) }, t("Formulate")),
      h("button", { onclick: () => { task.picks = {}; redraw(); } }, t("Clear")),
    ] });
  return [form,
    published.length ? h("div", { class: "warn-bad" }, t("Already published as {list}: this theory could never be submitted.", { list: published.map((p) => `T${p.id} (${nameOf(p.author)})`).join(", ") })) : null,
    own.length ? h("div", { class: "warn" }, t("You already have this theory: {list}.", { list: own.join(", ") })) : null];
}

function pendingDevelopmentRows(option) {
  const pending = view().lab.pending.development;
  return [groupLabel(t("Chosen this phase")), option.actions.map((a) => {
    const i = pending[a.index];
    return strip({ key: `pending${a.index}`, head: t("Choice {n}", { n: a.index + 1 }), slots: i.kind === "theory" ? ideaSlots(i) : {},
      text: i.kind === "method" ? t("method for {parameter}", { parameter: i.parameter }) : null, tail: h("button", { onclick: () => send(a) }, t("Drop")) });
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
  const areas = [lab.records];
  if (spec.kind === "observation") {
    const o = areas.flatMap((x) => x.observations).find((x) => x.id === spec.observation);
    return { key: `${lab.seat}/O${spec.observation}`, head: `O${spec.observation}`, sub: o ? t("P{probe}, round {round}", { probe: o.probe + 1, round: o.round }) : "", slots: o ? o.cards : {} };
  }
  const experiments = areas.flatMap((x) => x.experiments);
  const slots = {};
  for (const [e, variable] of spec.cards) {
    const found = experiments.find((x) => x.id === e);
    if (found) slots[variable] = found.cards[variable];
  }
  const ids = [...new Set(spec.cards.map(([e]) => e))];
  const head = `E${ids.join("+")}`;
  return { key: `${lab.seat}/${head}`, head, sub: ids.length > 1 ? t("cards of different experiments") : t("experiment"), slots };
}

function chargeControl(box, tpl) {  // offered only when the fee and the charge together fit the money that may be spent
  const fee = tpl.submission_fee[String(box.tier)];
  const charge = tpl.apc[String(box.tier)];
  const reward = tpl.ac_reward ? tpl.ac_reward[String(box.tier)] : null;  // Publication scoring
  const worth = reward ? h("b", {}, t("published: +{n} AC", { n: reward[0] }), charge && reward[1] !== reward[0] ? ` ${t("(+{n} with open access)", { n: reward[1] })}` : "", "; ") : null;
  const text = h("span", {}, worth, t("fee {fee}; you can spend {n}", { fee, n: tpl.spendable }));
  if (!charge) return text;
  if (fee + charge > tpl.spendable) return [text, h("span", { class: "muted" }, ` ${t("(article processing charge {n}: not enough money)", { n: charge })}`)];
  return [text, h("label", {}, h("input", { type: "checkbox", checked: box.payApc ? true : null, onchange: (e) => { box.payApc = e.target.checked; redraw(); } }), ` ${t("pay the article processing charge ({n})", { n: charge })}`)];
}

function processingLine(box) {  // the projected rounds in processing (nv_core.preview)
  const p = (preview().processing || {})[`${box.manuscript}/${box.tier}`];
  if (!p) return null;
  const i = Math.min(Math.max(0, box.records.length - p.first_records), p.rounds.length - 1);
  const rounds = (box.payApc ? p.rounds_with_apc : p.rounds)[i];
  const bonuses = [
    [p.extra_records[i], t("extra record")], [p.extra_elements, t("extra element")], [box.payApc ? 1 : 0, t("article processing charge")],
    [p.hot_topic, t("hot topic")], [p.crisis, t("Crisis fast-track")],
  ].filter(([n]) => n);
  const shortened = bonuses.reduce((sum, [n]) => sum + n, 0);
  const parts = p.base ? [t("{n} for this journal tier", { n: p.base }), ...bonuses.map(([n, name]) => `\u2212${n} ${name}`)] : [t("none at this journal tier")];
  return h("span", { class: "processing" }, h("b", {}, t("Projected processing: {n} round(s)", { n: rounds })),
    ` (${parts.join(", ")}${p.base && p.base - shortened !== rounds ? `; ${t("cannot be shortened further")}` : ""}), ${t("if accepted this round")}`);
}

function submitBox(box, index, option) {
  const tpl = option.template;
  const id = `box${index}`;
  const select = () => { if (task.target !== index) { task.target = index; redraw(); } };
  if (box.manuscript === null) {
    return h("div", { class: `box${task.target === index ? " is-target" : ""}`, onclick: select },
      h("div", { class: "slot-hint" }, t("Empty submission box: press \"use\" on one of your theories or methods below.")));
  }
  const idea = view().lab.ideas.find((i) => i.id === box.manuscript);
  const listed = box.tier === null ? null : listedSubmission(box);
  const inBox = new Set(box.records.map(specKey));
  const others = boxCandidates(box).filter((c) => !inBox.has(specKey(c)));
  const short = listed ? listed.records.length - box.records.length : 0;
  const own = idea.kind === "theory" ? ownCopies(idea, idea.id) : [];
  const published = idea.kind === "theory" ? publishedCopies(idea) : [];
  const warnings = [
    own.length ? t("You already have a theory like this: {list}.", { list: own.join(", ") }) : "",
    published.length ? t("The same theory is already published as {list}.", { list: published.map((p) => `T${p.id} (${nameOf(p.author)})`).join(", ") }) : "",
  ].filter(Boolean);
  const submit = () => {  // duplicates are allowed (e.g. to fast-track a reformulated theory), so these only warn
    if (warnings.length && !window.confirm(`${warnings.join("\n")}\n\n${t("Are you sure you want to submit D{id}?", { id: idea.id })}`)) return;
    send({ ...listed, records: box.records, pay_apc: box.payApc });
  };
  return boxView({
    id, target: task.target === index, onclick: select,
    top: { key: `D${idea.id}`, head: `D${idea.id}`, sub: t("submission"), slots: idea.kind === "theory" ? ideaSlots(idea) : {},
      text: idea.kind === "method" ? t("method for {parameter}", { parameter: idea.parameter }) : null, tail: [
        h("button", { class: "primary", disabled: listed && short <= 0 ? null : true, onclick: submit }, t("Submit")),
        h("button", { onclick: () => { Object.assign(box, emptyBox()); task.target = index; redraw(); } }, t("Empty")),
      ] },
    records: box.records.map((spec, n) => ({ ...recordRow(spec), tail: h("button", { onclick: () => { box.records.splice(n, 1); redraw(); } }, t("Remove")) })),
    foot: [
      warnings.map((w) => h("div", { class: "warn" }, w)),
      h("span", {}, t("Journal tier:"), " ", tiersFor(idea.id).map((n) => h("button", { class: box.tier === n ? "on" : "", onclick: () => { chooseTier(box, n); redraw(); } }, String(n)))),
      listed ? chargeControl(box, tpl) : h("span", { class: "muted" }, t("choose a tier")),
      listed ? processingLine(box) : null,
      short > 0 ? h("span", { class: "note-bad" }, t("at least {n} more record(s) needed", { n: short })) : null,
      others.length ? h("span", {}, t("Add a record:"), " ", others.map((c) => h("button", { onclick: () => { box.records.push(c); redraw(); } }, recordRow(c).head))) : null,
    ],
  });
}

function submitRows(option) {
  const ideas = view().lab.ideas;
  for (const box of task.boxes) if (box.manuscript !== null && (!ideas.some((i) => i.id === box.manuscript) || !tiersFor(box.manuscript).length)) Object.assign(box, emptyBox());
  if (!task.boxes.length) task.boxes.push(emptyBox());
  task.target = Math.min(task.target, task.boxes.length - 1);
  return [task.boxes.map((box, i) => submitBox(box, i, option)),
    h("div", { class: "box-foot" }, h("button", { onclick: () => { task.boxes.push(emptyBox()); task.target = task.boxes.length - 1; redraw(); } }, t("Add a submission box")))];
}

function manuscriptActionRows(option, label) {  // revising and withdrawing: the manuscript's strip with one button
  return option.actions.map((a) => {
    const m = view().manuscripts.find((x) => x.id === a.manuscript);
    const button = h("button", { onclick: () => send(a) }, label);
    return m ? manuscriptBox(m, { id: `${option.type}${m.id}`, sub: t(AREA_NAMES[m.area] || m.area), tail: button }) : button;
  });
}

function reviewRows(option) {
  const votes = view().lab.pending.votes || {};
  const isOwn = (card) => { const m = manuscriptUnderReview(myReviewCards()[card]); return Boolean(m && m.author === msg.you); };
  const cards = [...new Set(option.actions.map((a) => a.card))].sort((a, b) => isOwn(b) - isOwn(a) || a - b);  // your own on top
  return cards.map((card) => {
    const position = myReviewCards()[card];
    const m = manuscriptUnderReview(position);
    const twice = myReviewCards().filter((c) => c === position).length > 1 ? `, ${t("your card {n}", { n: card + 1 })}` : "";
    const tail = option.actions.filter((a) => a.card === card).map((a) =>
      h("button", { class: votes[String(card)] === a.vote ? "primary" : "", onclick: () => send(a) }, t(a.vote)));
    if (!m) return h("div", { class: "form-row" }, `${t("awaiting peer review")} #${position}${twice} `, tail);
    const own = isOwn(card);
    return manuscriptBox(m, { id: `review${card}`, sub: `#${position}${twice}, ${t("tier {n}", { n: m.tier })}, ${own ? "" : authorLabel(m)}`, subStrong: own ? authorLabel(m) : null, tail });
  });
}

// Smaller choices -----------------------------------------------------------------------------------
function describe(a) {
  const n = (seat) => nameOf(seat);
  switch (a.type) {
    case "claim_probe_time": return t("Take Probe time on P{probe}", { probe: a.probe + 1 });
    case "reveal_prediction": return a.reveal ? t("Reveal Q{id}", { id: a.prediction }) : t("Keep Q{id} hidden after all", { id: a.prediction });
    case "develop_method": return t("Develop a method for {parameter}", { parameter: a.parameter });
    case "propose_alliance": return t("Propose an alliance to {name}", { name: n(a.partner) });
    case "accept_alliance": return t("Accept the alliance with {name}", { name: n(a.partner) });
    case "leave_alliance": return t("Leave the alliance with {name}", { name: n(a.partner) });
    case "stay_in_alliance": return t("Stay in the alliance with {name}", { name: n(a.partner) });
    default: return JSON.stringify(a);
  }
}

function completeActions(option) {
  const items = option.actions;
  if (items.length <= 8) return items.map((a) => h("button", { onclick: () => send(a) }, describe(a)));
  const select = h("select", {}, items.map((a, i) => h("option", { value: i }, describe(a))));
  return [select, h("button", { onclick: () => send(items[Number(select.value)]) }, t("Do it"))];
}

// A number box with a larger - and + on either side. The box itself is in .box; read .value as usual.
function taskLabel(name) {  // a staff task, with what the Grant funding position asks of the Grants row
  const needed = preview().grant_admin_needed;
  const label = tTask(name);
  return name === "grants" && needed !== undefined ? [label, h("span", { class: "grant-need" }, t("grant track needs: {n}", { n: needed }))] : label;
}

function numberInput(value, min, max, disabled) {
  const limited = max !== null && max !== undefined;
  const input = h("input", { type: "number", class: "plain", value, min, max: limited ? max : false, disabled: disabled ? true : null });
  const step = (by) => {
    input.value = Math.min(limited ? max : Infinity, Math.max(min, (Number(input.value) || 0) + by));
    input.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const button = (text, by, title) => h("button", { type: "button", title, disabled: disabled ? true : null, onclick: () => step(by) }, text);
  input.box = h("span", { class: "stepper" }, button("\u2212", -1, t("One less")), input, button("+", 1, t("One more")));
  return input;
}

function allocateForm(tpl) {
  const pending = view().lab.pending.allocation;
  const now = tpl.postdocs_now;
  const [low, high] = tpl.postdocs_after;
  const postdocs = numberInput(pending ? now + pending.hire_postdocs - pending.fire_postdocs : now, low, high);
  const students = numberInput(pending ? pending.hire_students : 0, 0, tpl.max_students);
  const noStudents = simplified();  // the simplified game has no students: no Students column
  const inputs = {};
  const caps = tpl.task_caps || {};  // the most staff a task takes: Talent development, and Experimentation (lab capacity)
  const cap = (task) => (task in caps ? caps[task] : tpl.at_most_one.includes(task) ? 1 : null);
  const rowsByTask = {};
  const rows = [...tpl.tasks].sort((a, b) => taskOrder(a) - taskOrder(b)).map((task) => {
    const current = pending && pending.allocation[task] ? pending.allocation[task] : { postdocs: 0, students: 0 };
    const p = numberInput(current.postdocs, 0, cap(task));
    const s = numberInput(current.students, 0, cap(task), tpl.postdoc_only.includes(task));
    inputs[task] = [p, s];
    rowsByTask[task] = [p, s];
    const limit = task in caps && !tpl.at_most_one.includes(task) ? h("div", { class: "muted" }, t("at most {n} (lab capacity)", { n: caps[task] })) : null;
    return [h("span", {}, taskLabel(task), limit), tWhen(task), p.box, ...(noStudents ? [] : [s.box])];
  });
  const totals = { postdocs: h("b", {}), students: h("b", {}) };
  const allocationTable = noStudents
    ? table([t("Task"), t("When"), t("Postdocs")], [...rows, [h("b", {}, t("Allocated")), "", totals.postdocs]])
    : table([t("Task"), t("When"), t("Postdocs"), t("Students")], [...rows, [h("b", {}, t("Allocated")), "", totals.postdocs, totals.students]]);
  allocationTable.classList.add("alloc");
  const button = h("button", { class: "primary", title: t("Hire, fire and allocate as shown, and commit: final for this round"), onclick: () => {
    const after = Number(postdocs.value);
    const allocation = {};
    for (const [task, [p, s]] of Object.entries(inputs)) {
      const count = { postdocs: Number(p.value) || 0, students: Number(s.value) || 0 };
      if (count.postdocs || count.students) allocation[task] = count;
    }
    sendAndCommit({ type: "allocate_staff", hire_postdocs: Math.max(0, after - now), fire_postdocs: Math.max(0, now - after),
      hire_students: Number(students.value) || 0, allocation });
  } }, t("Commit"));
  // Each staff column: grey until every hired staff member of that type has a task, red if too many do.
  const update = () => {
    const wanted = { postdocs: Number(postdocs.value) || 0, students: Number(students.value) || 0 };
    const given = { postdocs: 0, students: 0 };
    for (const [p, s] of Object.values(inputs)) { given.postdocs += Number(p.value) || 0; given.students += Number(s.value) || 0; }
    for (const kind of Object.keys(wanted)) {
      allocationTable.classList.toggle(`${kind}-over`, given[kind] > wanted[kind]);
      allocationTable.classList.toggle(`${kind}-short`, given[kind] < wanted[kind]);
      totals[kind].textContent = t("{n} of {m}", { n: given[kind], m: wanted[kind] });
    }
    let overCap = false;
    for (const [task, [p, s]] of Object.entries(rowsByTask)) {
      const over = cap(task) !== null && (Number(p.value) || 0) + (Number(s.value) || 0) > cap(task);
      p.classList.toggle("over", over);
      s.classList.toggle("over", over);
      overCap = overCap || over;
    }
    button.disabled = given.postdocs !== wanted.postdocs || given.students !== wanted.students || overCap;
  };
  for (const input of [postdocs, students, ...Object.values(inputs).flat()]) input.oninput = update;
  const maxButton = (input, limit) => (limit === null ? null : h("button", { type: "button", title: t("As many as you can"), onclick: () => { input.value = limit; update(); } }, t("max")));
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
    h("div", { class: "form-row hire-row" }, t("You have {n} postdoc(s). Postdocs after hiring/firing:", { n: now }), " ", postdocs.box, maxButton(postdocs, high),
      ` (${t("{low} to {high}", { low, high: high === null ? t("any") : high })}) `,
      ...(noStudents ? [] : [`\u00b7 ${t("students to hire:")} `, students.box, maxButton(students, tpl.max_students), ` (${t("at most {n}", { n: tpl.max_students })}) `]),
      h("button", { type: "button", disabled: previous ? null : true, title: t("Fill in the task allocation of your last round"), onclick: repeat }, t("Repeat"))),
    allocationTable,
    h("div", { class: "small muted" }, (noStudents ? t("Every staff member needs a task") : t("Every staff member needs a task; Development and Talent development take postdocs only; at most one on Talent development"))
      + (caps.experimentation !== undefined ? `; ${t("at most {n} on Experimentation (your lab capacity).", { n: caps.experimentation })}` : ".")),
    button,
  ];
}

function leavingForm(tpl) {
  const inputs = Object.entries(tpl.students_by_task).sort(([a], [b]) => taskOrder(a) - taskOrder(b))
    .map(([task, n]) => [task, numberInput(0, 0, n), n]);
  return [
    h("p", {}, t("{n} student(s) must leave. Choose from which tasks:", { n: tpl.count })),
    table([t("Task"), t("When"), t("Students there"), t("Leaving")], inputs.map(([task, input, n]) => [taskLabel(task), tWhen(task), n, input.box])),
    h("button", { class: "primary", title: t("These students leave; final for this round"), onclick: () => {
      const by_task = {};
      for (const [task, input] of inputs) if (Number(input.value)) by_task[task] = Number(input.value);
      sendAndCommit({ type: "choose_leaving_students", by_task });
    } }, t("Commit")),
  ];
}

function orderForm(tpl) {
  const input = h("input", { value: tpl.predictions.map((id) => `Q${id}`).join(", "), size: 30 });
  return [h("p", { class: "small" }, t("Several of your predictions are on the same Probe: the order in which they are scored.")), input,
    h("button", { onclick: () => send({ type: "order_predictions", order: input.value.split(",").map((x) => Number(x.trim().replace(/^Q/, ""))) }) }, t("Set the order"))];
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
  order_predictions: (o) => orderForm(o.template), revise: (o) => manuscriptActionRows(o, t("Revise")),
  withdraw_submission: (o) => manuscriptActionRows(o, t("Withdraw")), archive_records: (o) => archiveForm(o.template),
};
const TITLES = {
  allocate_staff: "Hiring and task allocation", choose_leaving_students: "Student task check", claim_probe_time: "Probe time",
  order_predictions: "Scoring order", develop_method: "Develop a method", revise: "Revise a manuscript", archive_records: "Archive records",
  withdraw_submission: "Undo this step's submission or revision", leave_alliance: "Last chance to leave an alliance",
  stay_in_alliance: "Stay in an alliance",
};
const TASK_NAMES = {
  make_prediction: ["make predictions", 'your own theories first, then those closest to the Nobel Prize. Click a Probe in the World Grid to see which theories fit it. Amounts apply if revealed.'],
  cancel_prediction: ["make predictions", ""],
  reveal_prediction: ["reveal predictions", "what each would bring"],
  run_experiment: ["experiments and sensors", 'press "+" on a Probe tile to install or upgrade its sensor'],
  formulate_theory: ["formulate a theory", 'press "use" on a record, or on the selected strip, to copy its states here'],
  submit: ["submit manuscripts", 'the outlined box receives what you "use"'],
  review_vote: ["peer review", "open a box to see the manuscript's supporting records"],
};
const IN_THE_TITLE = { commit: "Commit", pass: "Pass", expand_lab: "Lab capacity +1" };
const COMMIT_HELP = { commit: "My choices for this step are final", pass: "Stop experimenting this round",
  expand_lab: "Pay to increase your lab capacity by 1 (once a round). It uses no staff member and does not end your turn; the new capacity counts from the next Hiring." };

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
  if (nothingSubmittedYet()) return t("You have not submitted or revised a manuscript in this step.");
  if (nothingDevelopedYet()) return t("You have staff on Development but have not formulated a theory or developed a method.");
  return null;
}
function titleButton(option) {
  const warning = option.type === "commit" ? commitWarning() : null;
  return h("button", {
    class: warning ? "commit-waiting" : option.type === "commit" ? "primary" : "",
    title: warning || t(COMMIT_HELP[option.type]),
    onclick: () => {
      if (warning && !window.confirm(`${warning}\n\n${t("Commit anyway?")}`)) return;
      send(option.actions[0]);
    },
  }, option.type === "expand_lab" ? `${t(IN_THE_TITLE.expand_lab)} (${t("costs {n}", { n: view().researchers[msg.you].lab_capacity_cost })})` : t(IN_THE_TITLE[option.type]));
}

function setTaskHeading(name, note, buttons) {
  const phase = view() ? view().phase : null;
  $("actions-title").textContent = [phase && t(phase), name && t(name)].filter(Boolean).join(" \u00b7 ") || t("What you can do now");
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
const REPORT_OUTCOMES = { success: ["good", "Success"], failed: ["bad", "Failed"], pruned: ["muted", "Pruned"] /* older games */, unscored: ["muted", "Not scored: the game ended"] };
function reportEntry(p) {
  const [cls, label] = REPORT_OUTCOMES[p.outcome];
  const patent = p.patent === "new" ? t("patent") : p.patent === "held" ? (p.patent_holder === p.seat ? t("already holds its patent") : t("no patent ({name} holds it)", { name: nameOf(p.patent_holder) })) : null;
  const row = strip({ key: `report${p.id}`, head: `T${p.theory}`, sub: `P${p.probe + 1}${p.preregistered ? `, ${t("preregistered")}` : ""}`, slots: { ...p.inputs, ...p.outcomes }, tail: [
    h("b", { class: cls }, t(label)),
    p.credit === null ? null : info(t("{n} AC", { n: signed(p.credit) })),
    p.author_credit ? info(`${nameOf(p.author)} ${t("{n} as author", { n: signed(p.author_credit) })}`) : null,
    patent ? info(patent) : null,
  ] });
  if (!p.nobel) return row;
  return h("div", { class: "report-nobel" }, row, h("div", { class: "nobel-note" }, t("Nobel Prize! This prediction completed the streak of T{theory}: {name} wins the Nobel Prize.", { theory: p.theory, name: nameOf(p.author) })));
}
function showReport(box, report) {
  $("actions-title").textContent = t("Prediction report, round {n}", { n: report.round });
  fill($("task-buttons"), h("button", { class: "primary", title: t("Go on with the game"), onclick: () => {
    store.set("report", String(report.round));
    actionsShown = null;
    renderActions();
  } }, t("Next")));
  const seats = [...new Set(report.predictions.map((p) => p.seat))].sort((a, b) => a - b);
  const missed = report.missed.map((p) => `P${p + 1}`).join(", ");
  fill(box,
    report.crisis ? h("p", { class: "small bad" }, t("Crisis: {n} of {max} unsuccessful predictions so far.", { n: report.unsuccessful, max: report.crisis_condition }),
      missed ? ` ${t("No prediction on {list}: each counts as unsuccessful.", { list: missed })}` : "") : null,
    seats.length ? h("div", { class: "report" }, seats.map((seat) => recordArea(chip(seat), "", report.predictions.filter((p) => p.seat === seat).map(reportEntry))))
      : h("p", { class: "muted" }, t("Nobody revealed a prediction.")));
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
  if (v.result || msg.status !== "running") { box.append(h("p", { class: "muted" }, t("Nothing to do."))); return; }
  if (msg.options.every((o) => o.type === "alliance" || o.type === "expand_lab")) {  // alliances have their own panel
    setTaskHeading(null, null, msg.options.filter((o) => o.type === "expand_lab").map(titleButton));
    box.append(h("p", { class: "muted" }, msg.seats[msg.you] && msg.seats[msg.you].kind !== "human"
      ? t("Your seat is played by an automated player ({kind}) for now.", { kind: t(msg.seats[msg.you].kind) }) : t("Nothing to do right now; others are deciding.")));
    const preregistered = preregisteredRows();
    if (preregistered) box.append(preregistered);
    return;
  }
  const named = msg.options.find((o) => TASK_NAMES[o.type]);
  let [name, note] = named ? TASK_NAMES[named.type] : [null, null];
  note = note ? t(note) : note;
  const limit = preview().prediction_limit;  // Formulating predictions and preregistration
  if (limit) note = `${t("{n} of {max} predictions made", { n: limit.made, max: limit.allowed })}${limit.made >= limit.allowed ? ` ${t("(no room for more)")}` : ""}. ${note || ""}`;
  // Hiring and the Student task check commit from their own form, so the choice and the commit are one click.
  const formCommits = optionOf("allocate_staff") || optionOf("choose_leaving_students");
  setTaskHeading(name, note, msg.options.filter((o) => IN_THE_TITLE[o.type] && !(formCommits && o.type === "commit")).map(titleButton));
  // The sensor choices are drawn with the experiment; withdrawing is done on the prediction strips.
  const listed = msg.options.filter((o) => !IN_THE_TITLE[o.type] && !["install_sensor", "cancel_prediction", "alliance"].includes(o.type));
  if (optionOf("cancel_prediction") && !optionOf("make_prediction")) box.append(h("div", { class: "rows" }, predictionRows(null)));
  for (const option of listed) {
    if (TASK_ROWS[option.type]) box.append(h("div", { class: "rows" }, TASK_ROWS[option.type](option)));
    else box.append(h("div", { class: "option" }, h("h3", {}, t(TITLES[option.type] || option.type)), FORMS[option.type] ? FORMS[option.type](option) : completeActions(option)));
  }
  const preregistered = preregisteredRows();
  if (preregistered) box.append(preregistered);
  box.scrollTop = scrolled;
}

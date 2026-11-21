// Reports (specification 7.4): at the end of each part of the round, the task panel shows what
// every researcher did and what it earned, the player's own section first. "Next" closes a report;
// it is the player's own panel that waits, never the game. The Reports panel in the right column
// turns the reports of each part on or off and shows the latest one again.
"use strict";

// The parts of a round, in order. The prediction report comes from the engine's scoring; the others
// are lists of the events of that part (nv_core/engine/reports.py).
const REPORT_PARTS = [
  ["hiring", "Hiring", "Hiring report, round {n}"],
  ["experimentation", "Experimentation and Probe time", "Experimentation report, round {n}"],
  ["prediction", "Predictions", "Prediction report, round {n}"],
  ["publication", "Development and publication", "Publication report, round {n}"],
  ["cleanup", "Talent development and clean-up", "Clean-up report, round {n}"],
];
const REPORT_INDEX = Object.fromEntries(REPORT_PARTS.map(([kind], i) => [kind, i + 1]));
const reportPosition = (x) => x.report.round * 10 + REPORT_INDEX[x.kind];

let reportAgain = null;  // the part whose latest report "show again" asked for

function latestReports() {  // [{kind, report}], oldest first
  const v = view();
  const found = Object.entries(v.reports || {}).filter(([, report]) => report).map(([kind, report]) => ({ kind, report }));
  if (v.prediction_report) found.push({ kind: "prediction", report: v.prediction_report });
  return found.sort((a, b) => reportPosition(a) - reportPosition(b));
}
const reportsFor = () => !msg.spectator && msg.you !== null && msg.seats[msg.you] && msg.seats[msg.you].kind === "human";
const reportOn = (kind) => !prefs.reportsAllOff && !prefs.reportsOff[kind];
const reportSeen = (x) => store.get(`report:${x.kind}`) === String(x.report.round)
  || (x.kind === "prediction" && store.get("report") === String(x.report.round));  // the key before the other reports existed
const markSeen = (x) => store.set(`report:${x.kind}`, String(x.report.round));

// The report the task panel shows now, if any: one asked for again, or the oldest one not yet
// closed from the latest round of reports (a player who was away sees them one after the other).
function pendingReport() {
  if (!reportsFor()) return null;
  const all = latestReports();
  if (reportAgain) {
    const again = all.find((x) => x.kind === reportAgain);
    if (again) return { ...again, again: true };
    reportAgain = null;
  }
  if (!all.length) return null;
  const newest = reportPosition(all[all.length - 1]);
  return all.find((x) => reportPosition(x) > newest - 10 && reportOn(x.kind) && !reportSeen(x)) || null;
}

function closeReport(x) {
  markSeen(x);
  reportAgain = null;
  actionsShown = null;
  renderActions();
  refreshHighlights();
  renderReportsPanel();
}
function stopReports(x, all) {
  if (all) {
    prefs.reportsAllOff = true;
    latestReports().forEach(markSeen);
  } else {
    prefs.reportsOff[x.kind] = true;
  }
  savePrefs();
  closeReport(x);
}

// The player first, then the others in turn order after them.
function seatsFromMe() {
  const order = view().turn_order;
  const at = order.indexOf(msg.you);
  return at < 0 ? order : [...order.slice(at), ...order.slice(0, at)];
}

function showReport(box, x) {
  const [, , title] = REPORT_PARTS.find(([kind]) => kind === x.kind);
  $("actions-title").textContent = t(title, { n: x.report.round });
  $("actions-note").textContent = x.again ? t("shown again") : "";
  fill($("task-buttons"),
    h("button", { title: t("Turn off the reports of this part of the round (the Reports panel turns them on again)"), onclick: () => stopReports(x, false) }, t("Stop reports on this phase")),
    h("button", { title: t("Turn off every report (the Reports panel turns them on again)"), onclick: () => stopReports(x, true) }, t("Stop all reports")),
    h("button", { class: "primary", title: t("Go on with the game"), onclick: () => closeReport(x) }, t("Next")));
  fill(box, x.kind === "prediction" ? predictionReportBody(x.report) : phaseReportBody(x.report, x.kind));
}

// The prediction report ------------------------------------------------------------------------------
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
function predictionReportBody(report) {
  const seats = seatsFromMe().filter((seat) => report.predictions.some((p) => p.seat === seat));
  const missed = report.missed.map((p) => `P${p + 1}`).join(", ");
  return [
    report.crisis ? h("p", { class: "small bad" }, t("Crisis: {n} of {max} unsuccessful predictions so far.", { n: report.unsuccessful, max: report.crisis_condition }),
      missed ? ` ${t("No prediction on {list}: each counts as unsuccessful.", { list: missed })}` : "") : null,
    seats.length ? h("div", { class: "report" }, seats.map((seat) => recordArea(chip(seat), "", report.predictions.filter((p) => p.seat === seat).map(reportEntry))))
      : h("p", { class: "muted" }, t("Nobody revealed a prediction.")),
    // The round's World Grid, to study as long as the player likes (the Probes are cleared after scoring).
    report.grid ? h("div", { class: "report-grid" }, h("h3", {}, t("World Grid of round {n}", { n: report.round })),
      report.grid.map((p) => probeStrip(p, report.round))) : null,
  ];
}

// The other reports: one line per event, through t() where the event's data allows it (otherwise
// the event log's English text) ---------------------------------------------------------------------
const reportTask = (task) => t(task.replaceAll("_", " "));
const citing = (ids) => (ids && ids.length ? t(", citing {list}", { list: ids.map((id) => `M${id}`).join(", ") }) : "");
const positions = (cards) => cards.map((c) => (c ? `#${c}` : "-")).join(", ");
const ALLIANCE_LINES = { propose: "Proposes an alliance to {name}.", form: "Forms an alliance with {name}.", leave: "Leaves the alliance with {name}." };

// Each returns a text, a strip (or a list of them), or false to fall back on the event's own text.
const REPORT_LINES = {
  allocation: (d) => Boolean(d.staff) && t("Hires {p} postdoc(s), fires {f} and hires {s} student(s). Staff: {tasks}.", {
    p: d.hired_postdocs, f: d.fired_postdocs, s: d.hired_students,
    tasks: Object.entries(d.staff).map(([task, [p, s]]) => `${reportTask(task)} ${p}p+${s}s`).join(", ") || t("none"),
  }),
  period_deck: (d) => d.revealed !== undefined && t("{n} Game Period card(s) revealed; {left} left.", { n: d.revealed, left: d.left }),
  warning_shot: () => t("The Warning shot card is revealed: last chance to leave alliances."),
  crisis: () => t("The Crisis card is revealed: the Crisis period starts."),
  student_check: (d) => d.students !== undefined && t("Rolls {dice} for {n} student(s): {k} below {threshold} leave.", { dice: d.dice.join(", "), n: d.students, k: d.leaving, threshold: d.threshold }),
  student_leaves: (d) => d.count !== undefined && t("{n} student(s) on {task} leave the lab.", { n: d.count, task: reportTask(d.task) }),
  alliance: (d) => (d.action === "final" ? t("Alliances are now unbreakable.") : Boolean(ALLIANCE_LINES[d.action]) && t(ALLIANCE_LINES[d.action], { name: nameOf(d.partner) })),
  experiment: (d) => d.specified !== undefined && `${t("Runs an experiment{citing}.", { citing: citing(d.cited) })}${d.specified.length ? ` ${t("Specified: {list}.", { list: d.specified.join(", ") })}` : ""}`,
  experiment_result: (d) => Boolean(d.inputs) && strip({ key: `report-E${d.experiment}`, head: `E${d.experiment}`, sub: t("your result"), slots: { ...d.inputs, ...d.outcomes } }),
  sensor: (d) => d.cited !== undefined && t(d.level > 1 ? "Upgrades the {parameter} sensor on P{probe} to level {level}{citing}." : "Installs the {parameter} sensor on P{probe}{citing}.",
    { parameter: d.parameter, probe: d.probe + 1, level: d.level, citing: citing(d.cited) }),
  probe_time: (d) => d.probe !== undefined && t(d.sensor ? "Gets Probe time on P{n} with the sensor." : "Takes Probe time on P{n}.", { n: d.probe + 1 }),
  pass: () => t("Passes."),
  lab_capacity: (d) => d.cost !== undefined && t("Pays {cost} to increase the lab capacity to {n}.", { cost: d.cost, n: d.capacity }),
  archive: (d) => d.count !== undefined && t("Archives {n} record(s).", { n: d.count }),
  archive_private: (d) => Boolean(d.records) && t("Archived: {list}.", { list: d.records.join(", ") }),
  development: (d) => d.count !== undefined && t("Adds {n} development stack(s).", { n: d.count }),
  development_private: (d) => Boolean(d.ideas) && d.ideas.map((i) => ideaStrip(i, { key: `report-D${i.id}`, sub: t("new") })),
  accept: (d) => d.count !== undefined && t("{n} development stack(s) go to the Accept area.", { n: d.count }),
  submission: (d) => d.tier !== undefined && t("Submits D{m} to tier {tier} with {n} record(s){oa}.", { m: d.manuscript, tier: d.tier, n: d.records, oa: d.open_access ? t(", open access") : "" }),
  revision: (d) => d.manuscript !== undefined && t("Revises D{m}.", { m: d.manuscript }),
  withdrawal: (d) => Boolean(d.what) && t(d.what === "revision" ? "Withdraws the revision of D{m}." : "Withdraws the submission of D{m}.", { m: d.manuscript }),
  review_cards: (d) => Boolean(d.cards) && t("Gets peer review card(s): {list}.", { list: positions(d.cards) }),
  review_draws: (d) => Boolean(d.draws) && t("Random peer review draws: {list}.", { list: positions(d.draws) || "-" }),
  review_decision: (d) => d.accepts !== undefined && t(d.accepted ? "D{m} (#{position}): {a} accept, {r} revise, so it goes to the Accept area." : "D{m} (#{position}): {a} accept, {r} revise, so it goes to the Revise area.",
    { m: d.manuscript, position: d.position, a: d.accepts, r: d.revises }),
  accept_area: (d) => d.tokens !== undefined && t("D{m} enters the Accept area: {n} round(s) in processing.", { m: d.manuscript, n: d.tokens }),
  talent: (d) => d.position !== undefined && t(d.up ? "Advances to {n} on the Talent development track." : "Moves back to {n} on the Talent development track.", { n: d.position }),
  unpaid: (d) => d.count !== undefined && t("Cannot pay {n} postdoc(s), who leave.", { n: d.count }),
  published: (d) => Boolean(d.idea) && strip({ key: `${d.idea.kind === "theory" ? "T" : "M"}${d.paper}`, head: `${d.idea.kind === "theory" ? "T" : "M"}${d.paper}`,
    sub: t("published from D{m}, tier {tier}", { m: d.manuscript, tier: d.tier }), slots: d.idea.kind === "theory" ? ideaSlots(d.idea) : {},
    text: d.idea.kind === "method" ? t("method for {parameter}", { parameter: d.idea.parameter }) : null }),
  grant: (d) => d.position !== undefined && t(d.up ? "Moves up to position {n} on the Grant funding track." : "Moves down to position {n} on the Grant funding track.", { n: d.position }),
  funding: (d) => d.money !== undefined && (d.patents
    ? t("Receives {n} money for the next round ({p} of it from {k} patent(s)).", { n: d.money, p: d.patent_money, k: d.patents })
    : t("Receives {n} money for the next round.", { n: d.money })),
  records_discarded: (d) => d.beyond !== undefined && t("Discards {n} record(s) in the Clean-up phase.", { n: d.beyond + d.invalid }),
};

function reportLine(item) {
  const make = REPORT_LINES[item.kind];
  const made = make ? make(item.data || {}) : false;
  if (made instanceof Node || Array.isArray(made)) return made;
  return h("div", { class: "report-line" }, made || item.text);
}

function creditLine(report, seat) {
  const own = report.credits.filter((c) => c.seat === seat);
  const after = report.after[seat];
  if (!own.length) return h("div", { class: "report-credit muted" }, t("Academic credit: {n}, no change.", { n: after }));
  const before = report.before ? report.before[seat] : null;
  return h("div", { class: "report-credit" },
    h("b", {}, before === null ? t("Academic credit: now {n}", { n: after }) : t("Academic credit: {a} \u2192 {b}", { a: before, b: after })),
    ` (${own.map((c) => `${c.reason}: ${signed(c.amount)}`).join("; ")})`);
}

// The hiring report's staff table: the allocation form's rows, one column per researcher, counting
// the staff who stayed after the Student task check; the students who left are a row of their own.
const IN_THE_HIRING_TABLE = new Set(["allocation", "student_check", "student_leaves"]);
function hiringTable(report) {
  const seats = seatsFromMe();
  const staff = {};  // seat -> task -> [postdocs, students]
  const hired = {};
  const left = {};
  for (const item of report.items) {
    const d = item.data || {};
    if (item.kind === "allocation" && d.staff) {
      staff[item.seat] = Object.fromEntries(Object.entries(d.staff).map(([task, [p, s]]) => [task, [p, s]]));
      hired[item.seat] = d;
    } else if (item.kind === "student_leaves" && d.count !== undefined) {
      left[item.seat] = (left[item.seat] || 0) + d.count;
      const cell = (staff[item.seat] || {})[d.task];
      if (cell) cell[1] = Math.max(0, cell[1] - d.count);
    }
  }
  if (!Object.keys(staff).length) return null;
  const noStudents = simplified();
  const total = (seat) => Object.values(staff[seat] || {}).reduce(([p, s], [a, b]) => [p + a, s + b], [0, 0]);
  // Every task of the allocation form (the simplified game has no publication, Talent development or Grants tasks).
  const formTasks = noStudents ? ["experimentation", "data_collection", "development"] : TASK_ORDER;
  const used = Object.values(staff).flatMap((x) => Object.keys(x));
  const tasks = [...new Set([...formTasks, ...used])].sort((a, b) => taskOrder(a) - taskOrder(b));
  const cellOf = (seat, task) => (staff[seat] || {})[task] || [0, 0];
  // A task's staff as tokens: a white P per postdoc, a grey S per student, overlapping.
  const tokens = (p, s) => {
    const list = [...Array(p).fill("P"), ...Array(noStudents ? 0 : s).fill("S")];
    return list.length ? h("span", { class: "chip-stack" }, list.map((x) => h("span", { class: `token staff-${x}`, title: x === "P" ? t("postdoc") : t("student") }, x))) : "";
  };
  // The totals below as numbers: "1 P · 2 S".
  const numbers = (p, s, strong) => {
    const parts = [p ? `${p} P` : null, s && !noStudents ? `${s} S` : null].filter(Boolean).join(" \u00b7 ");
    return parts ? (strong ? h("b", {}, parts) : parts) : "";
  };
  const row = (cells, cls) => h("tr", { class: cls || null }, cells.map((c) => h("td", {}, c)));
  const body = tasks.map((task) => row([taskName(task), ...seats.map((seat) => tokens(...cellOf(seat, task)))]));
  body.push(h("tr", { class: "gap" }, h("td", { colspan: 1 + seats.length })));
  body.push(row([h("b", {}, t("Staff")), ...seats.map((seat) => numbers(...total(seat), true))], "summary"));
  body.push(row([t("Hired"), ...seats.map((seat) => (hired[seat] ? numbers(hired[seat].hired_postdocs, hired[seat].hired_students) : ""))], "summary"));
  body.push(row([t("Fired"), ...seats.map((seat) => (hired[seat] ? numbers(hired[seat].fired_postdocs, 0) : ""))], "summary"));
  if (!noStudents) body.push(row([t("Students who left"), ...seats.map((seat) => (left[seat] ? h("b", { class: "bad" }, `${left[seat]} S`) : ""))], "summary"));
  return h("table", { class: "hire-report" },
    h("tr", {}, h("th", {}, t("Task")), seats.map((seat) => h("th", {}, chip(seat)))), body);
}

function phaseReportBody(report, kind) {
  const general = report.items.filter((i) => i.seat === null || i.seat === undefined);
  const hiring = kind === "hiring" ? hiringTable(report) : null;
  const shown = (i) => !hiring || !IN_THE_HIRING_TABLE.has(i.kind);
  return [
    hiring,
    general.length ? h("div", { class: "report-general" }, general.map(reportLine)) : null,
    h("div", { class: "report" }, seatsFromMe().map((seat) => {
      const lines = report.items.filter((i) => i.seat === seat && shown(i)).map(reportLine);
      return recordArea(chip(seat), "", [lines.length ? lines : h("div", { class: "report-line muted" }, t("Nothing to report.")), creditLine(report, seat)]);
    })),
  ];
}

// The Reports panel (right column, low) -------------------------------------------------------------
function setReportsOn(kinds, on) {
  // Turning reports on again starts with the next ones: the latest are not shown at once.
  for (const kind of kinds) {
    if (kind === "all") prefs.reportsAllOff = !on;
    else prefs.reportsOff[kind] = !on;
  }
  if (on) latestReports().filter((x) => kinds.includes("all") || kinds.includes(x.kind)).forEach(markSeen);
  savePrefs();
  actionsShown = null;
  renderActions();
  refreshHighlights();
  renderReportsPanel();
}
function showAgain(kind) {
  reportAgain = kind;
  actionsShown = null;
  const panel = $("actions-panel");
  if (panel.classList.contains("closed")) panel.querySelector("h2 .flip").click();
  renderActions();
  refreshHighlights();
  panel.scrollIntoView({ block: "start", behavior: "smooth" });
}

function renderReportsPanel() {
  const panel = $("reports-panel");
  panel.style.display = view() && reportsFor() ? "" : "none";
  if (panel.style.display === "none") return;
  const latest = Object.fromEntries(latestReports().map((x) => [x.kind, x]));
  const box = (checked, disabled, onchange) => h("input", { type: "checkbox", checked: checked ? true : null, disabled: disabled ? true : null, onchange });
  fill($("reports"),
    h("label", { class: "report-switch" }, box(!prefs.reportsAllOff, false, (e) => setReportsOn(["all"], e.target.checked)), ` ${t("Show reports")}`),
    h("table", { class: "report-switches" }, REPORT_PARTS.map(([kind, name]) => h("tr", {},
      h("td", {}, h("label", {}, box(!prefs.reportsOff[kind], prefs.reportsAllOff, (e) => setReportsOn([kind], e.target.checked)), ` ${t(name)}`)),
      h("td", {}, h("button", { disabled: latest[kind] ? null : true, title: latest[kind] ? t("Round {n}", { n: latest[kind].report.round }) : t("None yet"),
        onclick: () => showAgain(kind) }, t("show again")))))),
    h("p", { class: "small muted" }, t("A report shows in the task panel at the end of each part of the round.")));
}

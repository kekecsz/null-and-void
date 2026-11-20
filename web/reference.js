// The Reference panel (specification 7.4): the game's own tables (Grant funding track, Talent
// development track, journal tiers) with the researchers' chips on the tracks, and every way to gain
// or lose academic credit, by phase. All values come from the game's settings (view().reference),
// so a game with changed settings shows its own numbers.
"use strict";

const signedNumber = (n) => (n > 0 ? `+${n}` : String(n));

// The tracks: one column per position, the researchers' round tokens (like poker chips, overlapping)
// under their position; hovering a token names its researcher.
const token = (seat) => h("span", { class: "token", style: `background:${colourOf(seat)}`, title: nameOf(seat) }, (nameOf(seat) || "?").slice(0, 1).toUpperCase());
function chipsAt(position, key) {
  const here = view().researchers.filter((r) => r[key] === position);
  return here.length ? h("span", { class: "chip-stack" }, here.map((r) => token(r.seat))) : "";
}
function trackTable(positions, rows, key) {
  return h("table", { class: "track" },
    h("tr", {}, h("th", {}, t("Position")), positions.map((p) => h("th", {}, String(p)))),
    rows.map(([label, cell, title]) => h("tr", { title: title || null }, h("td", {}, label), positions.map((p) => h("td", {}, cell(p))))),
    h("tr", { class: "track-chips" }, h("td", {}, t("Researchers")), positions.map((p) => h("td", {}, chipsAt(p, key)))));
}

// What a Grant funding / Talent development position means, for the Tracks panel's hover text too.
function grantPositionText(position) {
  const g = view().reference.grant_track[position - 1];
  if (!g) return "";
  return g.expected_to_increase === null
    ? t("Grant position {n}: funding {f}, admin staff {a}; to keep it: {k} publication(s) a round (the top position).", { n: position, f: g.funding, a: g.admin, k: g.expected_to_maintain })
    : t("Grant position {n}: funding {f}, admin staff {a}; to keep it: {k} publication(s) a round, to move up: {u}.", { n: position, f: g.funding, a: g.admin, k: g.expected_to_maintain, u: g.expected_to_increase });
}
function talentPositionText(position) {
  const x = view().reference.talent[position];
  return x ? t("Talent position {n}: you may hire up to {cap} student(s); a student leaves on a roll below {leave}.", { n: position, cap: x.hire_cap, leave: x.leave_below }) : "";
}

function grantTrack(ref) {
  const positions = ref.grant_track.map((_, i) => i + 1);
  const g = (p) => ref.grant_track[p - 1];
  return trackTable(positions, [
    [t("Funding"), (p) => String(g(p).funding)],
    [t("Admin staff"), (p) => String(g(p).admin), t("Staff on Grants needed to keep the position")],
    [t("Publications to keep it"), (p) => String(g(p).expected_to_maintain), t("Publications needed in a round to keep the position")],
    [t("Publications to move up"), (p) => (g(p).expected_to_increase === null ? "–" : String(g(p).expected_to_increase)), t("Publications needed in a round to move up one position")],
  ], "grant_position");
}

function talentTrack(ref) {
  const positions = ref.talent.map((_, i) => i);
  return trackTable(positions, [
    [t("Students you may hire"), (p) => String(ref.talent[p].hire_cap), t("The most students you may hire in a round")],
    [t("A student leaves on a roll below"), (p) => String(ref.talent[p].leave_below), t("Student task check: each student rolls a die")],
  ], "talent_position");
}

function journalTiers(ref) {
  const yes = (b) => (b ? t("yes") : t("no"));
  const records = (x) => {
    const kinds = [x.min_observations ? t("{n} obs.", { n: x.min_observations }) : null, x.min_experiments ? t("{n} exp.", { n: x.min_experiments }) : null].filter(Boolean);
    return kinds.length ? `${x.min_records} (${kinds.join(", ")})` : String(x.min_records);
  };
  const rows = ref.journal_tiers.map((x, tier) => [String(tier), records(x), String(x.min_elements), String(x.rounds_in_processing),
    yes(x.peer_review), yes(x.methods_accepted), String(x.submission_fee), String(x.apc), signedNumber(ref.publication_rewards[tier])]);
  const tableBox = table([t("Tier"), t("Records"), t("Elements"), t("Rounds"), t("Peer review"), t("Methods"), t("Fee"), t("APC"), t("AC")], rows);
  tableBox.classList.add("tiers");
  return tableBox;
}

// Academic credit, by phase. Each line: [text, value, rulebook section (hover), normal game only].
function creditSections(ref) {
  const c = ref.credit;
  const crisisBase = c.crisis_pred_base_bonus ? t(" (inputs + {n} in the Crisis)", { n: c.crisis_pred_base_bonus }) : "";
  const tiers = ref.publication_rewards.map((n, tier) => `${tier}: ${signedNumber(n)}`).join(", ");
  return [
    ["Hiring", t("Hiring"), [
      [t("Firing a postdoc"), t("{n} each", { n: signedNumber(c.fired_postdoc_penalty) }), "Hiring and task allocation phase", false],
    ]],
    ["Experimentation", t("Experimentation"), [
      [t("Installing or upgrading a sensor"), t("{n} per level reached", { n: signedNumber(c.sensor_install_and_upgrade_AC_reward) }), "Experimentation and equipment phase", false],
      [t("Your method cited (experiment or sensor)"), signedNumber(c.experiment_method_citation_AC_reward), "Experimentation and equipment phase", false],
    ]],
    ["Observation and prediction", t("Predictions"), [
      [t("Right prediction"), t("inputs × outcomes{crisis}, ×2 if preregistered", { crisis: crisisBase }), "Scoring predictions", false],
      [t("Your theory cited in a right prediction"), c.crisis_pred_citation_reward_bonus
        ? t("{n} ({m} in the Crisis)", { n: signedNumber(c.citation_reward), m: signedNumber(c.citation_reward + c.crisis_pred_citation_reward_bonus) })
        : signedNumber(c.citation_reward), "Scoring predictions", false],
      [t("Wrong prediction"), t("hidden {a}, preregistered {b}, in the Crisis {c}", { a: signedNumber(c.failed_non_prereg_pred_ac), b: signedNumber(c.failed_prereg_pred_ac), c: signedNumber(c.failed_prereg_pred_ac_crisis) }), "Failed predictions", false],
      [t("Your theory fails in the Crisis"), signedNumber(c.crisis_failed_pred_citation_penalty), "Failed predictions", false],
      [t("Your theory retracted"), signedNumber(c.retraction_ac_penalty), "Retraction", false],
    ]],
    ["Publication", t("Publication (scored in Clean-up)"), [
      [t("Paper published, by tier"), tiers, "Publication scoring", true],
      [t("Open access"), signedNumber(c.OA_publication_AC_reward), "Publication scoring", true],
    ]],
    ["Clean-up", t("Clean-up"), [
      [t("Unused staff member"), t("{n} each", { n: signedNumber(c.unused_staff_penalty) }), "Clean-up phase", true],
      [t("Unpaid postdoc"), t("{n} each, and 1 step back on the Talent track", { n: signedNumber(c.unpaid_postdoc_penalty) }), "Clean-up phase", true],
    ]],
  ];
}

function creditTable(ref) {
  const v = view();
  const phases = roundPhases();
  const now = v.result ? null : (phases.find(([, steps]) => steps.includes(v.phase)) || [null])[0];
  const current = { "Probe time": "Experimentation", Development: null, "Talent development": "Clean-up" }[now] ?? now;
  const rows = [];
  for (const [phase, title, lines] of creditSections(ref)) {
    const shown = lines.filter((line) => !(line[3] && simplified()));
    if (!shown.length) continue;
    const cls = phase === current ? "credit-now" : null;
    rows.push(h("tr", { class: `credit-head${cls ? ` ${cls}` : ""}` }, h("th", { colspan: 2 }, title)));
    for (const [text, value, section] of shown) {
      rows.push(h("tr", { class: cls, title: t("Rulebook: {section}", { section }) }, h("td", {}, text), h("td", {}, value)));
    }
  }
  return h("div", {}, h("table", { class: "credit-table" }, rows),
    h("p", { class: "small muted" }, t("Academic credit never drops below 0.")));
}

function renderReference() {
  const v = view();
  const panel = $("reference-panel");
  const ref = v && v.reference;
  panel.style.display = ref ? "" : "none";
  if (!ref) return;
  const part = (title, body) => [h("h3", {}, title), body];
  fill($("reference"),
    part(t("Academic credit"), creditTable(ref)),
    simplified() ? null : part(t("Grant funding track"), grantTrack(ref)),
    simplified() || !ref.talent ? null : part(t("Talent development track"), talentTrack(ref)),
    simplified() ? null : part(t("Journal tiers"), journalTiers(ref)));
}

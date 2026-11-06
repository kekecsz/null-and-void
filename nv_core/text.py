"""Text rendering of a view (specification section 5.4): compact, stable, with short ids.

Ids: P1.. Probes, IP1.. input parameters, WO1.. world outcomes, T7 published theory, M3 published
method, D5 development stack (unpublished theory or method, also used for its manuscript),
O12 observation record, E9 experiment, Q4 prediction.
"""

from typing import Any

BLANK = "."


def _values(values: dict[str, str | None]) -> str:
    return ", ".join(f"{k}={v if v is not None else BLANK}" for k, v in values.items())


def idea_text(idea: dict[str, Any]) -> str:
    if idea["kind"] == "method":
        return f"method for {idea['parameter']}"
    return f"{_values(idea['inputs'])} -> {_values(idea['outcomes'])}"


def _table(rows: list[list[str]]) -> list[str]:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return ["  " + "  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip() for row in rows]


def render_text(view: dict[str, Any]) -> str:
    names = view["players"]
    lines: list[str] = []
    out = lines.append

    def name(seat: int | None) -> str:
        return "-" if seat is None else names[seat]

    # Header ---------------------------------------------------------------------------------
    period = "Crisis period" if view["period"] == "crisis" else "Calm period"
    out(f"{view['scenario']['title']} | world {view['scenario']['world']}")
    out(f"Round {view['round']} | {period} | {view['phase']}")
    if view["result"]:
        result = view["result"]
        out(f"GAME OVER ({result['ending'].replace('_', ' ')}): winners {', '.join(name(s) for s in result['winners']) or 'nobody'}")
    elif view["current"] is not None:
        out(f"Waiting for: {name(view['current'])} (to act)")
    elif view["waiting"]:
        out(f"Still deciding: {', '.join(name(s) for s in view['waiting'])}")
    order = " > ".join(name(s) for s in view["turn_order"])
    out(f"Turn order: {order} | Game Period Deck: {view['period_deck']} card(s)")
    if view["crisis"]:
        c = view["crisis"]
        out(
            f"CRISIS: round {c['rounds_in_crisis']} of {c['crisis_length']} | "
            f"unsuccessful predictions {c['unsuccessful']} of {c['crisis_condition']}"
        )
    elif view["warning_revealed"]:
        out("The Warning shot card has been revealed.")
    if view["alliances"]:
        out("Alliances: " + "; ".join(f"{name(a)} & {name(b)}" for a, b in view["alliances"]))
    if view["proposals"]:
        out("Alliance proposals: " + "; ".join(f"{name(a)} -> {name(b)}" for a, b in view["proposals"]))

    # World Grid ----------------------------------------------------------------------------
    out("")
    out("WORLD GRID")
    probes = view["probes"]
    header = ["", *[f"P{p['index'] + 1}{' (hot)' if p['hot_topic'] else ''}" for p in probes]]
    rows = [header]
    rows.append(
        [
            "Probe time",
            *[f"{name(p['probe_time'])}{' (sensor)' if p['probe_time_from_sensor'] else ''}" for p in probes],
        ]
    )
    for var in view["variables"]:
        label = f"{var['id']} {var['name']}"
        cells = []
        for p in probes:
            if var["kind"] == "input":
                tag = "*" if var["id"] in p["specialty"] else (f"L{p['sensors'][var['id']]}" if var["id"] in p["sensors"] else "")
                value = "" if p["readings"] is None else (p["readings"].get(var["id"]) or BLANK)
                cells.append(f"{value} {tag}".strip())
            else:
                value = "?" if p["outcomes"] is None else p["outcomes"].get(var["id"], "?")
                cells.append(value)
        rows.append([label, *cells])
    lines += _table(rows)
    out("  (* Specialty Input Parameter, L1-L3 sensor level, . blank, ? not revealed)")
    if view.get("probe_truth") and any(view["probe_truth"]):
        out("  True states: " + " | ".join(f"P{i + 1} {_values(t)}" for i, t in enumerate(view["probe_truth"]) if t))

    # Researchers ---------------------------------------------------------------------------
    out("")
    out("RESEARCHERS")
    rows = [["", "credit", "money", "grant", "talent", "postdocs", "students", "stacks", "fresh", "stale", "patents"]]
    for r in view["researchers"]:
        mark = " (first)" if r["seat"] == view["first_player"] else ""
        done = " (ready)" if r["committed"] else ""
        rows.append(
            [
                f"{r['name']}{mark}{done}",
                str(r["credit"]),
                str(r["money"]),
                str(r["grant_position"]),
                str(r["talent_position"]),
                str(r["postdocs"]),
                str(r["students"]),
                str(r["ideas"]),
                f"{r['fresh']['observations']}o+{r['fresh']['cards']}c",
                f"{r['stale']['observations']}o+{r['stale']['cards']}c",
                str(r["patents"]),
            ]
        )
    lines += _table(rows)
    for r in view["researchers"]:
        if r["staff"]:
            staff = ", ".join(
                f"{task} {c['postdocs']}p+{c['students']}s (used {c['used']})" for task, c in r["staff"].items()
            )
            out(f"  {r['name']} staff: {staff}")

    # Literature ----------------------------------------------------------------------------
    out("")
    out("PUBLISHED PAPERS" + ("" if view["published"] else ": none"))
    for p in view["published"]:
        letter = "T" if p["kind"] == "theory" else "M"
        flags = []
        if p["open_access"]:
            flags.append("open access")
        if p["fresh"]:
            flags.append("Fresh out of print")
        if p["sideways"]:
            flags.append("cited this round")
        counters = f" | Nobel {p['nobel']}/{view['nobel_condition']} | Retraction {p['retraction']}/{view['retraction_threshold']}" if p["kind"] == "theory" else ""
        patents = f" | patents: {', '.join(name(s) for s in p['patents'])}" if p["patents"] else ""
        out(f"  {letter}{p['id']} {name(p['author'])} tier {p['tier']}: {idea_text(p)}{counters}{patents}{' | ' + ', '.join(flags) if flags else ''}")

    # Submission Portal ---------------------------------------------------------------------
    if view["manuscripts"]:
        out("")
        out("SUBMISSION PORTAL")
        for area, title in (("review", "Awaiting peer review"), ("revise", "Revise area"), ("accept", "Accept area")):
            items = [m for m in view["manuscripts"] if m["area"] == area]
            for m in sorted(items, key=lambda m: (m["position"] or 0, m["id"])):
                where = f"#{m['position']} " if m["position"] else ""
                extra = f" | {m['votes']} vote(s)" if area == "review" else ""
                extra += f" | {m['tokens']} round(s) in processing" if area == "accept" else ""
                content = f" | {idea_text(m['content'])}" if m["content"] else ""
                spectator = f" | votes {m['vote_list']} | fabricated records {m['fabricated_records']}" if "vote_list" in m else ""
                out(f"  {title}: {where}D{m['id']} {name(m['author'])} tier {m['tier']} | {m['records']} record(s){' | open access' if m['open_access'] else ''}{extra}{content}{spectator}")
                for record in m.get("record_cards") or []:
                    out(f"      {record['kind']} record: {_values(record['cards'])}")

    # Predictions ---------------------------------------------------------------------------
    if view["predictions"] or view["hidden_predictions"]:
        out("")
        out("PREDICTIONS")
        for p in view["predictions"]:
            status = p["status"]
            if p["status"] == "scored":
                status = "success" if p["success"] else "failed"
            flags = " preregistered" if p["preregistered"] else ""
            if p.get("chosen_to_reveal") and p["status"] == "hidden" and not p["preregistered"]:
                flags += " (to reveal)"
            out(f"  Q{p['id']} {name(p['seat'])}: T{p['theory']} on P{p['probe'] + 1}{flags} | {status} | {_values(p['inputs'])} -> {_values(p['outcomes'])}")
        for seat, by_probe in view["hidden_predictions"].items():
            out(f"  {name(int(seat))} hidden: " + ", ".join(f"{n} on P{probe + 1}" for probe, n in by_probe.items()))
    if view["review_cards"]:
        out("Peer review cards: " + "; ".join(f"{name(int(s))} {cards}" for s, cards in view["review_cards"].items() if cards))

    # Labs ----------------------------------------------------------------------------------
    labs = [view["lab"]] if "lab" in view else view.get("labs", [])
    for lab in labs:
        lines += _lab_lines(lab, name)
    return "\n".join(lines)


def _lab_lines(lab: dict[str, Any], name) -> list[str]:
    lines = ["", f"LAB OF {name(lab['seat']).upper()} (hidden from others)"]
    if lab["ideas"]:
        lines.append("  Development stacks: " + "; ".join(f"D{i['id']} {idea_text(i)}" for i in lab["ideas"]))
    for area_name in ("fresh", "stale"):
        area = lab[area_name]
        for o in area["observations"]:
            lines.append(f"  {area_name.title()} O{o['id']} (P{o['probe'] + 1}, round {o['round']}): {_values(o['cards'])}")
        for e in area["experiments"]:
            lines.append(f"  {area_name.title()} E{e['id']}: {_values(e['cards'])}")
    pending = lab["pending"]
    if pending["development"]:
        lines.append("  Chosen this phase: " + "; ".join(f"{n + 1}. {idea_text(i)}" for n, i in enumerate(pending["development"])))
    if pending["allocation"]:
        a = pending["allocation"]
        staff = ", ".join(f"{t} {c['postdocs']}p+{c['students']}s" for t, c in a["allocation"].items()) or "none"
        lines.append(
            f"  Planned: hire {a['hire_postdocs']} postdoc(s), fire {a['fire_postdocs']}, hire {a['hire_students']} student(s); {staff}"
        )
    if lab["leaving_students"]:
        lines.append(f"  {lab['leaving_students']} student(s) must leave: choose from which tasks")
    if pending["votes"]:
        lines.append("  Votes: " + ", ".join(f"card {int(k) + 1}: {v}" for k, v in pending["votes"].items()))
    if pending["leave_alliances"]:
        lines.append("  Leaving alliances with: " + ", ".join(name(s) for s in pending["leave_alliances"]))
    if lab["experiments"]:
        lines.append(
            "  This round's experiments: "
            + "; ".join(f"E{e['id']} {_values(e['inputs'])} -> {_values(e['outcomes'])}" for e in lab["experiments"])
        )
    return lines

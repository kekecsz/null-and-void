"""The end-of-game debrief (specification section 10): what the hidden world was, and how the
published literature compared with the truth.

Built only from the final game state (with its hidden bookkeeping), the event log and the World
Table, so it can be rebuilt for any finished game. Plain data in, plain data out: the server sends
it to the browser, and ``csv_tables`` gives the tables for export.

The Fabrication, File drawer and Peer review panels hold totals only: nothing in them names a
researcher.
"""

from typing import Any

from nv_core.engine.context import Event
from nv_core.state import GameState, PaperLog, Prediction

TOP_THEORIES = 5  # theories followed in the "Over time" panel (highest Nobel Prize counters)


def _content(inputs: dict[str, str], outcomes: dict[str, str]) -> str:
    return ", ".join(f"{k}={v}" for k, v in inputs.items()) + " -> " + ", ".join(f"{k}={v}" for k, v in outcomes.items())


def _predictions(state: GameState) -> list[Prediction]:
    """Every prediction of the game: the logged ones and those of a round the game ended in."""
    current = []
    for p in state.predictions:
        p = p.model_copy(deep=True)
        if not p.readings and 0 <= p.probe < len(state.probes):
            p.readings = {v: c.state for v, c in state.probes[p.probe].readings.items()}
        current.append(p)
    return [*state.prediction_log, *current]


def _knew_it_would_fail(state: GameState, p: Prediction) -> bool:
    """An experiment of the predictor's own, run by then, matching the theory's inputs and the
    Probe's visible readings, showed an outcome that contradicts the theory (the simulator's
    ``experiment_knowledge_of_failure``)."""
    return any(
        e.round <= p.round
        and all(e.inputs.get(k) == v for k, v in p.inputs.items())
        and all(x is None or e.inputs.get(k) == x for k, x in p.readings.items())
        and any(e.outcomes.get(k) != v for k, v in p.outcomes.items())
        for e in state.researcher(p.seat).experiments
    )


def build_debrief(
    state: GameState,
    events: list[Event],
    low_chance: float,
    world_model: dict[str, Any] | None = None,
    notes: dict[int, str] | None = None,
) -> dict[str, Any]:
    """``low_chance``: the Luck panel's threshold (``debrief_low_chance``). ``world_model``: the
    world file's effects, interactions and row probabilities, when known. ``notes``: AI seats' notes."""
    world, names = state.world, list(state.players)
    truth: dict[tuple, tuple[float, float]] = {}

    def accuracy(inputs: dict[str, str], outcomes: dict[str, str]) -> tuple[float, float]:
        key = (tuple(sorted(inputs.items())), tuple(sorted(outcomes.items())))
        if key not in truth:
            truth[key] = world.theory_truth(inputs, outcomes)
        return truth[key]

    predictions = _predictions(state)
    scored = [p for p in predictions if p.status == "scored"]
    paper_log = list(state.paper_log)
    recorded = bool(paper_log) or not state.published  # games before the bookkeeping have none
    if not paper_log:  # older games: what is still published
        for paper in state.published:
            paper_log.append(PaperLog(paper=paper.id, manuscript=0, idea=paper.idea, author=paper.author, tier=paper.tier,
                                      open_access=paper.open_access, round=paper.round, records=0, fabricated=0, reviewed=False))
    papers = {entry.paper: entry for entry in paper_log}
    crisis_start = next((e.round for e in events if e.kind == "crisis"), None)

    # How it ended -------------------------------------------------------------------------------
    result = state.result
    ending: dict[str, Any] = {
        "ending": result.ending if result else "ended_early",
        "winners": [names[s] for s in result.winners] if result else [],
        "primary": [names[s] for s in result.primary] if result else [],
        "round": state.round,
        "ranking": sorted(
            ({"seat": r.seat, "name": r.name, "credit": r.credit} for r in state.researchers),
            key=lambda x: -x["credit"],
        ),
        "alliances": [[names[a], names[b]] for a, b in state.alliances],
        "nobel": None,
        "crisis": None,
    }
    if result and result.theory is not None:
        mine = [p for p in scored if p.cited == result.theory]
        streak = []
        for p in mine:  # the successes since its last failure
            streak = [*streak, p] if p.success else []
        entry = papers.get(result.theory)
        acc = accuracy(entry.idea.inputs, entry.idea.outcomes)[0] if entry else None
        ending["nobel"] = {
            "theory": result.theory,
            "content": _content(entry.idea.inputs, entry.idea.outcomes) if entry else "",
            "author": names[entry.author] if entry else "",
            "true_accuracy": acc,
            "streak": [{"round": p.round, "predictor": names[p.seat], "probe": p.probe + 1} for p in streak],
            # The chance of the streak: every success had the theory's true accuracy of happening.
            "chance": acc ** len(streak) if acc is not None else None,
        }
    if crisis_start is not None:
        unsuccessful = [
            {"round": p.round, "kind": "failed prediction", "probe": p.probe + 1, "predictor": names[p.seat], "theory": p.cited}
            for p in scored if p.round >= crisis_start and not p.success
        ]
        unsuccessful += [
            {"round": e.round, "kind": "no prediction", "probe": e.data["probe"] + 1 if "probe" in e.data else None,
             "predictor": None, "theory": None}
            for e in events if e.kind == "crisis_miss"
        ]
        unsuccessful.sort(key=lambda x: (x["round"], x["probe"] or 0))
        ending["crisis"] = {"started": crisis_start, "rounds_in_crisis": state.rounds_in_crisis,
                            "condition": state.settings.crisis_condition, "unsuccessful": unsuccessful}

    # The real world -----------------------------------------------------------------------------
    rows = []
    for i, row in enumerate(world.rows):
        item = {"inputs": dict(row.inputs), "outcomes": dict(row.outcomes)}
        if world_model and i < len(world_model.get("rows", [])):
            item["probabilities"] = world_model["rows"][i].get("probabilities")
        rows.append(item)
    base_rates = {
        v.id: {s: sum(r.outcomes[v.id] == s for r in world.rows) / len(world.rows) for s in v.states}
        for v in world.world_outcomes
    }
    real_world = {
        "variables": [{"id": v.id, "name": v.name, "states": list(v.states)} for v in world.variables],
        "input_ids": world.input_ids,
        "rows": rows,
        "base_rates": base_rates,
        "main_effects": (world_model or {}).get("main_effects"),
        "interactions": (world_model or {}).get("interactions"),
        "nobel_grade": ((world_model or {}).get("screening") or {}).get("nobel_grade"),
    }

    # The literature vs. the truth ---------------------------------------------------------------
    literature = []
    for entry in paper_log:
        if entry.idea.kind != "theory":
            continue
        cited = [p for p in scored if p.cited == entry.paper]
        acc, coverage = accuracy(entry.idea.inputs, entry.idea.outcomes)
        successes = sum(1 for p in cited if p.success)
        literature.append({
            "theory": entry.paper, "author": names[entry.author], "tier": entry.tier, "round": entry.round,
            "content": _content(entry.idea.inputs, entry.idea.outcomes),
            "successes": successes, "failures": len(cited) - successes,
            "observed_rate": successes / len(cited) if cited else None,
            "true_accuracy": acc, "coverage": coverage,
            "retracted": entry.retracted_round,
        })
    methods = sum(1 for entry in paper_log if entry.idea.kind == "method")

    # Luck -------------------------------------------------------------------------------------------
    lucky, unlucky = [], []
    for p in scored:
        acc = accuracy(p.inputs, p.outcomes)[0]
        item = {"round": p.round, "predictor": names[p.seat], "theory": p.cited, "probe": p.probe + 1,
                "content": _content(p.inputs, p.outcomes), "true_accuracy": acc}
        if p.success and acc < low_chance:
            lucky.append(item)
        elif not p.success and acc > 1 - low_chance:
            unlucky.append(item)
    luck = {"threshold": low_chance, "lucky_successes": lucky, "unlucky_failures": unlucky}

    # Sabotage ---------------------------------------------------------------------------------------
    nobel_before = {log.round: log.nobel for log in state.round_log}
    sabotage = []
    for p in scored:
        if p.success or not p.revealed or not _knew_it_would_fail(state, p):
            continue
        entry = papers.get(p.cited)
        sabotage.append({
            "round": p.round, "predictor": names[p.seat], "theory": p.cited,
            "author": names[entry.author] if entry else None,
            "nobel_at_round_start": nobel_before.get(p.round - 1, {}).get(p.cited),
            "own_theory": bool(entry and entry.author == p.seat),
        })

    # Fabrication (totals only) ---------------------------------------------------------------------
    in_portal = sum(r.fabricated for m in state.manuscripts for r in m.records)
    relying = [entry for entry in paper_log if entry.fabricated]
    fabrication = {
        "fabricated_records": sum(entry.fabricated for entry in paper_log) + in_portal,
        "published_papers_relying_on_them": len(relying),
        "true_accuracy_of_those_theories": sorted(
            accuracy(e.idea.inputs, e.idea.outcomes)[0] for e in relying if e.idea.kind == "theory"
        ),
        "recorded": recorded,
    }

    # File drawer (totals only) ---------------------------------------------------------------------
    drawer = [p for p in predictions if p.status == "discarded" and not p.revealed]
    shown = [p for p in predictions if p.status == "scored"]

    def rate(group: list[Prediction]) -> float | None:
        known = [p for p in group if p.success is not None]
        return sum(1 for p in known if p.success) / len(known) if known else None

    file_drawer = {"never_revealed": len(drawer), "never_revealed_success_rate": rate(drawer),
                   "revealed": len(shown), "revealed_success_rate": rate(shown)}

    # Peer review (totals only) ---------------------------------------------------------------------
    by_tier: dict[int, dict[str, int]] = {}
    for log in state.review_log:
        tier = by_tier.setdefault(log.tier, {"decisions": 0, "accepted": 0})
        tier["decisions"] += 1
        tier["accepted"] += log.accepted
    peer_review = {
        "by_tier": [{"tier": t, **c, "acceptance_rate": c["accepted"] / c["decisions"]} for t, c in sorted(by_tier.items())],
        "accepted_with_fabricated_records": sum(1 for log in state.review_log if log.accepted and log.fabricated),
        "recorded": recorded,
    }

    # Over time ---------------------------------------------------------------------------------------
    logs = list(state.round_log)
    points = [(log.round, list(log.credit), dict(log.nobel)) for log in logs]
    if not points or points[-1][0] != state.round:  # the round the game ended in
        points.append((state.round, [r.credit for r in state.researchers],
                       {p.id: p.nobel for p in state.published if p.kind == "theory"}))
    best: dict[int, int] = {}
    for _, _, nobel in points:
        for theory, value in nobel.items():
            best[theory] = max(best.get(theory, 0), value)
    leading = [t for t, v in sorted(best.items(), key=lambda x: (-x[1], x[0])) if v > 0][:TOP_THEORIES]
    over_time = {
        "rounds": [r for r, _, _ in points],
        "credit": [{"name": names[s], "values": [c[s] for _, c, _ in points]} for s in range(state.n_players)],
        "nobel": [{"theory": t, "values": [n.get(t) for _, _, n in points]} for t in leading],
        "nobel_condition": state.settings.nobel_condition,
    }

    return {
        "players": names,
        "scenario": {"title": world.title, "world": world.world_id},
        "ending": ending,
        "real_world": real_world,
        "literature": literature,
        "methods_published": methods,
        "luck": luck,
        "sabotage": sabotage,
        "fabrication": fabrication,
        "file_drawer": file_drawer,
        "peer_review": peer_review,
        "over_time": over_time,
        "ai_notes": {names[s]: text for s, text in (notes or {}).items() if text},
        "bookkeeping_recorded": recorded,
    }


def csv_tables(debrief: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The debrief's tables for CSV export (the totals-only panels stay totals)."""
    over_time = debrief["over_time"]
    credit_rows = [
        {"round": r, **{c["name"]: c["values"][i] for c in over_time["credit"]}}
        for i, r in enumerate(over_time["rounds"])
    ]
    luck = [{"kind": "lucky success", **x} for x in debrief["luck"]["lucky_successes"]]
    luck += [{"kind": "unlucky failure", **x} for x in debrief["luck"]["unlucky_failures"]]
    world = debrief["real_world"]
    world_rows = [
        {**row["inputs"], **row["outcomes"], **({"probabilities": row["probabilities"]} if "probabilities" in row else {})}
        for row in world["rows"]
    ]
    totals = [
        {"panel": "fabrication", **{k: v for k, v in debrief["fabrication"].items() if not isinstance(v, list)}},
        {"panel": "file drawer", **debrief["file_drawer"]},
    ]
    totals += [{"panel": "peer review", **row} for row in debrief["peer_review"]["by_tier"]]
    return {
        "literature": debrief["literature"],
        "credit_by_round": credit_rows,
        "luck": luck,
        "sabotage": debrief["sabotage"],
        "world_table": world_rows,
        "totals": totals,
    }


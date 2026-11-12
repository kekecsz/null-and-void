"""Views (specification section 5.4): what a player, or a spectator, may see of the game.

A view is plain JSON-ready data. ``player_view`` holds everything public plus that player's own
hidden material; ``spectator_view`` holds everything. ``nv_core.text.render_text`` renders either.
"""

from typing import Any

from nv_core.engine import SIMULTANEOUS
from nv_core.engine.context import Event
from nv_core.state import Card, GameState, Idea, Manuscript, Paper, Phase, Prediction, RecordArea, Researcher

# Probes are dealt at the start of the Observation and prediction phase.
_DEALT = {Phase.PREDICTION, Phase.REVEAL, Phase.SCORING_ORDER, Phase.DEVELOPMENT, Phase.SUBMISSION, Phase.PEER_REVIEW}


def _idea(idea: Idea) -> dict[str, Any]:
    return {"id": idea.id, "kind": idea.kind, "inputs": idea.inputs, "outcomes": idea.outcomes, "parameter": idea.parameter}


def _cards(cards: list[Card]) -> dict[str, str | None]:
    return {c.var: c.state for c in cards}


def _area(area: RecordArea) -> dict[str, Any]:
    experiments: dict[int, dict[str, str | None]] = {}
    for item in area.cards:
        experiments.setdefault(item.experiment, {})[item.card.var] = item.card.state
    return {
        "observations": [
            {"id": o.id, "probe": o.probe, "round": o.round, "cards": _cards(o.cards)} for o in area.observations
        ],
        "experiments": [{"id": e, "cards": cards} for e, cards in sorted(experiments.items())],
    }


def _paper(state: GameState, paper: Paper) -> dict[str, Any]:
    return {
        **_idea(paper.idea),
        "id": paper.id,
        "author": paper.author,
        "tier": paper.tier,
        "open_access": paper.open_access,
        "round": paper.round,
        "nobel": paper.nobel,
        "retraction": paper.retraction,
        "fresh": paper.fresh,
        "patents": list(paper.patents),
    }


def _lab_capacity_cost(state: GameState, r: Researcher) -> int | None:
    """The cost of the next step of lab capacity, None at the maximum (Experimentation and equipment phase)."""
    s = state.settings
    if r.lab_capacity is None or s.starting_lab_capacity_advanced is None:
        return None
    costs = s.lab_capacity_costs()
    step = r.lab_capacity - s.starting_lab_capacity_advanced
    return costs[step] if 0 <= step < len(costs) else None


def _manuscript(m: Manuscript, show_content: bool, show_records: bool, spectator: bool) -> dict[str, Any]:
    """``show_records``: the author, peer reviewers allocated to it (Peer review: they "peek at
    the manuscript") and spectators see the supporting record cards too."""
    data: dict[str, Any] = {
        "id": m.id,
        "author": m.author,
        "tier": m.tier,
        "area": m.area,
        "position": m.position,
        "tokens": m.tokens,
        "votes": len(m.votes),
        "records": len(m.records),
        "open_access": m.open_access,
        "content": _idea(m.idea) if show_content else None,
        "record_cards": (
            [{"kind": r.kind, "cards": _cards(r.cards)} for r in m.records] if show_records else None
        ),
    }
    if spectator:
        data["vote_list"] = list(m.votes)
        data["fabricated_records"] = sum(r.fabricated for r in m.records)
    return data


def _prediction(p: Prediction, full: bool) -> dict[str, Any]:
    data = {
        "id": p.id,
        "seat": p.seat,
        "probe": p.probe,
        "theory": p.cited if p.cited is not None else p.theory,
        "inputs": p.inputs,
        "outcomes": p.outcomes,
        "preregistered": p.preregistered,
        "status": p.status,
        "success": p.success,
    }
    if full:
        data["chosen_to_reveal"] = p.revealed
    return data


def _public_prediction(state: GameState, p: Prediction) -> bool:
    """Preregistered predictions are shown once the lab shields are removed; others once revealed."""
    if p.status in ("revealed", "pruned", "scored"):
        return True
    return p.preregistered and state.phase not in (Phase.PREDICTION,)


def _view(state: GameState, seat: int | None) -> dict[str, Any]:
    spectator = seat is None
    dealt = state.phase in _DEALT
    probes = []
    for p in state.probes:
        probes.append(
            {
                "index": p.index,
                "specialty": p.specialty,
                "sensors": p.sensors,
                "probe_time": p.probe_time,
                "probe_time_from_sensor": p.probe_time_from_sensor,
                "hot_topic": p.index == state.hot_topic,
                "readings": {v: c.state for v, c in p.readings.items()} if dealt else None,
                "outcomes": (
                    {v: c.state for v, c in p.outcomes.items()} if dealt and (p.outcomes_revealed or spectator) else None
                ),
            }
        )
    reviewing = set()
    if seat is not None and state.phase == Phase.PEER_REVIEW:
        reviewing = {c for c in state.review_cards.get(seat, []) if c}
    researchers = []
    for r in state.researchers:
        researchers.append(
            {
                "seat": r.seat,
                "name": r.name,
                "credit": r.credit,
                "money": r.money,
                "grant_position": r.grant_position,
                "talent_position": r.talent_position,
                "lab_capacity": r.lab_capacity,
                "lab_capacity_cost": _lab_capacity_cost(state, r),
                "postdocs": r.postdocs,
                "students": r.students,
                "staff": {
                    t.value: {"postdocs": c.postdocs, "students": c.students, "used": r.used.get(t, 0)}
                    for t, c in r.staff.items()
                },
                "ideas": len(r.ideas),
                "fresh": {"observations": len(r.fresh.observations), "cards": len(r.fresh.cards)},
                "stale": {"observations": len(r.stale.observations), "cards": len(r.stale.cards)},
                "patents": sum(p.patents.count(r.seat) for p in state.published),
                "committed": state.phase in SIMULTANEOUS and r.seat not in state.waiting,
            }
        )
    predictions = [
        _prediction(p, spectator or p.seat == seat)
        for p in state.predictions
        if spectator or p.seat == seat or _public_prediction(state, p)
    ]
    hidden_counts: dict[int, dict[int, int]] = {}
    if state.phase in (Phase.REVEAL, Phase.SCORING_ORDER):
        for p in state.predictions:
            if p.status == "hidden" and not p.preregistered and p.seat != seat:
                hidden_counts.setdefault(p.seat, {}).setdefault(p.probe, 0)
                hidden_counts[p.seat][p.probe] += 1
    view: dict[str, Any] = {
        "seat": seat,
        "players": list(state.players),
        "scenario": {"id": state.world.scenario_id, "title": state.world.title, "world": state.world.world_id},
        "round": state.round,
        "period": state.period,
        "phase": state.phase.value,
        "simultaneous": state.phase in SIMULTANEOUS,
        "waiting": list(state.waiting),
        "current": state.current,
        "first_player": state.first_player,
        "turn_order": state.turn_order(),
        "period_deck": len(state.period_deck),
        "warning_revealed": state.warning_revealed,
        "crisis": (
            {
                "rounds_in_crisis": state.rounds_in_crisis,
                "crisis_length": state.settings.crisis_length,
                "unsuccessful": state.unsuccessful_predictions,
                "crisis_condition": state.settings.crisis_condition,
            }
            if state.period == "crisis"
            else None
        ),
        "nobel_condition": state.settings.nobel_condition,
        "retraction_threshold": state.settings.retraction_threshold,
        "variables": [
            {"id": v.id, "name": v.name, "states": v.states, "kind": "input" if v in state.world.input_parameters else "outcome"}
            for v in state.world.variables
        ],
        "probes": probes,
        "researchers": researchers,
        "alliances": [list(pair) for pair in state.alliances],
        "proposals": [list(pair) for pair in state.proposals],
        "published": [_paper(state, p) for p in state.published],
        "manuscripts": [
            _manuscript(
                m,
                show_content=spectator or m.open_access or m.author == seat or m.position in reviewing,
                show_records=spectator or m.author == seat or m.position in reviewing,
                spectator=spectator,
            )
            for m in state.manuscripts
        ],
        "predictions": predictions,
        "hidden_predictions": hidden_counts,
        "review_cards": {str(s): cards for s, cards in state.review_cards.items()},
        "result": state.result.model_dump() if state.result else None,
        "prediction_report": state.prediction_report,
    }
    if seat is not None:
        view["lab"] = _lab(state, seat)
    else:
        view["labs"] = [_lab(state, s, all_rounds=True) for s in range(state.n_players)]
        view["world_table"] = [row.model_dump() for row in state.world.rows]
        view["probe_truth"] = [
            {**state.world.rows[state.stack_rows[p.stack]].inputs, **{v: c.state for v, c in p.outcomes.items()}}
            if dealt and p.stack is not None
            else None
            for p in state.probes
        ]
        view["prediction_log"] = [_prediction(p, True) for p in state.prediction_log]
    return view


def _lab(state: GameState, seat: int, all_rounds: bool = False) -> dict[str, Any]:
    r = state.researcher(seat)
    pending = state.pending[seat]
    return {
        "seat": seat,
        "ideas": [_idea(i) for i in r.ideas],
        "fresh": _area(r.fresh),
        "stale": _area(r.stale),
        "leaving_students": r.leaving_students,
        "pending": {
            "allocation": pending.allocation,
            "leaving_students": pending.leaving_students,
            "leave_alliances": pending.leave_alliances,
            "development": [_idea(i) for i in pending.development],
            "votes": {str(k): v for k, v in pending.votes.items()},
            "scoring_order": pending.scoring_order,
        },
        "experiments": [e.model_dump() for e in r.experiments if all_rounds or e.round == state.round],
    }


def player_view(state: GameState, seat: int) -> dict[str, Any]:
    return _view(state, seat)


def spectator_view(state: GameState) -> dict[str, Any]:
    return _view(state, None)


def visible_events(events: list[Event], seat: int | None) -> list[Event]:
    """The events a player (or, with ``seat`` None, a spectator) may see."""
    if seat is None:
        return list(events)
    return [e for e in events if e.visible_to is None or seat in e.visible_to]

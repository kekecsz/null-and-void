"""Playing one game with automated players and collecting the simulator's rows (specification
section 9). Seats are numbered from 1 in the CSV rows."""

import traceback
from dataclasses import dataclass, field
from typing import Any

from nv_core.engine import IllegalAction, apply, legal_actions, new_game
from nv_core.record import GameRecord
from nv_core.settings import Settings
from nv_core.state import GameState, Prediction
from nv_core.views import player_view
from nv_core.world_data import WorldData
from nv_sim import invariants
from nv_sim.bots import BOTS

MAX_REFUSALS = 20  # a bot whose choices are refused this often in a row commits or passes instead


def make_players(seat_types: list[str], seed: int) -> list:
    players = []
    for seat, kind in enumerate(seat_types):
        if kind not in BOTS:
            raise ValueError(f"unknown seat type {kind!r} (available: {', '.join(BOTS)}; AI seats come in milestone 4)")
        players.append(BOTS[kind](f"{seed}/seat{seat}"))
    return players


def theory_truth(world: WorldData, inputs: dict[str, str], outcomes: dict[str, str]) -> tuple[float, float]:
    """True (accuracy, coverage) of a theory in the World Table, as in specification 4.3."""
    covered = [row for row in world.rows if all(row.inputs[k] == v for k, v in inputs.items())]
    if not covered:
        return 0.0, 0.0
    hits = sum(all(row.outcomes[k] == v for k, v in outcomes.items()) for row in covered)
    return hits / len(covered), len(covered) / len(world.rows)


def _text(values: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in values.items())


@dataclass
class GameReport:
    game: dict[str, Any]
    rounds: list[dict[str, Any]] = field(default_factory=list)
    theories: list[dict[str, Any]] = field(default_factory=list)
    predictions: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    record: GameRecord | None = None


class _Collector:
    def __init__(self, state: GameState):
        self.world = state.world
        self.n = state.n_players
        self.round = state.round
        self.money_start = [r.money for r in state.researchers]
        self.staff = [0] * self.n
        self.published = 0
        self.rounds: list[dict[str, Any]] = []
        self.papers: dict[int, dict[str, Any]] = {}
        self.max_nobel: dict[int, int] = {}
        self.predictions: list[dict[str, Any]] = []
        self.logged = 0
        self.crisis_start: int | None = None
        self.input_builds = {p: 1 for p in state.input_decks}

    def events(self, state: GameState, events) -> None:
        for e in events:
            if e.kind == "allocation":
                data = e.data.get("allocation") or {}
                self.staff[e.data["seat"]] = sum(
                    c["postdocs"] + c["students"] for c in data.get("allocation", {}).values()
                )
            elif e.kind == "published":
                paper = state.paper(e.data["paper"])
                self.published += 1
                if paper.kind == "theory":
                    accuracy, coverage = theory_truth(self.world, paper.idea.inputs, paper.idea.outcomes)
                    self.papers[paper.id] = {
                        "theory": paper.id,
                        "author": paper.author + 1,
                        "tier": paper.tier,
                        "round_published": e.round,
                        "open_access": paper.open_access,
                        "inputs": _text(paper.idea.inputs),
                        "outcomes": _text(paper.idea.outcomes),
                        "n_inputs": len(paper.idea.inputs),
                        "n_outcomes": len(paper.idea.outcomes),
                        "true_accuracy": accuracy,
                        "coverage": coverage,
                        "retracted": False,
                    }
            elif e.kind == "retraction":
                if e.data["theory"] in self.papers:
                    self.papers[e.data["theory"]]["retracted"] = True
            elif e.kind == "crisis" and self.crisis_start is None:
                self.crisis_start = e.round
            elif e.kind == "deck" and "Input Parameter Deck" in e.text and "rebuilt" in e.text:
                parameter = e.text.split()[3]
                self.input_builds[parameter] += 1

    def after(self, state: GameState) -> None:
        for paper in state.published:
            if paper.kind == "theory":
                self.max_nobel[paper.id] = max(self.max_nobel.get(paper.id, 0), paper.nobel)
        while self.logged < len(state.prediction_log):
            self._prediction(state, state.prediction_log[self.logged])
            self.logged += 1
        if state.round != self.round or state.result:
            self._close_round(state)

    def _close_round(self, state: GameState) -> None:
        row: dict[str, Any] = {"round": self.round}
        made = [p for p in self.predictions if p["round"] == self.round]
        for seat in range(self.n):
            row[f"staff_{seat + 1}"] = self.staff[seat]
            row[f"money_{seat + 1}"] = self.money_start[seat]
            row[f"credit_{seat + 1}"] = state.researchers[seat].credit
        row["papers_published"] = self.published
        row["predictions_made"] = len(made)
        row["predictions_revealed"] = sum(p["revealed"] for p in made)
        self.rounds.append(row)
        self.round = state.round
        self.money_start = [r.money for r in state.researchers]
        self.staff = [0] * self.n
        self.published = 0

    def _prediction(self, state: GameState, p: Prediction) -> None:
        readings = state.probes[p.probe].readings
        knowledge = any(
            e.round <= p.round
            and all(e.inputs[k] == v for k, v in p.inputs.items())
            and all(c.state is None or e.inputs[k] == c.state for k, c in readings.items())
            and any(e.outcomes[k] != v for k, v in p.outcomes.items())
            for e in state.researcher(p.seat).experiments
        )
        theory = p.cited if p.cited is not None else p.theory
        accuracy, _ = theory_truth(self.world, p.inputs, p.outcomes)
        self.predictions.append(
            {
                "round": p.round,
                "seat": p.seat + 1,
                "theory": theory,
                "probe": p.probe + 1,
                "preregistered": p.preregistered,
                "revealed": p.revealed,
                "status": p.status,
                "success": p.success,
                "theory_true_accuracy": accuracy,
                # An experiment of the predictor's own, matching the theory's inputs and the
                # Probe's visible readings, showed an outcome that contradicts the theory.
                "experiment_knowledge_of_failure": knowledge,
            }
        )

    def theories(self, state: GameState) -> list[dict[str, Any]]:
        rows = []
        scored = [p for p in self.predictions if p["status"] == "scored"]
        for paper_id, row in self.papers.items():
            mine = [p for p in scored if p["theory"] == paper_id]
            rows.append(
                {
                    **row,
                    "successes": sum(1 for p in mine if p["success"]),
                    "failures": sum(1 for p in mine if not p["success"]),
                    "highest_nobel": self.max_nobel.get(paper_id, 0),
                }
            )
        return rows


def play_game(
    world: WorldData,
    settings: Settings,
    seed: int,
    seat_types: list[str],
    max_actions: int = 20000,
    keep_record: bool = False,
    check_invariants: bool = True,
) -> GameReport:
    players = make_players(seat_types, seed)
    names = [f"{kind}{seat + 1}" for seat, kind in enumerate(seat_types)]
    state = new_game(world, settings, seed, names)
    collector = _Collector(state)
    actions: list = []
    errors: list[str] = []
    refused = 0
    try:
        while state.result is None:
            if len(actions) >= max_actions:
                errors.append(f"stalled: no ending after {max_actions} actions")
                break
            seat = state.current if state.current is not None else state.waiting[0]
            player = players[seat]
            options = legal_actions(state, seat)
            view = (
                player_view(state, seat)
                if player.needs_view
                else {"round": state.round, "phase": state.phase.value, "seat": seat}
            )
            result = None
            for _ in range(MAX_REFUSALS):
                action = player.choose(view, options)
                try:
                    result = apply(state, action)
                    break
                except IllegalAction:
                    refused += 1
            if result is None:  # fall back to committing or passing
                for option in options:
                    if option.type in ("commit", "pass"):
                        action = option.actions[0]
                        result = apply(state, action)
                        break
            if result is None:
                errors.append(f"round {state.round}, {state.phase.value}: seat {seat + 1} found no legal action")
                break
            state, events = result
            actions.append(action)
            collector.events(state, events)
            collector.after(state)
            if check_invariants:
                broken = invariants.check(state, collector.input_builds)
                if broken:
                    errors += [f"round {state.round}, {state.phase.value}, action {len(actions)}: {b}" for b in broken]
                    break
    except Exception:  # a crash is a bug: record it and go on with the next game
        errors.append(traceback.format_exc(limit=8))
    if state.predictions:  # a game can end during scoring, before predictions are logged
        for p in state.predictions:
            collector._prediction(state, p)
    if collector.round == state.round and (not collector.rounds or collector.rounds[-1]["round"] != state.round):
        collector._close_round(state)

    result = state.result
    game: dict[str, Any] = {
        "seed": seed,
        "world": world.world_id,
        "players": len(seat_types),
        "seats": ";".join(seat_types),
        "rounds": state.round,
        "crisis_start_round": collector.crisis_start,
        "ending": result.ending if result else "error",
        "winners": ";".join(str(s + 1) for s in result.winners) if result else "",
        "primary_winners": ";".join(str(s + 1) for s in result.primary) if result else "",
        "nobel_theory": result.theory if result else None,
        "actions": len(actions),
        "refused_actions": refused,
        "ai_cost": 0.0,
        "error": " | ".join(errors).replace("\n", " ") if errors else "",
    }
    for seat, r in enumerate(state.researchers):
        game[f"credit_{seat + 1}"] = r.credit
    record = (
        GameRecord(world=world, settings=settings, seed=seed, players=names, actions=actions) if keep_record else None
    )
    return GameReport(
        game=game,
        rounds=collector.rounds,
        theories=collector.theories(state),
        predictions=collector.predictions,
        errors=errors,
        record=record,
    )

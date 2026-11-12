"""Rules engine: Observation and prediction phase (predictions, preregistration,
reveal, scoring), Nobel Prize, Retraction and Crisis.

The tiny world (tests/core/engine_helpers.py) has WO1 = up exactly when IP1 = a. Theories on
IP3 alone are used where a theory must fit every Probe: IP3 is blank on Probes without an IP3
sensor or Specialty, and a blank never mismatches.
"""

import pytest

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply
from nv_core.state import Phase
from tests.core.engine_helpers import do, game, publish, set_readings, settings, to_phase

S = settings()
# A development staff member makes the game stop at the Development phase, right after scoring.
DATA = {0: {"data_collection": 2, "development": 1}, 1: {"data_collection": 2, "development": 1}}
ONE = {s: {"data_collection": 1, "development": 1} for s in range(3)}


def _prediction_phase(n=2, period="calm", allocations=None, **theories):
    """Reach the prediction step with theories published by the given authors."""
    state = game(n)
    papers = {}
    for key, (author, inputs, outcomes) in theories.items():
        papers[key] = publish(state, author, inputs=inputs, outcomes=outcomes)
    state.period = period
    state = to_phase(state, Phase.PREDICTION, allocations or DATA)
    for p in state.probes:
        set_readings(state, p.index, {"IP1": "a", "IP3": "p"}, outcome="up")
    return state, {k: v.id for k, v in papers.items()}


def _credits(state):
    return [r.credit for r in state.researchers]


def test_prediction_must_not_mismatch_visible_readings():
    state, t = _prediction_phase(T=(1, {"IP1": "a"}, {"WO1": "up"}))
    set_readings(state, 0, {"IP1": "b"})
    with pytest.raises(IllegalAction, match="mismatches"):
        apply(state, a.MakePrediction(seat=0, theory=t["T"], probe=0))
    apply(state, a.MakePrediction(seat=0, theory=t["T"], probe=1))


def test_fresh_out_of_print_theory_only_for_its_author():
    state, _ = _prediction_phase(T=(1, {"IP3": "p"}, {"WO1": "up"}))
    fresh = publish(state, 1, inputs={"IP3": "q"}, outcomes={"WO1": "up"}, fresh=True)
    set_readings(state, 0, {"IP3": None})
    with pytest.raises(IllegalAction, match="Fresh out of print"):
        apply(state, a.MakePrediction(seat=0, theory=fresh.id, probe=0))
    apply(state, a.MakePrediction(seat=1, theory=fresh.id, probe=0))


def test_preregistration_limited_by_data_collection_staff():
    state, t = _prediction_phase(
        T=(1, {"IP3": "p"}, {"WO1": "up"}), U=(1, {"IP1": "a"}, {"WO1": "up"}), V=(1, {"IP1": "a", "IP3": "p"}, {"WO1": "up"})
    )
    state = do(state, *(a.MakePrediction(seat=0, theory=t[k], probe=0, preregister=True) for k in ("T", "U")))
    with pytest.raises(IllegalAction, match="at most 2"):
        apply(state, a.MakePrediction(seat=0, theory=t["V"], probe=1, preregister=True))


def test_one_theory_once_per_probe():
    """Formulating predictions and preregistration: one theory once by the same researcher on
    the same Probe; on another Probe it can be preregistered again."""
    state, t = _prediction_phase(T=(1, {"IP3": "p"}, {"WO1": "up"}))
    state = do(state, a.MakePrediction(seat=0, theory=t["T"], probe=0, preregister=True))
    with pytest.raises(IllegalAction, match="already predict"):
        apply(state, a.MakePrediction(seat=0, theory=t["T"], probe=0))
    apply(state, a.MakePrediction(seat=0, theory=t["T"], probe=1, preregister=True))


def _finish_predictions(state):
    """Commit everyone's predictions and reveals; return the state and the events."""
    events = []
    for _ in range(10):
        if state.phase not in (Phase.PREDICTION, Phase.REVEAL, Phase.SCORING_ORDER) or not state.waiting:
            break
        state, new = apply(state, a.CommitPhase(seat=state.waiting[0]))
        events += new
    return state, events


def test_successful_preregistered_prediction_scoring():
    """Base = inputs in the theory, x outcomes shown, x2 preregistered; citation reward,
    patent and Nobel counter for the cited theory."""
    state, t = _prediction_phase(T=(1, {"IP3": "p"}, {"WO1": "up"}))
    turn = state.turn_order()
    before = _credits(state)
    state = do(state, a.MakePrediction(seat=0, theory=t["T"], probe=0, preregister=True))
    state, _ = _finish_predictions(state)
    paper = state.paper(t["T"])
    assert paper.nobel == 1 and paper.retraction == 0 and paper.patents == [0]
    assert state.researcher(0).credit - before[0] == 1 * 1 * 2
    assert state.researcher(1).credit - before[1] == S.citation_reward
    assert turn  # turn order does not matter with one prediction


def test_revealed_failed_prediction_resets_nobel_and_counts_retraction():
    state, t = _prediction_phase(T=(1, {"IP3": "p"}, {"WO1": "down"}))
    state.paper(t["T"]).nobel = 2
    before = _credits(state)
    state = do(state, a.MakePrediction(seat=0, theory=t["T"], probe=0), a.CommitPhase(seat=0), a.CommitPhase(seat=1))
    assert state.phase == Phase.REVEAL and state.waiting == [0]
    state = do(state, a.RevealPrediction(seat=0, prediction=state.predictions[0].id), a.CommitPhase(seat=0))
    paper = state.paper(t["T"])
    assert paper.nobel == 0 and paper.retraction == 1
    assert state.researcher(0).credit - before[0] == S.failed_non_prereg_pred_ac
    assert state.researcher(1).credit == before[1]  # no citation reward for a failed prediction


def test_retraction_returns_the_theory_and_penalises_its_author():
    state, t = _prediction_phase(T=(1, {"IP3": "p"}, {"WO1": "down"}))
    state.paper(t["T"]).retraction = S.retraction_threshold - 1
    before = _credits(state)
    state = do(state, a.MakePrediction(seat=0, theory=t["T"], probe=0, preregister=True))
    state, _ = _finish_predictions(state)
    assert all(p.id != t["T"] for p in state.published)
    assert any(i.inputs == {"IP3": "p"} and i.outcomes == {"WO1": "down"} for i in state.researcher(1).ideas)
    assert state.researcher(1).credit == max(0, before[1] + S.retraction_ac_penalty)


def test_two_researchers_on_one_theory_are_both_scored():
    """Outcome and Prediction Reveal: every revealed prediction is scored, also when another
    researcher used the same theory."""
    state, t = _prediction_phase(n=3, allocations=ONE, T=(2, {"IP3": "p"}, {"WO1": "down"}))
    order = state.turn_order()
    first, second = order[0], order[1]
    state = do(
        state,
        a.MakePrediction(seat=first, theory=t["T"], probe=0, preregister=True),
        a.MakePrediction(seat=second, theory=t["T"], probe=1, preregister=True),
    )
    state, events = _finish_predictions(state)
    statuses = {p.seat: p.status for p in state.prediction_log}
    assert statuses[first] == "scored" and statuses[second] == "scored"


def test_identical_theories_prefer_own():
    state, t = _prediction_phase(A=(0, {"IP3": "p"}, {"WO1": "up"}), B=(1, {"IP3": "p"}, {"WO1": "up"}))
    state = do(state, a.MakePrediction(seat=1, theory=t["A"], probe=0, preregister=True))
    state, _ = _finish_predictions(state)
    assert state.prediction_log[0].cited == t["B"]


def test_identical_theories_lowest_nobel_counter_when_not_own():
    state, t = _prediction_phase(n=3, allocations=ONE, A=(0, {"IP3": "p"}, {"WO1": "up"}), B=(1, {"IP3": "p"}, {"WO1": "up"}))
    state.paper(t["A"]).nobel = 3
    state.paper(t["B"]).nobel = 1
    state = do(state, a.MakePrediction(seat=2, theory=t["A"], probe=0, preregister=True))
    state, _ = _finish_predictions(state)
    assert state.prediction_log[0].cited == t["B"]


def test_nobel_prize_ends_the_game_for_author_and_allies():
    state, t = _prediction_phase(n=3, allocations=ONE, T=(1, {"IP3": "p"}, {"WO1": "up"}))
    state.alliances = [[1, 2]]
    state.paper(t["T"]).nobel = S.nobel_condition - 1
    state = do(state, a.MakePrediction(seat=0, theory=t["T"], probe=0, preregister=True))
    state, _ = _finish_predictions(state)
    assert state.result.ending == "nobel" and state.result.primary == [1] and state.result.winners == [1, 2]
    assert state.phase == Phase.GAME_OVER


def test_zero_credit_cannot_reveal_failed_non_preregistered_prediction():
    state, t = _prediction_phase(T=(1, {"IP3": "p"}, {"WO1": "down"}))
    state.researcher(0).credit = 0
    state = do(state, a.MakePrediction(seat=0, theory=t["T"], probe=0), a.CommitPhase(seat=0), a.CommitPhase(seat=1))
    with pytest.raises(IllegalAction, match="0 academic credit"):
        apply(state, a.RevealPrediction(seat=0, prediction=state.predictions[0].id))


def test_crisis_predictions_are_preregistered_and_failures_count():
    state, t = _prediction_phase(period="crisis", T=(1, {"IP3": "p"}, {"WO1": "down"}))
    state.rounds_in_crisis = 1
    before = _credits(state)
    state = do(state, a.MakePrediction(seat=0, theory=t["T"], probe=0))
    assert state.predictions[0].preregistered
    state, _ = _finish_predictions(state)
    # One failed prediction plus one miss for each other Probe.
    assert state.unsuccessful_predictions == 1 + (len(state.probes) - 1)
    assert state.researcher(0).credit == max(0, before[0] + S.failed_prereg_pred_ac_crisis)
    assert state.researcher(1).credit == max(0, before[1] + S.crisis_failed_pred_citation_penalty)


def test_crisis_success_bonus_and_crash():
    state, t = _prediction_phase(period="crisis", T=(1, {"IP3": "p"}, {"WO1": "up"}))
    state.rounds_in_crisis = 1
    before = _credits(state)
    state = do(state, a.MakePrediction(seat=0, theory=t["T"], probe=0))
    state, _ = _finish_predictions(state)
    assert state.researcher(0).credit - before[0] == (1 + S.crisis_pred_base_bonus) * 1 * 2
    assert state.researcher(1).credit - before[1] == S.citation_reward + S.crisis_pred_citation_reward_bonus
    assert state.paper(t["T"]).nobel == 0  # not tracked in the Crisis

    crash, _ = _prediction_phase(period="crisis", T=(1, {"IP3": "p"}, {"WO1": "up"}))
    crash.unsuccessful_predictions = S.crisis_condition - 1
    crash, _ = _finish_predictions(crash)
    assert crash.result.ending == "crisis_crash" and crash.result.winners == []

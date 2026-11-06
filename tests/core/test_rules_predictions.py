"""Rulebook "Observation and prediction phase": "Formulating predictions and preregistration",
"Preregistration pruning", "Outcome and Prediction Reveal", "Scoring predictions", "Failed
predictions"; "Nobel Prize"; "Retraction"; "Crisis"; specification 5.7 (pruning, missed Probes).

The test world has two world outcomes so the outcome multiplier can be checked:
IP1 (a, b), IP2 (x, y), IP3 (p, q); WO1 (up, down) is "up" exactly when IP1 = a, WO2 (big, small)
is "big" exactly when IP2 = x. Every Probe is set to show IP1 = a, IP2 = x, IP3 = p with
outcomes up and big unless a test says otherwise.
"""

import itertools

import pytest

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply
from nv_core.state import Card, Phase, Task
from nv_core.world_data import Variable, WorldData, WorldRow
from tests.core.engine_helpers import do, game, publish, settings, to_phase

S = settings()
INPUTS = {"IP1": ["a", "b"], "IP2": ["x", "y"], "IP3": ["p", "q"]}
OUTCOMES = {"WO1": ["up", "down"], "WO2": ["big", "small"]}
SHOWN = {"IP1": "a", "IP2": "x", "IP3": "p"}
TRUE = {"WO1": "up", "WO2": "big"}
STEPS = (Phase.PREDICTION, Phase.REVEAL, Phase.SCORING_ORDER)


def two_outcome_world() -> WorldData:
    rows = []
    for combo in itertools.product(*INPUTS.values()):
        inputs = dict(zip(INPUTS, combo))
        outcomes = {"WO1": "up" if inputs["IP1"] == "a" else "down", "WO2": "big" if inputs["IP2"] == "x" else "small"}
        rows.append(WorldRow(inputs=inputs, outcomes=outcomes))
    return WorldData(
        scenario_id="tiny2",
        title="Tiny with two outcomes",
        story="",
        world_id="tiny2_world",
        input_parameters=[Variable(id=k, name=k.lower(), states=v) for k, v in INPUTS.items()],
        world_outcomes=[Variable(id=k, name=k.lower(), states=v) for k, v in OUTCOMES.items()],
        rows=rows,
    )


def _column(state, probe, inputs=SHOWN, outcomes=TRUE):
    p = state.probes[probe]
    for var, value in inputs.items():
        p.readings[var] = Card(var=var, state=value, origin="supply")
    for var, value in outcomes.items():
        p.outcomes[var] = Card(var=var, state=value, origin="supply")


def _at_prediction(n=2, period="calm", dc=2, **overrides):
    """Reach the prediction step; every researcher has ``dc`` data collection postdocs and one
    development postdoc (so the game stops at the Development phase after scoring)."""
    state = game(n, world=two_outcome_world(), **overrides)
    state.period_deck = "c" * 200
    if period == "crisis":
        state.period, state.rounds_in_crisis = "crisis", 1
    state = to_phase(state, Phase.PREDICTION, {s: {"data_collection": dc, "development": 1} for s in range(n)})
    for p in state.probes:
        _column(state, p.index)
    return state


def _theory(state, author, inputs, outcomes, **fields):
    paper = publish(state, author, inputs=inputs, outcomes=outcomes)
    for k, v in fields.items():
        setattr(paper, k, v)
    return paper


def _predict(state, seat, theory, probe, prereg=False):
    state = do(state, a.MakePrediction(seat=seat, theory=theory, probe=probe, preregister=prereg))
    return state, state.predictions[-1].id


def _to_reveal(state):
    while state.phase == Phase.PREDICTION and state.waiting:
        state = do(state, a.CommitPhase(seat=state.waiting[0]))
    return state


def _finish(state):
    for _ in range(30):
        if state.result or state.phase not in STEPS or not state.waiting:
            break
        state = do(state, a.CommitPhase(seat=state.waiting[0]))
    return state


def _credits(state):
    return [r.credit for r in state.researchers]


def _log(state, prediction_id):
    return next(p for p in state.prediction_log if p.id == prediction_id)


# Formulating predictions and preregistration --------------------------------------------
def test_prediction_needs_a_data_collection_staff_member():
    """Formulating predictions and preregistration: at least one staff member on data collection."""
    state = game(world=two_outcome_world())
    state.period_deck = "c" * 200
    state = to_phase(state, Phase.PREDICTION, {0: {"data_collection": 1, "development": 1}, 1: {"development": 1}})
    t = _theory(state, 0, {"IP1": "a"}, {"WO1": "up"})
    with pytest.raises(IllegalAction):
        apply(state, a.MakePrediction(seat=1, theory=t.id, probe=0))
    apply(state, a.MakePrediction(seat=0, theory=t.id, probe=0))


def test_crisis_predictions_cannot_be_made_hidden():
    """Formulating predictions and preregistration: during the Crisis period all Predictions must be
    preregistered."""
    state = _at_prediction(period="crisis")
    t = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"})
    state, pid = _predict(state, 0, t.id, 0)
    with pytest.raises(IllegalAction):
        apply(state, a.SetPreregistered(seat=0, prediction=pid, preregister=False))


# Outcome and Prediction Reveal ------------------------------------------------------------
def test_reveal_limited_by_data_collection_staff_including_preregistered():
    """Outcome and Prediction Reveal: Preregistered plus revealed predictions at most the data
    collection staff; with one staff member and one Preregistered prediction nothing more is revealed."""
    state = _at_prediction(dc=1)
    t = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"})
    u = _theory(state, 1, {"IP2": "x"}, {"WO2": "big"})
    state, _ = _predict(state, 0, t.id, 0, prereg=True)
    state, hidden = _predict(state, 0, u.id, 1)
    state = _to_reveal(state)
    with pytest.raises(IllegalAction):
        apply(state, a.RevealPrediction(seat=0, prediction=hidden))
    state = _finish(state)
    assert _log(state, hidden).status not in ("revealed", "scored", "pruned")


def test_cannot_reveal_a_prediction_on_someone_elses_preregistered_theory():
    """Outcome and Prediction Reveal: only predictions not based on the same theory as any
    Preregistered prediction can be revealed."""
    state = _at_prediction()
    t = _theory(state, 0, {"IP1": "a"}, {"WO1": "up"})
    state, _ = _predict(state, 1, t.id, 1, prereg=True)
    state, hidden = _predict(state, 0, t.id, 0)
    state = _to_reveal(state)
    with pytest.raises(IllegalAction):
        apply(state, a.RevealPrediction(seat=0, prediction=hidden))


def test_reveal_pruning_keeps_turn_order_and_pruned_prediction_uses_staff():
    """Outcome and Prediction Reveal: of two revealed predictions on one theory the one earlier in
    turn order stays, the author gets [citation_reward] for the discarded one, and a pruned
    prediction still uses a data collection staff member."""
    state = _at_prediction()
    first, second = state.turn_order()[:2]
    t = _theory(state, second, {"IP1": "a"}, {"WO1": "down"})  # fails on every Probe
    before = _credits(state)
    state, p_first = _predict(state, first, t.id, 0)
    state, p_second = _predict(state, second, t.id, 1)
    state = _to_reveal(state)
    state = do(state, a.RevealPrediction(seat=first, prediction=p_first), a.RevealPrediction(seat=second, prediction=p_second))
    state = _finish(state)
    assert _log(state, p_first).status == "scored" and _log(state, p_second).status == "pruned"
    assert state.researcher(first).credit - before[first] == S.failed_non_prereg_pred_ac
    assert state.researcher(second).credit - before[second] == S.citation_reward
    assert state.researcher(second).used.get(Task.DATA_COLLECTION, 0) == 1


# Scoring predictions ---------------------------------------------------------------------
@pytest.mark.parametrize("prereg", [False, True])
def test_success_value_is_inputs_times_outcomes_doubled_if_preregistered(prereg):
    """Scoring predictions (Successful predictions): base = input parameters in the theory, times the
    world outcomes shown, doubled when preregistered; the author gets [citation_reward]."""
    state = _at_prediction()
    t = _theory(state, 1, {"IP1": "a", "IP2": "x"}, {"WO1": "up", "WO2": "big"})
    before = _credits(state)
    state, pid = _predict(state, 0, t.id, 0, prereg=prereg)
    if not prereg:
        state = _to_reveal(state)
        state = do(state, a.RevealPrediction(seat=0, prediction=pid))
    state = _finish(state)
    assert state.researcher(0).credit - before[0] == 2 * 2 * (2 if prereg else 1)
    assert state.researcher(1).credit - before[1] == S.citation_reward
    assert state.paper(t.id).patents == [0]


def test_outcome_not_shown_on_the_theory_is_disregarded():
    """Scoring predictions: a theory showing only one world outcome only needs to match that one."""
    state = _at_prediction()
    _column(state, 0, outcomes={"WO1": "up", "WO2": "small"})
    t = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"})
    before = _credits(state)
    state, pid = _predict(state, 0, t.id, 0, prereg=True)
    state = _finish(state)
    assert _log(state, pid).success
    assert state.researcher(0).credit - before[0] == 1 * 1 * 2


def test_one_mismatching_outcome_makes_the_prediction_fail():
    """Scoring predictions / Failed predictions: every outcome on the theory must match; a failed
    preregistered prediction scores [failed_prereg_pred_ac], resets the Nobel counter and adds one
    to the Retraction counter."""
    state = _at_prediction()
    _column(state, 0, outcomes={"WO1": "up", "WO2": "small"})
    t = _theory(state, 1, {"IP1": "a"}, {"WO1": "up", "WO2": "big"}, nobel=2)
    before = _credits(state)
    state, pid = _predict(state, 0, t.id, 0, prereg=True)
    state = _finish(state)
    assert not _log(state, pid).success
    assert state.researcher(0).credit == max(0, before[0] + S.failed_prereg_pred_ac)
    assert state.researcher(1).credit == before[1]
    assert state.paper(t.id).nobel == 0 and state.paper(t.id).retraction == 1
    assert state.paper(t.id).patents == []


def test_crisis_success_with_two_outcomes():
    """Scoring predictions: in the Crisis the base is increased by [crisis_pred_base_bonus] before the
    outcome multiplier; Crisis predictions are preregistered, so the value is doubled."""
    state = _at_prediction(period="crisis")
    t = _theory(state, 1, {"IP1": "a", "IP2": "x"}, {"WO1": "up", "WO2": "big"})
    before = _credits(state)
    state, _ = _predict(state, 0, t.id, 0)
    state = _finish(state)
    assert state.researcher(0).credit - before[0] == (2 + S.crisis_pred_base_bonus) * 2 * 2
    assert state.researcher(1).credit - before[1] == S.citation_reward + S.crisis_pred_citation_reward_bonus


def test_success_resets_the_retraction_counter():
    """Successful predictions: set the retraction counter of the cited theory to 0."""
    state = _at_prediction()
    t = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"}, retraction=S.retraction_threshold - 1)
    state, _ = _predict(state, 0, t.id, 0, prereg=True)
    state = _finish(state)
    assert state.paper(t.id).retraction == 0 and state.paper(t.id).nobel == 1


def test_one_below_the_retraction_threshold_stays_published():
    """Retraction: only reaching [retraction_threshold] retracts the theory."""
    if S.retraction_threshold < 2:
        pytest.skip("needs a threshold of at least 2")
    state = _at_prediction()
    t = _theory(state, 1, {"IP1": "a"}, {"WO1": "down"}, retraction=S.retraction_threshold - 2)
    before = _credits(state)
    state, _ = _predict(state, 0, t.id, 0, prereg=True)
    state = _finish(state)
    assert state.paper(t.id).retraction == S.retraction_threshold - 1
    assert state.researcher(1).credit == before[1]


def test_retraction_counter_not_tracked_in_crisis():
    """Retraction: the Retraction counters are not tracked during the Crisis period."""
    state = _at_prediction(period="crisis")
    t = _theory(state, 1, {"IP1": "a"}, {"WO1": "down"}, retraction=S.retraction_threshold - 1)
    state, _ = _predict(state, 0, t.id, 0)
    state = _finish(state)
    assert any(p.id == t.id for p in state.published)
    assert state.paper(t.id).retraction == S.retraction_threshold - 1


def test_one_below_the_nobel_condition_does_not_win():
    """Nobel Prize: the author wins once the counter reaches [nobel_condition], not before."""
    state = _at_prediction()
    t = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"}, nobel=S.nobel_condition - 2)
    state, _ = _predict(state, 0, t.id, 0, prereg=True)
    state = _finish(state)
    assert state.result is None
    assert state.paper(t.id).nobel == S.nobel_condition - 1


def test_preregistered_predictions_are_scored_before_revealed_ones():
    """Scoring predictions: scored in the order revealed, Preregistered first. Both theories are one
    success from the Nobel Prize; the Preregistered one (later in turn order) wins it."""
    state = _at_prediction()
    first, second = state.turn_order()[:2]
    a_theory = _theory(state, first, {"IP3": "p"}, {"WO1": "up"}, nobel=S.nobel_condition - 1)
    b_theory = _theory(state, second, {"IP1": "a"}, {"WO1": "up"}, nobel=S.nobel_condition - 1)
    state, hidden = _predict(state, first, a_theory.id, 0)
    state, _ = _predict(state, second, b_theory.id, 1, prereg=True)
    state = _to_reveal(state)
    state = do(state, a.RevealPrediction(seat=first, prediction=hidden))
    state = _finish(state)
    assert state.result.ending == "nobel" and state.result.primary == [second]


def test_turn_order_comes_before_probe_order_in_scoring():
    """Scoring predictions: predictions are scored in turn order, then in Probe order. The first
    researcher predicts on a later Probe; their prediction is still scored first."""
    state = _at_prediction()
    first, second = state.turn_order()[:2]
    a_theory = _theory(state, first, {"IP3": "p"}, {"WO1": "up"}, nobel=S.nobel_condition - 1)
    b_theory = _theory(state, second, {"IP1": "a"}, {"WO1": "up"}, nobel=S.nobel_condition - 1)
    state, _ = _predict(state, first, b_theory.id, 1, prereg=True)
    state, _ = _predict(state, second, a_theory.id, 0, prereg=True)
    state = _finish(state)
    assert state.result.ending == "nobel" and state.result.primary == [second]


@pytest.mark.parametrize("winner_first", [0, 1])
def test_researcher_orders_own_predictions_on_one_probe(winner_first):
    """Scoring predictions: a player with several predictions on one Probe decides their scoring order."""
    state = _at_prediction()
    theories = [
        _theory(state, 0, {"IP3": "p"}, {"WO1": "up"}, nobel=S.nobel_condition - 1),
        _theory(state, 1, {"IP1": "a"}, {"WO1": "up"}, nobel=S.nobel_condition - 1),
    ]
    ids = []
    for t in theories:
        state, pid = _predict(state, 0, t.id, 0, prereg=True)
        ids.append(pid)
    for _ in range(10):
        if state.phase == Phase.SCORING_ORDER or state.result or state.phase not in STEPS:
            break
        state = do(state, a.CommitPhase(seat=state.waiting[0]))
    assert state.phase == Phase.SCORING_ORDER and state.waiting == [0]
    order = [ids[winner_first], ids[1 - winner_first]]
    state = do(state, a.OrderPredictions(seat=0, order=order))
    state = _finish(state)
    assert state.result.primary == [theories[winner_first].author]


# Preregistration pruning: identical theories (specification 5.7) -------------------------
def _identical(n=3):
    state = _at_prediction(n=n, dc=1)
    for r in state.researchers:
        r.credit = 15
    return state


def _cited(state, theory_id):
    state, pid = _predict(state, 0, theory_id, 0, prereg=True)
    state = _finish(state)
    return _log(state, pid).cited


def test_identical_theory_with_someone_elses_fresh_marker_is_not_a_candidate():
    """Preregistration pruning (specification 5.7): another researcher's Fresh out of print theory is
    never cited, even with the lower Nobel counter."""
    state = _identical()
    first = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"}, nobel=3)
    _theory(state, 2, {"IP1": "a"}, {"WO1": "up"}, nobel=0, fresh=True)
    assert _cited(state, first.id) == first.id


def test_identical_theories_prefer_the_author_with_lower_credit():
    """Preregistration pruning: preference 3, the theory of the researcher with the lowest credit."""
    state = _identical()
    rich = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"})
    poor = _theory(state, 2, {"IP1": "a"}, {"WO1": "up"})
    state.researcher(1).credit, state.researcher(2).credit = 20, 5
    assert _cited(state, rich.id) == poor.id


def test_identical_theories_prefer_the_earlier_publication():
    """Preregistration pruning: preference 4, the earlier published theory."""
    state = _identical()
    later = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"}, round=2)
    earlier = _theory(state, 2, {"IP1": "a"}, {"WO1": "up"}, round=1)
    assert _cited(state, later.id) == earlier.id


def test_identical_theories_same_round_go_to_earlier_author_in_turn_order():
    """Preregistration pruning (specification 5.7): a remaining tie goes to the author earlier in turn order."""
    state = _identical()
    by_author = {seat: _theory(state, seat, {"IP1": "a"}, {"WO1": "up"}, round=1) for seat in (1, 2)}
    earlier = next(s for s in state.turn_order() if s in by_author)
    assert _cited(state, by_author[3 - earlier].id) == by_author[earlier].id


# Crisis -----------------------------------------------------------------------------------
def test_probe_with_only_pruned_predictions_counts_as_missed():
    """Crisis (specification 5.7): a Probe whose only predictions were pruned counts as a Probe where
    no one made a prediction. Three Probes: one kept successful prediction, one pruned, one empty,
    so two unsuccessful predictions. [crisis_condition] is raised here so the game goes on."""
    state = _at_prediction(period="crisis", crisis_condition=10)
    first, second = state.turn_order()[:2]
    t = _theory(state, 0, {"IP1": "a"}, {"WO1": "up"})
    state, _ = _predict(state, first, t.id, 0)
    state, pruned = _predict(state, second, t.id, 1)
    state = _finish(state)
    assert _log(state, pruned).status == "pruned"
    assert len(state.probes) == 3
    assert state.unsuccessful_predictions == 2


@pytest.mark.parametrize("below", [0, 1])
def test_crisis_crash_exactly_at_the_condition(below):
    """Crisis: reaching [crisis_condition] unsuccessful predictions is a Crisis Crash; one fewer is not.
    Nobody predicts, so every Probe is a miss."""
    state = _at_prediction(period="crisis")
    start = S.crisis_condition - len(state.probes) - below
    if start < 0:
        pytest.skip("crisis_condition smaller than the number of Probes")
    state.unsuccessful_predictions = start
    state = _finish(state)
    if below == 0:
        assert state.result is not None and state.result.ending == "crisis_crash" and state.result.winners == []
    else:
        assert state.result is None and state.unsuccessful_predictions == S.crisis_condition - 1

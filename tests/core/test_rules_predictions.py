"""Rulebook "Observation and prediction phase": "Formulating predictions and preregistration",
"Outcome and Prediction Reveal", "Scoring predictions", "Failed predictions"; "Nobel Prize";
"Retraction"; "Crisis"; specification 5.7 (identical theories).

The test world has two world outcomes so the outcome multiplier can be checked:
IP1 (a, b), IP2 (x, y), IP3 (p, q); WO1 (up, down) is "up" exactly when IP1 = a, WO2 (big, small)
is "big" exactly when IP2 = x. Every Probe is set to show IP1 = a, IP2 = x, IP3 = p with
outcomes up and big unless a test says otherwise.
"""

import itertools

import pytest

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply, legal_actions
from nv_core.state import Card, Phase, Task
from nv_core.world_data import Variable, WorldData, WorldRow
from tests.core.engine_helpers import do, game, publish, settings, to_phase

S = settings()
INPUTS = {"IP1": ["a", "b"], "IP2": ["x", "y"], "IP3": ["p", "q"]}
OUTCOMES = {"WO1": ["up", "down"], "WO2": ["big", "small"]}
SHOWN = {"IP1": "a", "IP2": "x", "IP3": "p"}
TRUE = {"WO1": "up", "WO2": "big"}
STEPS = (Phase.PREDICTION, Phase.REVEAL, Phase.SCORING_ORDER)
NOBEL = S.nobel_threshold(1)  # the Nobel Prize threshold of a theory published in tier 1 (the test default)


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
    assert _log(state, hidden).status not in ("revealed", "scored")


def test_a_prediction_on_someone_elses_preregistered_theory_can_be_revealed():
    """Outcome and Prediction Reveal: any prediction can be revealed, up to the staff on data collection."""
    state = _at_prediction()
    t = _theory(state, 0, {"IP1": "a"}, {"WO1": "up"})
    state, _ = _predict(state, 1, t.id, 1, prereg=True)
    state, hidden = _predict(state, 0, t.id, 0)
    state = _to_reveal(state)
    state = do(state, a.RevealPrediction(seat=0, prediction=hidden))
    state = _finish(state)
    assert _log(state, hidden).status == "scored"


def test_revealed_predictions_on_one_theory_are_all_scored():
    """Outcome and Prediction Reveal; Scoring predictions: two researchers reveal predictions on the
    same theory on different Probes. Both are scored, both use a staff member, and the retraction
    counter moves once for each Probe."""
    state = _at_prediction()
    first, second = state.turn_order()[:2]
    t = _theory(state, second, {"IP1": "a"}, {"WO1": "down"})  # fails on every Probe
    before = _credits(state)
    state, p_first = _predict(state, first, t.id, 0)
    state, p_second = _predict(state, second, t.id, 1)
    state = _to_reveal(state)
    state = do(state, a.RevealPrediction(seat=first, prediction=p_first), a.RevealPrediction(seat=second, prediction=p_second))
    state = _finish(state)
    assert _log(state, p_first).status == "scored" and _log(state, p_second).status == "scored"
    assert state.researcher(first).credit - before[first] == S.failed_non_prereg_pred_ac
    assert state.researcher(second).credit - before[second] == S.failed_non_prereg_pred_ac
    assert state.researcher(second).used.get(Task.DATA_COLLECTION, 0) == 1
    if S.retraction_threshold > 2:
        assert state.paper(t.id).retraction == 2


def test_one_theory_once_by_a_researcher_on_a_probe():
    """Formulating predictions and preregistration: one theory can only be used once by the same
    researcher on the same Probe in a round, identical copies included."""
    state = _at_prediction()
    t = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"})
    copy = _theory(state, 0, {"IP1": "a"}, {"WO1": "up"})
    state, _ = _predict(state, 0, t.id, 0)
    for theory in (t.id, copy.id):
        with pytest.raises(IllegalAction, match="already predict"):
            apply(state, a.MakePrediction(seat=0, theory=theory, probe=0))
        assert not any(o.type == "make_prediction" and any(x.theory == theory and x.probe == 0 for x in o.actions)
                       for o in legal_actions(state, 0))
    state, _ = _predict(state, 0, t.id, 1)  # another Probe
    state, _ = _predict(state, 1, t.id, 0)  # another researcher


def test_success_counters_move_once_per_theory_per_probe():
    """Successful predictions: the Nobel Prize counter is adjusted once for each theory per Probe per
    round; each prediction still earns its credit and the author's citation reward. The patent goes to
    the first successful predictor in scoring order."""
    state = _at_prediction(n=3)
    first, second, third = state.turn_order()
    t = _theory(state, third, {"IP1": "a"}, {"WO1": "up"})
    before = _credits(state)
    state, _ = _predict(state, first, t.id, 0, prereg=True)
    state, _ = _predict(state, second, t.id, 0, prereg=True)
    state = _finish(state)
    assert state.paper(t.id).nobel == 1
    assert state.paper(t.id).patents == [first]
    gained = 1 * 1 * 2  # one input, one outcome, preregistered
    assert state.researcher(second).credit - before[second] == gained
    assert state.researcher(third).credit - before[third] == 2 * S.citation_reward


def test_failure_counters_move_once_per_theory_per_probe():
    """Failed predictions: the retraction counter is adjusted once for each theory per Probe per round."""
    state = _at_prediction(n=3)
    first, second, third = state.turn_order()
    t = _theory(state, third, {"IP1": "a"}, {"WO1": "down"}, nobel=2)
    state, _ = _predict(state, first, t.id, 0, prereg=True)
    state, _ = _predict(state, second, t.id, 0, prereg=True)
    state = _finish(state)
    assert (state.paper(t.id).retraction, state.paper(t.id).nobel) == (1, 0)


def test_a_theory_retracted_during_scoring_still_scores_the_later_predictions():
    """Scoring predictions (a theory retracted during scoring): a theory retracted by an earlier failed prediction; a later prediction that
    cited it is scored for the researcher who made it."""
    state = _at_prediction()
    first, second = state.turn_order()[:2]
    t = _theory(state, second, {"IP1": "a"}, {"WO1": "down"}, retraction=S.retraction_threshold - 1)
    before = _credits(state)
    state, _ = _predict(state, first, t.id, 0, prereg=True)
    state, late = _predict(state, second, t.id, 1, prereg=True)
    state = _finish(state)
    assert all(p.id != t.id for p in state.published)
    assert _log(state, late).status == "scored"
    expected = S.failed_prereg_pred_ac + S.retraction_ac_penalty
    assert state.researcher(second).credit - before[second] == expected


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


def test_a_theory_carries_at_most_one_patent():
    """Funding > Patents: a theory is linked to at most one patent; a
    later successful prediction with it scores as usual and the first predictor keeps the patent."""
    state = _at_prediction()
    t = _theory(state, 1, {"IP1": "a", "IP2": "x"}, {"WO1": "up", "WO2": "big"}, patents=[1])
    before = _credits(state)
    state, pid = _predict(state, 0, t.id, 0, prereg=True)
    state = _finish(state)
    assert _log(state, pid).success
    assert state.researcher(0).credit - before[0] == 2 * 2 * 2
    assert state.paper(t.id).patents == [1]


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


def test_retraction_in_the_crisis():
    """Retraction: the Retraction counters are tracked in the Crisis period too, and a theory that
    reaches [retraction_threshold] is retracted at once. [crisis_condition] is raised so the game goes on."""
    state = _at_prediction(period="crisis", crisis_condition=10)
    t = _theory(state, 1, {"IP1": "a"}, {"WO1": "down"}, retraction=S.retraction_threshold - 1, nobel=2)
    state.researcher(1).credit = 30
    state, _ = _predict(state, 0, t.id, 0)
    state = _finish(state)
    assert all(p.id != t.id for p in state.published)
    assert state.researcher(1).credit == 30 + S.crisis_failed_pred_citation_penalty + S.retraction_ac_penalty


@pytest.mark.parametrize("tier", [0, 1, 3])
def test_the_nobel_threshold_is_the_condition_minus_the_journal_tier(tier):
    """Nobel Prize: the author wins once the counter reaches [nobel_condition] minus the journal
    tier the theory was published in, not before."""
    threshold = S.nobel_condition - tier
    for start, wins in ((threshold - 2, False), (threshold - 1, True)):
        state = _at_prediction()
        t = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"}, nobel=start, tier=tier)
        state, _ = _predict(state, 0, t.id, 0, prereg=True)
        state = _finish(state)
        if wins:
            assert state.result.ending == "nobel" and state.result.primary == [1]
        else:
            assert state.result is None and state.paper(t.id).nobel == threshold - 1


def test_the_simplified_game_has_its_own_nobel_threshold():
    """Nobel Prize: in the simplified game the threshold is [nobel_condition_simplified]."""
    state = _at_prediction(mode="simplified")
    t = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"}, nobel=S.nobel_condition_simplified - 1, tier=0)
    state, _ = _predict(state, 0, t.id, 0, prereg=True)
    state = _finish(state)
    assert state.result.ending == "nobel" and state.result.primary == [1]


def test_preregistered_predictions_are_scored_before_revealed_ones():
    """Scoring predictions: two waves, Preregistered predictions first. Both theories are one success
    from the Nobel Prize; the Preregistered one wins it although the other is on the Hot topic Probe."""
    state = _at_prediction()
    first, second = state.turn_order()[:2]
    state.hot_topic = 0
    a_theory = _theory(state, first, {"IP3": "p"}, {"WO1": "up"}, nobel=NOBEL - 1)
    b_theory = _theory(state, second, {"IP1": "a"}, {"WO1": "up"}, nobel=NOBEL - 1)
    state, hidden = _predict(state, first, a_theory.id, 0)
    state, _ = _predict(state, second, b_theory.id, 1, prereg=True)
    state = _to_reveal(state)
    state = do(state, a.RevealPrediction(seat=first, prediction=hidden))
    state = _finish(state)
    assert state.result.ending == "nobel" and state.result.primary == [second]


_BY_AUTHOR = ({"IP1": "a"}, {"IP2": "x"}, {"IP3": "p"})  # a different theory for each author; all fit every Probe


@pytest.mark.parametrize("hot_topic", [0, 1, 2])
def test_probes_are_scored_from_the_hot_topic_probe_onwards(hot_topic):
    """Scoring predictions: Probe by Probe, from the Hot topic Probe in the order the marker travels.
    Each Probe has a theory one success from the Nobel Prize, by a different author; the one on the
    Hot topic Probe wins."""
    state = _at_prediction(n=3, dc=3)
    state.hot_topic = hot_topic
    theories = [_theory(state, author, _BY_AUTHOR[author], {"WO1": "up"}, nobel=NOBEL - 1) for author in range(3)]
    for probe, t in enumerate(theories):
        state, _ = _predict(state, 0, t.id, probe, prereg=True)
    state = _finish(state)
    assert state.result.ending == "nobel" and state.result.primary == [theories[hot_topic].author]


def test_the_simplified_game_scores_from_probe_1():
    """Scoring predictions: in the simplified game the cycle starts at Probe 1."""
    state = _at_prediction(mode="simplified")
    assert state.hot_topic is None
    near = S.nobel_condition_simplified - 1
    later = _theory(state, 0, _BY_AUTHOR[0], {"WO1": "up"}, nobel=near, tier=0)
    first = _theory(state, 1, _BY_AUTHOR[1], {"WO1": "up"}, nobel=near, tier=0)
    state, _ = _predict(state, 0, later.id, 2, prereg=True)
    state, _ = _predict(state, 0, first.id, 0, prereg=True)
    state = _finish(state)
    assert state.result.ending == "nobel" and state.result.primary == [1]


@pytest.mark.parametrize("holder_index", [0, 1])
def test_the_researcher_with_probe_time_is_scored_first_on_that_probe(holder_index):
    """Scoring predictions: on one Probe, the predictions of the researcher with Probe time are scored
    first, then turn order decides. Each cites their own theory, one success from the Nobel Prize."""
    state = _at_prediction()
    seats = state.turn_order()[:2]
    holder = seats[holder_index]
    state.probes[0].probe_time = holder
    theories = {seat: _theory(state, seat, _BY_AUTHOR[seat], {"WO1": "up"}, nobel=NOBEL - 1) for seat in seats}
    for seat in seats:
        state, _ = _predict(state, seat, theories[seat].id, 0, prereg=True)
    state = _finish(state)
    assert state.result.primary == [holder]


def test_turn_order_decides_among_researchers_without_probe_time():
    """Scoring predictions: on a Probe nobody holds Probe time on, turn order decides."""
    state = _at_prediction()
    first, second = state.turn_order()[:2]
    state.probes[0].probe_time = None
    theories = {seat: _theory(state, seat, _BY_AUTHOR[seat], {"WO1": "up"}, nobel=NOBEL - 1) for seat in (first, second)}
    state, _ = _predict(state, second, theories[second].id, 0, prereg=True)
    state, _ = _predict(state, first, theories[first].id, 0, prereg=True)
    state = _finish(state)
    assert state.result.primary == [first]


def test_one_researchers_predictions_on_a_probe_go_in_publication_order():
    """Scoring predictions: one researcher's predictions on the same Probe are scored in the
    publication order of their theories (the earlier published first)."""
    state = _at_prediction()
    older = _theory(state, 1, _BY_AUTHOR[2], {"WO1": "up"}, nobel=NOBEL - 1)
    newer = _theory(state, 0, _BY_AUTHOR[0], {"WO1": "up"}, nobel=NOBEL - 1)
    state, _ = _predict(state, 0, newer.id, 0, prereg=True)
    state, _ = _predict(state, 0, older.id, 0, prereg=True)
    state = _finish(state)
    assert state.result.primary == [1]


# Nobel Prize in the Crisis ----------------------------------------------------------------------
def test_reaching_the_threshold_in_the_crisis_does_not_win_at_once():
    """Nobel Prize: in the Crisis the counter moves, but the prize is only checked when the Crisis ends."""
    state = _at_prediction(period="crisis", crisis_condition=99)
    t = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"}, nobel=NOBEL - 1)
    state, _ = _predict(state, 0, t.id, 0)
    state = _finish(state)
    assert state.result is None and state.paper(t.id).nobel == NOBEL


def _crisis_end(theories):
    """Play the last Crisis round to its end with published theories given as (author, tier, Nobel
    counter); nobody predicts, so the counters stay as given."""
    state = _at_prediction(period="crisis", crisis_condition=99)
    state.rounds_in_crisis = S.crisis_length
    made = [_theory(state, author, _BY_AUTHOR[author], {"WO1": "up"}, tier=tier, nobel=nobel)
            for author, tier, nobel in theories]
    for _ in range(200):
        if state.result:
            break
        state = do(state, a.CommitPhase(seat=state.waiting[0]))
    return state, made


def test_at_the_end_of_the_crisis_the_theory_furthest_above_its_threshold_wins():
    """Nobel Prize: when the Crisis ends, of the theories at or above their threshold the one furthest
    above it wins (a tier-3 theory one above beats a tier-0 theory exactly at it)."""
    state, made = _crisis_end([(0, 0, S.nobel_condition), (1, 3, S.nobel_condition - 2)])
    assert state.result.ending == "nobel" and state.result.primary == [1] and state.result.theory == made[1].id


def test_a_tie_at_the_end_of_the_crisis_shares_the_prize():
    """Nobel Prize: on a tie the researchers share the Nobel Prize and win together."""
    state, _ = _crisis_end([(0, 0, S.nobel_condition), (1, 2, S.nobel_condition - 2)])
    assert state.result.ending == "nobel" and state.result.primary == [0, 1]


def test_without_a_theory_at_its_threshold_the_crisis_ends_with_academic_credit():
    """Victory: without a Nobel Prize or a Crisis Crash, the game ends with academic credit."""
    state, _ = _crisis_end([(0, 0, S.nobel_condition - 1)])
    assert state.result.ending == "credit"


# Identical theories (Formulating predictions and preregistration; specification 5.7) ------------
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
    """Identical theories (specification 5.7): another researcher's Fresh out of print theory is
    never cited, even with the lower Nobel counter."""
    state = _identical()
    first = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"}, nobel=3)
    _theory(state, 2, {"IP1": "a"}, {"WO1": "up"}, nobel=0, fresh=True)
    assert _cited(state, first.id) == first.id


def test_identical_theories_prefer_the_most_successes_still_needed():
    """Identical theories: preference 2, the theory with the most successes still needed before its
    Nobel Prize threshold, not the lowest counter (a tier-3 theory at 3 is closer than a tier-0 at 4)."""
    state = _identical()
    high = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"}, tier=3, nobel=3)
    low = _theory(state, 2, {"IP1": "a"}, {"WO1": "up"}, tier=0, nobel=4)
    state.researcher(1).credit, state.researcher(2).credit = 5, 20  # preference 3 would pick the other one
    assert _cited(state, high.id) == low.id


def test_identical_theories_prefer_the_author_with_lower_credit():
    """Identical theories: preference 3, the theory of the researcher with the lowest credit."""
    state = _identical()
    rich = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"})
    poor = _theory(state, 2, {"IP1": "a"}, {"WO1": "up"})
    state.researcher(1).credit, state.researcher(2).credit = 20, 5
    assert _cited(state, rich.id) == poor.id


def test_identical_theories_prefer_the_earlier_publication():
    """Identical theories: preference 4, the earlier published theory."""
    state = _identical()
    later = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"}, round=2)
    earlier = _theory(state, 2, {"IP1": "a"}, {"WO1": "up"}, round=1)
    assert _cited(state, later.id) == earlier.id


def test_identical_theories_same_round_go_to_earlier_author_in_turn_order():
    """Identical theories (specification 5.7): a remaining tie goes to the author earlier in turn order."""
    state = _identical()
    by_author = {seat: _theory(state, seat, {"IP1": "a"}, {"WO1": "up"}, round=1) for seat in (1, 2)}
    earlier = next(s for s in state.turn_order() if s in by_author)
    assert _cited(state, by_author[3 - earlier].id) == by_author[earlier].id


# Crisis -----------------------------------------------------------------------------------
def test_probe_without_predictions_counts_as_missed():
    """Crisis: a Probe where no one made a prediction is an unsuccessful prediction. Three Probes: two
    successful predictions on the same theory, one empty. [crisis_condition] is raised here so the
    game goes on."""
    state = _at_prediction(period="crisis", crisis_condition=10)
    first, second = state.turn_order()[:2]
    t = _theory(state, 0, {"IP1": "a"}, {"WO1": "up"})
    state, _ = _predict(state, first, t.id, 0)
    state, scored = _predict(state, second, t.id, 1)
    state = _finish(state)
    assert _log(state, scored).status == "scored"
    assert len(state.probes) == 3
    assert state.unsuccessful_predictions == 1


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


# Formulating predictions and preregistration: [predictions_per_staff] per data collection staff member
def test_predictions_are_limited_per_data_collection_staff_member():
    state = _at_prediction(dc=1)
    theories = [_theory(state, 1, {"IP1": "a"}, {"WO1": "up"}), _theory(state, 1, {"IP2": "x"}, {"WO2": "big"}),
                _theory(state, 1, {"IP3": "p"}, {"WO1": "up"})]
    allowed = S.predictions_per_staff * 1
    for paper in (theories * allowed)[:allowed]:
        state, _ = _predict(state, 0, paper.id, 0)
    assert not any(o.type == "make_prediction" for o in legal_actions(state, 0))
    with pytest.raises(IllegalAction, match="at most"):
        apply(state, a.MakePrediction(seat=0, theory=theories[0].id, probe=1))
    # withdrawing one makes room again
    state = do(state, a.CancelPrediction(seat=0, prediction=state.predictions[-1].id))
    assert any(o.type == "make_prediction" for o in legal_actions(state, 0))


def test_the_limit_grows_with_the_staff():
    state = _at_prediction(dc=2)
    theories = [_theory(state, 1, {"IP1": "a"}, {"WO1": "up"}), _theory(state, 1, {"IP2": "x"}, {"WO2": "big"}),
                _theory(state, 1, {"IP3": "p"}, {"WO1": "up"})]
    pairs = [(t.id, probe.index) for t in theories for probe in state.probes]
    allowed = S.predictions_per_staff * 2
    for theory, probe in pairs[:allowed]:
        state, _ = _predict(state, 0, theory, probe)
    theory, probe = pairs[allowed]
    with pytest.raises(IllegalAction, match="at most"):
        apply(state, a.MakePrediction(seat=0, theory=theory, probe=probe))


def test_a_game_saved_before_the_limit_has_none():
    from nv_core.settings import Settings

    saved = S.model_dump(mode="json")
    del saved["predictions_per_staff"]
    assert Settings.model_validate(saved).prediction_limit(3) is None


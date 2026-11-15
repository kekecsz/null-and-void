"""Rulebook "Basic mechanics": the simplified game, with the rules marked "Simplified game" and
"Normal game" across the rulebook (Game setup, Hiring and task allocation phase, lab capacity,
Patent, Publication in the simplified game, Funding in the simplified game, Retraction, Hot topic,
Alliance, Clean-up phase), and the mode choice (specification section 11).

The tiny world is in tests/core/engine_helpers.py: WO1 = up exactly when IP1 = a.
"""

import pytest

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply, legal_actions
from nv_core.engine.context import Ctx
from nv_core.engine.development import finish
from nv_core.settings import Settings, SettingsError, load_settings
from nv_core.state import Phase, StaffCount, Task
from nv_core.views import player_view
from tests.core.engine_helpers import do, game, publish, set_readings, settings, to_phase

S = settings()
SIMPLE = {"mode": "simplified"}
# A development staff member makes the game stop at the Development phase.
DATA = {s: {"data_collection": 1, "development": 1} for s in range(2)}


def _types(state, seat):
    return {o.type for o in legal_actions(state, seat)}


# The mode choice ---------------------------------------------------------------------------------
def test_a_game_is_normal_unless_chosen_simplified():
    assert S.mode == "normal" and not S.simplified
    assert settings(**SIMPLE).simplified


def test_an_unknown_mode_is_refused():
    with pytest.raises(SettingsError, match="mode"):
        load_settings({"mode": "easy"})


def test_a_game_saved_before_the_rename_keeps_its_starting_lab_capacity():
    saved = S.model_dump(mode="json", exclude={"mode"})
    del saved["starting_lab_capacity"]
    saved["starting_lab_capacity_advanced"] = 5
    old = Settings.model_validate(saved)
    assert old.starting_lab_capacity == 5 and old.mode == "normal"


# Game setup --------------------------------------------------------------------------------------
def test_simplified_setup_funds_lab_capacity_and_no_hot_topic():
    """Game setup: each researcher starts with [funding_simplified] and a lab capacity of
    [starting_lab_capacity_simplified]; the Hot topic counter is normal game only."""
    state = game(3, **SIMPLE)
    assert all(r.money == S.funding_simplified for r in state.researchers)
    assert all(r.lab_capacity == S.starting_lab_capacity_simplified for r in state.researchers)
    assert state.hot_topic is None


def test_normal_setup_is_unchanged():
    state = game(3)
    funding = S.grant_track[S.grant_track_starting_position - 1].funding
    assert all(r.money == funding and r.lab_capacity == S.starting_lab_capacity for r in state.researchers)
    assert state.hot_topic == 0


@pytest.mark.parametrize("players", [2, 3])
def test_simplified_game_period_deck(players):
    """Game setup: in the simplified game the Game Period Deck parts hold
    [calm_cards_per_player_top_simplified], [..._warning_simplified] and [..._crisis_simplified]
    Calm period cards per player, with the Warning shot card in the middle part and the Crisis
    card in the bottom part."""
    deck = game(players, **SIMPLE).period_deck
    top = S.calm_cards_per_player_top_simplified * players
    warning = S.calm_cards_per_player_warning_simplified * players + 1
    crisis = S.calm_cards_per_player_crisis_simplified * players + 1
    assert len(deck) == top + warning + crisis
    assert set(deck[:top]) == {"c"}
    assert deck[top:top + warning].count("w") == 1 and "x" not in deck[:top + warning]
    assert deck[top + warning:].count("x") == 1


def test_normal_game_period_deck_is_unchanged():
    deck = game(3).period_deck
    assert len(deck) == 3 * (S.calm_cards_per_player_top + S.calm_cards_per_player_warning + S.calm_cards_per_player_crisis) + 2


# Hiring and task allocation phase ------------------------------------------------------------------
def test_simplified_hiring_offers_three_tasks_and_no_students():
    state = game(2, **SIMPLE)
    template = next(o for o in legal_actions(state, 0) if o.type == "allocate_staff").template
    assert template["max_students"] == 0
    assert set(template["tasks"]) == {"experimentation", "data_collection", "development"}


def test_simplified_game_refuses_students():
    """Hiring and task allocation phase: in the simplified game, researchers cannot hire students."""
    state = game(2, **SIMPLE)
    action = a.AllocateStaff(seat=0, hire_students=1, allocation={Task.DATA_COLLECTION: StaffCount(students=1)})
    with pytest.raises(IllegalAction, match="students"):
        apply(state, action)


@pytest.mark.parametrize("task", [Task.WRITE_UP, Task.PEER_REVIEW, Task.TALENT_DEVELOPMENT, Task.GRANTS])
def test_simplified_game_has_only_three_tasks(task):
    state = game(2, **SIMPLE)
    action = a.AllocateStaff(seat=0, hire_postdocs=1, allocation={task: StaffCount(postdocs=1)})
    with pytest.raises(IllegalAction, match="simplified game"):
        apply(state, action)


def test_the_experimentation_cap_is_the_simplified_lab_capacity():
    state = game(2, **SIMPLE)
    n = S.starting_lab_capacity_simplified
    over = a.AllocateStaff(seat=0, hire_postdocs=n + 1, allocation={Task.EXPERIMENTATION: StaffCount(postdocs=n + 1)})
    state.researcher(0).money = 20
    with pytest.raises(IllegalAction, match="lab capacity"):
        apply(state, over)
    apply(state, over.model_copy(update={"hire_postdocs": n, "allocation": {Task.EXPERIMENTATION: StaffCount(postdocs=n)}}))


# Experimentation and equipment phase ------------------------------------------------------------------
def test_lab_capacity_cannot_be_expanded_in_the_simplified_game():
    """Lab capacity: expanding it is normal game only."""
    state = to_phase(game(2, **SIMPLE), Phase.EXPERIMENTATION, {s: {"experimentation": 1} for s in range(2)})
    seat = state.current
    assert "expand_lab" not in _types(state, seat)
    with pytest.raises(IllegalAction, match="simplified"):
        apply(state, a.ExpandLab(seat=seat))
    assert all(r["lab_capacity_cost"] is None for r in player_view(state, seat)["researchers"])


def test_at_zero_credit_a_simplified_researcher_may_pass():
    """Academic credit rules: at 0 credit only actions that cause a penalty are ruled out; the
    simplified game has no unused staff penalty, so passing is allowed."""
    state = to_phase(game(2, **SIMPLE), Phase.EXPERIMENTATION, {s: {"experimentation": 1} for s in range(2)})
    seat = state.current
    state.researcher(seat).credit = 0
    assert "pass" in _types(state, seat)
    apply(state, a.Pass(seat=seat))


# Alliance (normal game only) -------------------------------------------------------------------------
def test_no_alliances_in_the_simplified_game():
    state = game(2, **SIMPLE)
    assert "alliance" not in _types(state, 0)
    with pytest.raises(IllegalAction, match="simplified"):
        apply(state, a.ProposeAlliance(seat=0, partner=1))


# Publication in the simplified game --------------------------------------------------------------------
def test_development_goes_to_the_accept_area_and_is_published_unscored():
    """Publication in the simplified game: after the Development phase, theories and methods go to
    the Accept area in tier 0 with no records and 0 Rounds in processing tokens; no submission fee is
    paid and publication is not scored. Clean-up publishes them with a Fresh out of print marker."""
    state = to_phase(game(2, **SIMPLE), Phase.DEVELOPMENT, DATA)
    state = do(
        state,
        a.FormulateTheory(seat=0, inputs={"IP1": "a"}, outcomes={"WO1": "up"}),
        a.DevelopMethod(seat=1, parameter="IP2"),
    )
    credit = [r.credit for r in state.researchers]
    state = do(state, a.CommitPhase(seat=state.waiting[0]))
    state = do(state, a.CommitPhase(seat=state.waiting[0]))
    assert state.phase == Phase.HIRING and state.round == 2
    theory = next(p for p in state.published if p.kind == "theory")
    method = next(p for p in state.published if p.kind == "method")
    assert (theory.author, theory.tier, theory.fresh) == (0, 0, True)
    assert (method.author, method.idea.parameter) == (1, "IP2")
    assert [r.credit for r in state.researchers] == credit
    assert not state.manuscripts and not any(r.ideas for r in state.researchers)


def test_the_accept_area_holds_the_new_manuscripts_before_clean_up():
    state = to_phase(game(2, **SIMPLE), Phase.DEVELOPMENT, DATA)
    state = do(state, a.FormulateTheory(seat=0, inputs={"IP1": "a"}, outcomes={"WO1": "up"}))
    ctx_state = state.clone()
    finish(Ctx(ctx_state))
    [m] = ctx_state.manuscripts
    assert (m.area, m.tier, m.tokens, m.records, m.open_access) == ("accept", 0, 0, [], False)


# Funding in the simplified game, Clean-up phase -------------------------------------------------------------
def test_simplified_clean_up_flat_funding_no_grants_no_unused_staff_penalty():
    """Funding in the simplified game: a flat rate of [funding_simplified]; grants are ignored and
    the unused staff penalty is normal game only."""
    state = to_phase(game(2, **SIMPLE), Phase.DEVELOPMENT, DATA)
    credit = [r.credit for r in state.researchers]
    grant = [r.grant_position for r in state.researchers]
    state = to_phase(state, Phase.HIRING)  # development staff left unused
    assert [r.credit for r in state.researchers] == credit
    assert [r.grant_position for r in state.researchers] == grant
    assert all(r.money == S.funding_simplified for r in state.researchers)
    assert state.hot_topic is None


# Scoring predictions: no patents; Retraction: the theory is discarded ----------------------------------------
def _prediction_phase(**theories):
    state = game(2, **SIMPLE)
    papers = {k: publish(state, author, inputs=i, outcomes=o).id for k, (author, i, o) in theories.items()}
    state = to_phase(state, Phase.PREDICTION, DATA)
    for p in state.probes:
        set_readings(state, p.index, {"IP1": "a", "IP3": "p"}, outcome="up")
    return state, papers


def _finish_predictions(state):
    for _ in range(10):
        if state.phase not in (Phase.PREDICTION, Phase.REVEAL, Phase.SCORING_ORDER) or not state.waiting:
            break
        state, _ = apply(state, a.CommitPhase(seat=state.waiting[0]))
    return state


def test_no_patent_in_the_simplified_game():
    """Scoring predictions: Patent (normal game only)."""
    state, t = _prediction_phase(T=(1, {"IP3": "p"}, {"WO1": "up"}))
    before = state.researcher(1).credit
    state = do(state, a.MakePrediction(seat=0, theory=t["T"], probe=0, preregister=True))
    state = _finish_predictions(state)
    paper = state.paper(t["T"])
    assert paper.patents == [] and paper.nobel == 1
    assert state.researcher(1).credit == before + S.citation_reward


def test_a_retracted_theory_is_discarded_in_the_simplified_game():
    """Retraction: in the simplified game, the theory is simply discarded."""
    state, t = _prediction_phase(T=(1, {"IP3": "p"}, {"WO1": "down"}))
    state.paper(t["T"]).retraction = S.retraction_threshold - 1
    before = state.researcher(1).credit
    state = do(state, a.MakePrediction(seat=0, theory=t["T"], probe=0, preregister=True))
    state = _finish_predictions(state)
    assert all(p.id != t["T"] for p in state.published)
    assert not state.researcher(1).ideas
    assert state.researcher(1).credit == max(0, before + S.retraction_ac_penalty)

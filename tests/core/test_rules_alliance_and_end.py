"""Rulebook "Alliance", "Academic credit rules" (tie-break), "Victory"; specification 5.2 (alliance
actions any time the rulebook allows)."""

import pytest

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply
from nv_core.engine.context import Ctx
from nv_core.engine.ending import credit_victory, end_game
from nv_core.state import Phase
from tests.core.engine_helpers import do, game, publish, to_phase


# Alliance ---------------------------------------------------------------------------------
def test_a_proposal_alone_forms_no_alliance():
    """Alliance: the alliance must be announced and accepted by both researchers."""
    state = game(n=3)
    state = do(state, a.ProposeAlliance(seat=0, partner=2))
    assert state.alliances == []
    state = do(state, a.AcceptAlliance(seat=2, partner=0))
    assert state.alliances == [[0, 2]]


def test_alliance_actions_outside_ones_turn():
    """Specification 5.2: alliance actions any time the rulebook allows, also in a sequential step
    when it is someone else's turn."""
    state = to_phase(game(n=3), Phase.EXPERIMENTATION, {s: {"experimentation": 1} for s in range(3)})
    current = state.current
    others = [s for s in range(3) if s != current]
    state = do(state, a.ProposeAlliance(seat=others[0], partner=others[1]), a.AcceptAlliance(seat=others[1], partner=others[0]))
    assert state.alliances == [sorted(others)]
    assert state.phase == Phase.EXPERIMENTATION and state.current == current


def test_alliance_formed_after_last_chance_is_unbreakable():
    """Alliance: alliances can be formed until the Crisis card is revealed; once the last chance stage
    is over they are unbreakable."""
    state = game(n=3)
    state.warning_revealed, state.last_chance_done = True, True
    state = do(state, a.ProposeAlliance(seat=0, partner=1), a.AcceptAlliance(seat=1, partner=0))
    assert state.alliances == [[0, 1]]
    with pytest.raises(IllegalAction):
        apply(state, a.LeaveAlliance(seat=0, partner=1))


def test_staying_in_the_last_chance_stage_keeps_the_alliance():
    """Alliance: in the last chance to leave stage, researchers who pass stay allied, after which the
    alliance is unbreakable."""
    state = game(n=3)
    state = do(state, a.ProposeAlliance(seat=0, partner=1), a.AcceptAlliance(seat=1, partner=0))
    state.period_deck = "w" + "c" * 50
    state = to_phase(state, Phase.LAST_CHANCE, {s: {"experimentation": 1} for s in range(3)})
    state = do(state, a.CommitPhase(seat=0), a.CommitPhase(seat=1))
    assert state.alliances == [[0, 1]] and state.last_chance_done
    with pytest.raises(IllegalAction):
        apply(state, a.LeaveAlliance(seat=1, partner=0))


def test_one_researcher_in_several_alliances_shares_victory_with_each_ally():
    """Alliance: a player can be in a pairwise alliance with any number of other players."""
    state = game(n=4)
    state.alliances = [[0, 1], [0, 2]]
    end_game(Ctx(state), "nobel", [0])
    assert sorted(state.result.winners) == [0, 1, 2]
    assert state.phase == Phase.GAME_OVER


def test_tied_credit_victory_includes_each_winners_allies():
    """Alliance / Academic credit rules: in a tied victory every winner's direct allies win too."""
    state = game(n=4)
    state.alliances = [[1, 2]]
    end_game(Ctx(state), "credit", [0, 1])
    assert sorted(state.result.winners) == [0, 1, 2]


def test_crisis_crash_ends_with_no_winners_even_with_alliances():
    """Victory: in a Crisis Crash everyone loses regardless of academic credit."""
    state = game(n=3)
    state.alliances = [[0, 1]]
    end_game(Ctx(state), "crisis_crash", [])
    assert state.result.winners == []


# Academic credit rules ----------------------------------------------------------------------
def test_credit_tie_broken_by_published_theories_not_methods():
    """Academic credit rules: tied researchers are separated by the most published theories."""
    state = game(n=3)
    for seat, credit in enumerate([30, 30, 5]):
        state.researcher(seat).credit = credit
    publish(state, 0, parameter="IP1")
    publish(state, 0, parameter="IP2")
    publish(state, 1, inputs={"IP1": "a"}, outcomes={"WO1": "up"})
    assert credit_victory(Ctx(state)) == [1]


def test_credit_tie_broken_in_favour_of_more_theories():
    """Academic credit rules: the one with the most published theories wins."""
    state = game(n=3)
    for seat, credit in enumerate([30, 30, 5]):
        state.researcher(seat).credit = credit
    publish(state, 0, inputs={"IP1": "a"}, outcomes={"WO1": "up"})
    publish(state, 0, inputs={"IP1": "b"}, outcomes={"WO1": "down"})
    publish(state, 1, inputs={"IP2": "x"}, outcomes={"WO1": "up"})
    publish(state, 2, inputs={"IP2": "y"}, outcomes={"WO1": "up"})
    assert credit_victory(Ctx(state)) == [0]


def test_highest_credit_wins_outright():
    """Victory: the researcher with the highest academic credit wins."""
    state = game(n=3)
    for seat, credit in enumerate([12, 31, 30]):
        state.researcher(seat).credit = credit
    assert credit_victory(Ctx(state)) == [1]

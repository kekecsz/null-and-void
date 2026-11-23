"""Rulebook "Retirement (normal game only)", "Crisis" (Crisis Crash) and "Victory": early retirement
as an Emeritus Professor after a second Tier 5 publication (specification 5.7: Tier 5 is the top
journal tier of the parameter file)."""

import pytest

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply, legal_actions
from nv_core.engine.cleanup import cleanup
from nv_core.engine.context import Ctx
from nv_core.engine.ending import check_crisis_crash
from nv_core.state import Idea, Manuscript, Phase, StaffCount, Task
from nv_core.views import player_view
from tests.core.engine_helpers import do, game, publish, settings

S = settings()
TOP = len(S.journal_tiers) - 1


def _accepted(state, author, tier=TOP):
    """A theory manuscript published at the next Clean-up phase."""
    idea = Idea(id=state.new_id(), kind="theory", inputs={"IP1": "a"}, outcomes={"WO1": "up"})
    state.manuscripts.append(Manuscript(idea=idea, author=author, tier=tier, open_access=False, records=[],
                                        round_submitted=1, area="accept", tokens=0))


def _cleanup(state):
    cleanup(Ctx(state))
    return state


def test_a_second_tier_5_paper_makes_its_author_decide():
    state = game(n=3)
    publish(state, 0, inputs={"IP1": "b"}, outcomes={"WO1": "up"}, tier=TOP)
    _accepted(state, 0)
    _accepted(state, 1)  # researcher 1's first one: no decision
    _cleanup(state)
    assert state.retirement_due == [0]


def test_only_papers_in_the_literature_count_and_not_in_the_crisis():
    state = game(n=2)
    _accepted(state, 0)
    _cleanup(state)
    assert state.retirement_due == []  # only one
    state = game(n=2)
    publish(state, 0, inputs={"IP1": "b"}, outcomes={"WO1": "up"}, tier=TOP)
    state.crisis_revealed, state.period, state.rounds_in_crisis = True, "crisis", 1
    _accepted(state, 0)
    _cleanup(state)
    assert state.retirement_due == []  # Retirement is only possible before the Crisis hits


def test_the_simplified_game_has_no_retirement():
    state = game(n=2, mode="simplified")
    publish(state, 0, inputs={"IP1": "b"}, outcomes={"WO1": "up"}, tier=TOP)
    _accepted(state, 0)
    _cleanup(state)
    assert state.retirement_due == []


def _deciding(seats):
    """The end of a Clean-up phase with ``seats`` deciding, reached through the engine."""
    state = game(n=3)
    for seat in seats:
        publish(state, seat, inputs={"IP1": "b"}, outcomes={"WO1": "up"}, tier=TOP)
        _accepted(state, seat)
    state.phase = Phase.PEER_REVIEW
    state.waiting = [0]
    state.review_cards = {0: []}
    state = do(state, a.CommitPhase(seat=0))
    assert state.phase == Phase.RETIREMENT and state.waiting == seats
    return state


def test_decisions_are_secret_and_revealed_together_then_retired_researchers_cannot_collect_data():
    state = _deciding([0, 1])
    assert {o.type for o in legal_actions(state, 0)} == {"decide_retirement"}  # commit once decided
    state = do(state, a.DecideRetirement(seat=0, retire=True), a.CommitPhase(seat=0))
    assert not state.researcher(0).retired and state.phase == Phase.RETIREMENT  # not revealed yet
    state, events = apply(state, a.DecideRetirement(seat=1, retire=False))
    state, events = apply(state, a.CommitPhase(seat=1))
    assert [e.text for e in events if e.kind == "retirement"] == [f"{state.players[0]} retires as an Emeritus Professor",
                                                                    f"{state.players[1]} does not retire"]
    assert state.researcher(0).retired and not state.researcher(1).retired
    assert state.phase == Phase.HIRING and state.round == 2
    assert player_view(state, 2)["researchers"][0]["retired"]
    r = state.researcher(0)
    r.money = 10
    with pytest.raises(IllegalAction, match="data collection"):
        apply(state, a.AllocateStaff(seat=0, hire_postdocs=1, allocation={Task.DATA_COLLECTION: StaffCount(postdocs=1)}))
    template = next(o for o in legal_actions(state, 0) if o.type == "allocate_staff").template
    assert template["task_caps"][Task.DATA_COLLECTION.value] == 0


def test_a_researcher_who_declined_decides_again_after_the_next_tier_5_paper():
    state = _deciding([0])
    state = do(state, a.DecideRetirement(seat=0, retire=False), a.CommitPhase(seat=0))
    _accepted(state, 0)
    _cleanup(state)
    assert state.retirement_due == [0]


def _crisis(state, retired, unsuccessful=None):
    state.crisis_revealed, state.period, state.rounds_in_crisis = True, "crisis", 1
    for seat in retired:
        state.researcher(seat).retired = True
    if unsuccessful is not None:
        state.unsuccessful_predictions = unsuccessful
    return state


def test_a_crisis_crash_spares_retired_researchers_who_then_win_on_credit_with_their_bonus():
    """Crisis: non-retired researchers lose and their alliances break; the Crisis ends for the survivors:
    no Nobel Prize, the bonus (two Tier 5 papers still published), then credit among them."""
    state = _crisis(game(n=3, alliances=True), retired=[1, 2], unsuccessful=S.crisis_condition)
    state.alliances = [[0, 1]]  # 0 loses: the alliance breaks, so 0 does not win through 1
    for seat, credit in ((0, 99), (1, 10), (2, 20)):
        state.researcher(seat).credit = credit
    for _ in range(2):
        publish(state, 1, inputs={"IP1": "b"}, outcomes={"WO1": "up"}, tier=TOP)
    assert check_crisis_crash(Ctx(state))
    assert state.result.ending == "crisis_crash" and state.result.winners == [1]
    assert state.researcher(1).credit == 10 + S.retirement_bonus and state.researcher(2).credit == 20
    assert state.alliances == []


def test_without_retired_researchers_a_crisis_crash_has_no_winners():
    state = _crisis(game(n=2), retired=[], unsuccessful=S.crisis_condition)
    assert check_crisis_crash(Ctx(state)) and state.result.winners == []


def test_no_nobel_prize_after_a_crisis_crash_even_for_survivors():
    """Crisis: a game ending in a Crisis Crash awards no Nobel Prize; the survivors' bonus and credit decide."""
    state = _crisis(game(n=2), retired=[1], unsuccessful=S.crisis_condition)
    survivor = publish(state, 1, inputs={"IP1": "b"}, outcomes={"WO1": "up"}, tier=1)
    survivor.nobel = S.nobel_threshold(1) + 2
    check_crisis_crash(Ctx(state))
    assert state.result.ending == "crisis_crash" and state.result.winners == [1] and state.result.theory is None


def test_at_the_end_of_the_crisis_the_bonus_comes_before_the_credit_victory():
    state = _crisis(game(n=2), retired=[0])
    state.rounds_in_crisis = S.crisis_length
    for _ in range(2):
        publish(state, 0, inputs={"IP1": "b"}, outcomes={"WO1": "up"}, tier=TOP)
    state.researcher(0).credit, state.researcher(1).credit = 10, 10 + S.retirement_bonus - 1  # no staff: no penalties
    cleanup(Ctx(state))
    assert state.researcher(0).credit == 10 + S.retirement_bonus
    assert state.result.ending == "credit" and state.result.winners == [0]


def test_no_bonus_when_the_nobel_prize_is_won_at_the_end_of_the_crisis():
    state = _crisis(game(n=2), retired=[0])
    state.rounds_in_crisis = S.crisis_length
    for _ in range(2):
        publish(state, 0, inputs={"IP1": "b"}, outcomes={"WO1": "up"}, tier=TOP)
    theory = publish(state, 1, inputs={"IP1": "a"}, outcomes={"WO1": "up"}, tier=1)
    theory.nobel = S.nobel_threshold(1)
    state.researcher(0).credit = 10
    cleanup(Ctx(state))
    assert state.result.ending == "nobel" and state.result.winners == [1]
    assert state.researcher(0).credit == 10

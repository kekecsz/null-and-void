"""Rulebook "Clean-up phase" (each step and their order), "Research grants", "Talent development
phase", "Crisis" (end of the Crisis period), "Academic credit rules" (no credit below 0);
specification 5.7 (Grants staff used).

Most tests call the Clean-up step directly on a quiet state: no staff, no money, no manuscripts,
so only the arranged situation changes credit, money and positions.
"""

import pytest

from nv_core import actions as a
from nv_core.engine.cleanup import cleanup, talent_development
from nv_core.engine.context import Ctx
from nv_core.state import Idea, Manuscript, Phase, StaffCount, Task
from tests.core.engine_helpers import do, game, publish, settings, to_phase

S = settings()


def _quiet(state):
    for r in state.researchers:
        r.postdocs, r.students, r.money = 0, 0, 0
        r.staff, r.used = {}, {}
    state.manuscripts = []
    return state


def _accepted(idea_id, author=0, tokens=0, tier=0):
    """A method manuscript in the Accept area (tier 0 scores no credit, so only counts as a publication)."""
    return Manuscript(
        idea=Idea(id=idea_id, kind="method", parameter="IP1"),
        author=author, tier=tier, open_access=False, records=[], round_submitted=1,
        area="accept", position=None, votes=[], tokens=tokens,
    )


def _give_postdocs(r, task, n, paid=True):
    r.postdocs = n
    r.staff = {task: StaffCount(postdocs=n)} if n else {}
    r.money = n * S.cost_of_postdoc if paid else 0


# Publication step, then token removal -------------------------------------------------------
def test_manuscript_with_one_token_is_published_one_clean_up_later():
    """Clean-up phase: manuscripts with 0 tokens are published, then 1 token is removed from each; so a
    manuscript with 1 token is not published this round but in the next Clean-up."""
    state = _quiet(game())
    state.manuscripts = [_accepted(500, tokens=1)]
    cleanup(Ctx(state))
    assert not any(p.idea.id == 500 for p in state.published)
    assert state.manuscript(500).tokens == 0
    cleanup(Ctx(state))
    paper = next(p for p in state.published if p.idea.id == 500)
    assert paper.fresh and paper.author == 0


def test_publication_in_clean_up_counts_for_the_grant_check():
    """Clean-up phase: publication comes before the grant check, so this round's publications count."""
    state = _quiet(game())
    r = state.researcher(0)
    start = S.grant_track[r.grant_position - 1]
    if start.expected_to_increase is None or start.admin:
        pytest.skip("the starting position cannot be left with no Grants staff")
    state.manuscripts = [_accepted(510 + k) for k in range(start.expected_to_increase)]
    position = r.grant_position
    cleanup(Ctx(state))
    assert r.grant_position == position + 1


# Research grants --------------------------------------------------------------------------
def _grant_position():
    """The first position above 1 with admin and maintenance requirements and a higher position."""
    for i, pos in enumerate(S.grant_track, start=1):
        if i >= 2 and pos.admin > 0 and pos.expected_to_maintain > 0 and pos.expected_to_increase is not None:
            return i
    pytest.skip("no grant position with all requirements")


@pytest.mark.parametrize("case", ["increase", "far_above", "maintain", "below_maintain", "short_admin"])
def test_grant_marker_moves_at_most_one_position(case):
    """Research grants: down one if admin staff or expected to maintain is not met; otherwise up one if
    expected to increase is met; never more than one position. Funding follows the new position."""
    i = _grant_position()
    pos = S.grant_track[i - 1]
    publications, admin, expected = {
        "increase": (pos.expected_to_increase, pos.admin, i + 1),
        "far_above": (pos.expected_to_increase + 3, pos.admin, i + 1),
        "maintain": (pos.expected_to_maintain, pos.admin, i if pos.expected_to_maintain < pos.expected_to_increase else i + 1),
        "below_maintain": (pos.expected_to_maintain - 1, pos.admin, i - 1),
        "short_admin": (pos.expected_to_increase, pos.admin - 1, i - 1),
    }[case]
    state = _quiet(game())
    r = state.researcher(0)
    r.grant_position = i
    _give_postdocs(r, Task.GRANTS, admin)
    state.manuscripts = [_accepted(520 + k) for k in range(publications)]
    cleanup(Ctx(state))
    assert r.grant_position == expected
    assert r.money == S.grant_track[expected - 1].funding


def test_top_grant_position_cannot_increase():
    """Research grants: there is no position above the last one."""
    top = len(S.grant_track)
    pos = S.grant_track[-1]
    state = _quiet(game())
    r = state.researcher(0)
    r.grant_position = top
    _give_postdocs(r, Task.GRANTS, pos.admin)
    state.manuscripts = [_accepted(540 + k) for k in range(pos.expected_to_maintain + 3)]
    cleanup(Ctx(state))
    assert r.grant_position == top


def test_grants_staff_used_is_the_admin_of_the_position_held_before_the_check():
    """Research grants (specification 5.7): staff used = admin requirement of the position held before
    the marker moves; the rest is left on the mat and costs [unused_staff_penalty] each."""
    candidates = [
        i for i, pos in enumerate(S.grant_track, start=1)
        if i >= 2 and pos.expected_to_maintain > 0 and pos.admin != S.grant_track[i - 2].admin
    ]
    if not candidates:
        pytest.skip("no position whose admin differs from the one below")
    i = candidates[0]
    pos = S.grant_track[i - 1]
    state = _quiet(game())
    r = state.researcher(0)
    r.grant_position, r.credit = i, 20
    _give_postdocs(r, Task.GRANTS, pos.admin + 1)  # one more than needed
    state.manuscripts = [_accepted(560 + k) for k in range(pos.expected_to_maintain - 1)]  # fails maintenance
    cleanup(Ctx(state))
    assert r.grant_position == i - 1
    assert r.credit == 20 + 1 * S.unused_staff_penalty


# Postdoc pay, unpaid postdocs, students -----------------------------------------------------
@pytest.mark.parametrize("short, unpaid", [(0, 0), (1, 1), (2 * S.cost_of_postdoc, 2)])
def test_unpaid_postdocs_leave_with_penalty_and_one_talent_step(short, unpaid):
    """Clean-up phase: each postdoc costs [cost_of_postdoc]; unpaid ones leave with
    [unpaid_postdoc_penalty] each, and any unpaid postdoc moves the Talent marker back by 1 (once)."""
    state = _quiet(game())
    r = state.researcher(0)
    _give_postdocs(r, Task.WRITE_UP, 2)
    r.used = {Task.WRITE_UP: 2}
    r.money -= short
    r.credit, r.talent_position = 20, 2
    cleanup(Ctx(state))
    assert r.postdocs == 2 - unpaid
    assert r.credit == 20 + unpaid * S.unpaid_postdoc_penalty
    assert r.talent_position == (2 - 1 if unpaid else 2)


def test_students_always_leave():
    """Clean-up phase: all students leave the lab."""
    state = _quiet(game())
    r = state.researcher(0)
    r.students = 2
    r.staff = {Task.WRITE_UP: StaffCount(students=2)}
    r.used = {Task.WRITE_UP: 2}
    cleanup(Ctx(state))
    assert r.students == 0


def test_academic_credit_never_drops_below_zero():
    """Academic credit rules: academic credit can never drop below 0."""
    state = _quiet(game())
    r = state.researcher(0)
    _give_postdocs(r, Task.WRITE_UP, 2, paid=False)
    r.credit = 1
    cleanup(Ctx(state))
    assert r.credit == 0


# Board resets -----------------------------------------------------------------------------
def test_hot_topic_advances_and_wraps_to_the_leftmost_probe():
    """Clean-up phase: the Hot topic marker moves one Probe right, from the rightmost to the leftmost."""
    state = _quiet(game())
    state.hot_topic = 0
    cleanup(Ctx(state))
    assert state.hot_topic == 1
    state = _quiet(game())
    state.hot_topic = len(state.probes) - 1
    cleanup(Ctx(state))
    assert state.hot_topic == 0


def test_probe_time_markers_and_sideways_papers_are_reset():
    """Clean-up phase: Probe time markers return; sideways Methods and Theories are turned upright."""
    state = _quiet(game())
    state.probes[0].probe_time = 1
    paper = publish(state, 1, parameter="IP2")
    paper.sideways = True
    cleanup(Ctx(state))
    assert all(p.probe_time is None for p in state.probes)
    assert not state.paper(paper.id).sideways


def test_first_researcher_token_moves_to_the_next_player():
    """Clean-up phase: the First researcher token moves to the next player."""
    state = _quiet(game(n=3))
    expected = state.turn_order()[1]
    cleanup(Ctx(state))
    assert state.first_player == expected
    assert state.turn_order()[0] == expected


# Crisis rounds and the end of the game ---------------------------------------------------------
def test_crisis_round_before_the_last_advances_without_ending():
    """Crisis / Clean-up phase: during the Crisis advance the rounds in crisis track; the game only ends
    when it cannot advance any further."""
    state = _quiet(game())
    state.period, state.rounds_in_crisis = "crisis", S.crisis_length - 1
    cleanup(Ctx(state))
    assert state.result is None and state.rounds_in_crisis == S.crisis_length


def test_calm_period_does_not_advance_the_crisis_track():
    """Clean-up phase: the rounds in crisis track only advances during the Crisis period."""
    state = _quiet(game())
    before = state.rounds_in_crisis
    cleanup(Ctx(state))
    assert state.rounds_in_crisis == before and state.result is None


def test_last_crisis_round_counts_this_clean_ups_penalties():
    """Clean-up phase / Crisis: the game ends at the end of the last Clean-up, so the unused-staff
    penalty of that Clean-up decides the credit victory."""
    if S.unused_staff_penalty >= 0:
        pytest.skip("needs a negative unused staff penalty")
    state = _quiet(game())
    state.period, state.rounds_in_crisis = "crisis", S.crisis_length
    leader, chaser = state.researcher(0), state.researcher(1)
    _give_postdocs(leader, Task.WRITE_UP, 2)  # both left unused
    leader.credit = 20
    chaser.credit = 20 + 2 * S.unused_staff_penalty + 1  # behind before, ahead after the penalty
    cleanup(Ctx(state))
    assert state.result.ending == "credit" and state.result.primary == [1]


# Talent development phase -------------------------------------------------------------------
@pytest.mark.parametrize("start", [0, S.talent_track_max])
def test_talent_development_advances_one_up_to_the_maximum_and_always_uses_the_staff(start):
    """Talent development phase: one position per round, at most [talent_track_max]; the staff member
    is used even at the maximum."""
    state = _quiet(game())
    r = state.researcher(0)
    r.talent_position = start
    _give_postdocs(r, Task.TALENT_DEVELOPMENT, 1)
    talent_development(Ctx(state))
    assert r.talent_position == min(start + 1, S.talent_track_max)
    assert r.used.get(Task.TALENT_DEVELOPMENT, 0) == 1


def test_no_talent_development_without_staff():
    """Talent development phase: only researchers with staff on Talent development advance."""
    state = _quiet(game())
    talent_development(Ctx(state))
    assert all(r.talent_position == S.talent_development_track_starting_position for r in state.researchers)


def test_talent_development_comes_before_the_unpaid_postdoc_step():
    """Talent development phase, then Clean-up phase: starting at 0 with a Talent development postdoc
    and no money, the marker goes 0 -> 1 (Talent development) -> 0 (unpaid postdocs). In the opposite
    order it would end at 1."""
    state = game()
    state = to_phase(state, Phase.DEVELOPMENT, {0: {"development": 1, "talent_development": 1}, 1: {"development": 1}})
    r = state.researcher(0)
    r.money, r.talent_position = 0, 0
    state = do(state, a.DevelopMethod(seat=0, parameter="IP2"), a.CommitPhase(seat=0), a.CommitPhase(seat=1))
    assert state.phase == Phase.HIRING and state.round == 2
    assert state.researcher(0).talent_position == 0
    assert state.researcher(0).postdocs == 0

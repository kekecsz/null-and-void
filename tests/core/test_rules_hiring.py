"""Rulebook "Hiring and task allocation phase" (with "Game setup" for the Game Period Deck and
"Alliance" for the Warning shot) and specification 5.2 (Hiring is simultaneous secret).

Values come from docs/parameter_defaults.yaml through load_settings(); only the tiny test world
and hand-made decks are written here.
"""

import pytest

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply, validate
from nv_core.state import Phase, StaffCount, Task
from tests.core.engine_helpers import do, game, settings

S = settings()


def _postdocs(n, task=Task.GRANTS):
    return {task: StaffCount(postdocs=n)} if n else {}


def test_postdoc_pay_may_equal_the_money_but_not_exceed_it():
    """Hiring and task allocation phase: the pay for all postdocs (kept and hired) cannot exceed the money."""
    state = game()
    r = state.researcher(0)
    r.postdocs, r.staff, r.money = 2, {}, 3 * S.cost_of_postdoc
    # 2 kept + 1 hired = 3 postdocs, pay exactly equal to the money: allowed.
    assert validate(state, a.AllocateStaff(seat=0, hire_postdocs=1, allocation=_postdocs(3))) is None
    # 2 kept + 2 hired = 4 postdocs: pay exceeds the money.
    assert validate(state, a.AllocateStaff(seat=0, hire_postdocs=2, allocation=_postdocs(4))) is not None


def test_student_cap_includes_talent_position_exactly():
    """Hiring and task allocation phase: students up to [student_base_hire_cap] plus the Talent position."""
    state = game()
    r = state.researcher(0)
    r.talent_position = min(2, S.talent_track_max)
    r.money = 0  # students need no funding
    cap = S.student_base_hire_cap + r.talent_position
    ok = a.AllocateStaff(seat=0, hire_students=cap, allocation={Task.GRANTS: StaffCount(students=cap)})
    assert validate(state, ok) is None
    over = a.AllocateStaff(seat=0, hire_students=cap + 1, allocation={Task.GRANTS: StaffCount(students=cap + 1)})
    assert validate(state, over) is not None


def test_students_cannot_do_talent_development():
    """Hiring and task allocation phase: Talent development is postdoc only."""
    state = game()
    with pytest.raises(IllegalAction):
        apply(state, a.AllocateStaff(seat=0, hire_students=1, allocation={Task.TALENT_DEVELOPMENT: StaffCount(students=1)}))


def test_one_postdoc_on_talent_development_is_allowed():
    """Hiring and task allocation phase: exactly one staff member may be on Talent development."""
    state = game()
    state.researcher(0).money = 5 * S.cost_of_postdoc
    action = a.AllocateStaff(seat=0, hire_postdocs=1, allocation={Task.TALENT_DEVELOPMENT: StaffCount(postdocs=1)})
    assert validate(state, action) is None


def test_other_tasks_take_any_number_of_staff():
    """Hiring and task allocation phase: the number of staff per task is unlimited (except Talent development)."""
    state = game()
    n = 5
    state.researcher(0).money = n * S.cost_of_postdoc
    action = a.AllocateStaff(seat=0, hire_postdocs=n, allocation={Task.DATA_COLLECTION: StaffCount(postdocs=n)})
    assert validate(state, action) is None


def test_allocation_is_secret_and_editable_until_everyone_commits():
    """Specification 5.2: Hiring and task allocation is simultaneous secret; choices apply when the
    last researcher commits, and a later choice replaces an earlier one (5.3)."""
    state = game()
    for r in state.researchers:
        r.money = 10 * S.cost_of_postdoc
    state.period_deck = "c" * 100
    state = do(
        state,
        a.AllocateStaff(seat=0, hire_postdocs=3, allocation=_postdocs(3)),
        a.AllocateStaff(seat=0, hire_postdocs=1, allocation=_postdocs(1)),
        a.CommitPhase(seat=0),
    )
    assert state.phase == Phase.HIRING and state.waiting == [1]
    assert state.researcher(0).postdocs == 0  # nothing applied yet
    state = do(state, a.AllocateStaff(seat=1, hire_postdocs=1, allocation=_postdocs(1)), a.CommitPhase(seat=1))
    assert state.researcher(0).postdocs == 1  # the second choice counts


def test_period_cards_revealed_count_students_too():
    """Hiring and task allocation phase: one Game Period card per staff member, students included."""
    state = game()
    for r in state.researchers:
        r.money = 5 * S.cost_of_postdoc
    state.period_deck = "c" * 100
    before = len(state.period_deck)
    state = do(
        state,
        # 1 postdoc + 2 students on one task (the leaving students need no choice).
        a.AllocateStaff(seat=0, hire_postdocs=1, hire_students=2, allocation={Task.GRANTS: StaffCount(postdocs=1, students=2)}),
        a.CommitPhase(seat=0),
        a.AllocateStaff(seat=1, hire_postdocs=1, allocation=_postdocs(1)),
        a.CommitPhase(seat=1),
    )
    assert before - len(state.period_deck) == 4


@pytest.mark.parametrize("calm_before, crisis", [(1, True), (2, False)])
def test_crisis_card_only_when_it_is_among_the_revealed_cards(calm_before, crisis):
    """Crisis: the Crisis period starts when the Crisis card is revealed at the end of the Hiring phase.
    Two staff members reveal two cards: a Crisis card in second place is revealed, in third place not."""
    state = game()
    for r in state.researchers:
        r.money = 5 * S.cost_of_postdoc
    state.period_deck = "c" * calm_before + "x" + "c" * 50
    state = do(
        state,
        a.AllocateStaff(seat=0, hire_postdocs=1, allocation=_postdocs(1)),
        a.CommitPhase(seat=0),
        a.AllocateStaff(seat=1, hire_postdocs=1, allocation=_postdocs(1)),
        a.CommitPhase(seat=1),
    )
    assert (state.period == "crisis") is crisis
    assert state.crisis_revealed is crisis


def test_warning_shot_without_alliances_needs_no_last_chance_stage():
    """Alliance: the "last chance to leave" stage only asks researchers in an alliance; with none it
    is passed over (specification 5.2: steps nobody decides are automatic)."""
    state = game()
    for r in state.researchers:
        r.money = 5 * S.cost_of_postdoc
    state.period_deck = "w" + "c" * 50
    state = do(
        state,
        a.AllocateStaff(seat=0, hire_postdocs=1, allocation=_postdocs(1, Task.EXPERIMENTATION)),
        a.CommitPhase(seat=0),
        a.AllocateStaff(seat=1, hire_postdocs=1, allocation=_postdocs(1, Task.EXPERIMENTATION)),
        a.CommitPhase(seat=1),
    )
    assert state.warning_revealed
    assert state.phase != Phase.LAST_CHANCE

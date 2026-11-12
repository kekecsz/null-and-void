"""Rulebook "Hiring and task allocation phase" (with "Game setup" for the Game Period Deck and
"Alliance" for the Warning shot) and specification 5.2 (Hiring is simultaneous secret).

Values come from docs/parameter_defaults.yaml through load_settings(); only the tiny test world
and hand-made decks are written here.
"""

import pytest
import yaml

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply, legal_actions, validate
from nv_core.paths import PARAMETER_DEFAULTS
from nv_core.settings import Settings, SettingsError, load_settings
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


def test_student_cap_includes_the_bonus_of_the_talent_position_exactly():
    """Hiring and task allocation phase: students up to [student_base_hire_cap] plus the bonus student
    cap value of the Talent development track position."""
    state = game()
    r = state.researcher(0)
    r.talent_position = min(2, S.talent_track_max)
    r.money = 0  # students need no funding
    cap = S.student_base_hire_cap + S.talent_development_track[r.talent_position].bonus_student_cap
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


def _reveal(state, staff_of_seat_0):
    """Seat 0 hires that many postdocs, seat 1 nobody; returns how many Game Period cards are revealed."""
    for r in state.researchers:
        r.money = 10 * S.cost_of_postdoc
    state.period_deck = "c" * 100
    state = do(
        state,
        a.AllocateStaff(seat=0, hire_postdocs=staff_of_seat_0, allocation=_postdocs(staff_of_seat_0)),
        a.CommitPhase(seat=0),
        a.CommitPhase(seat=1),
    )
    return 100 - len(state.period_deck)


@pytest.mark.parametrize("minimum, staff, revealed", [(1, 3, 3 + 1), (1, 1, 1 + 1), (3, 2, 3 + 3), (3, 4, 4 + 3), (0, 2, 2)])
def test_each_researcher_counts_for_at_least_the_minimum(minimum, staff, revealed):
    """Specification 5.7, Game Period cards: the minimum replaces a lab's staff count only when it is
    larger; here seat 1 has no staff at all, and seat 0 pays nothing extra for having staff."""
    assert _reveal(game(min_cards_burn_each_round_per_player=minimum), staff) == revealed


def test_a_game_saved_before_the_minimum_existed_keeps_its_rule():
    saved = settings().model_dump(mode="json")
    del saved["min_cards_burn_each_round_per_player"]
    assert Settings.model_validate(saved).min_cards_burn_each_round_per_player == 0


def test_the_parameter_file_must_list_the_minimum(tmp_path):
    data = yaml.safe_load(PARAMETER_DEFAULTS.read_text(encoding="utf-8"))
    del data["min_cards_burn_each_round_per_player"]
    path = tmp_path / "parameters.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(SettingsError, match="min_cards_burn_each_round_per_player: missing"):
        load_settings(path=path)


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


# The [talent_development_track] table --------------------------------------------------------------
_TRACK = [{"bonus student cap": b, "student reliability": r} for b, r in [(0, 0), (2, 0), (2, 3), (5, 1)]]


def test_student_cap_and_threshold_come_from_the_table():
    """Hiring and task allocation phase, Student task check phase: the values of the track position,
    not the position itself."""
    s = settings(talent_development_track=_TRACK, talent_track_max=3)
    assert [s.student_hire_cap(p) - s.student_base_hire_cap for p in range(4)] == [0, 2, 2, 5]
    assert [s.student_unassigned_base_threshold - s.student_leave_threshold(p) for p in range(4)] == [0, 0, 3, 1]


def test_legal_actions_offer_the_cap_of_the_table():
    state = game(talent_development_track=_TRACK, talent_track_max=3)
    state.researcher(0).talent_position = 1
    option = next(o for o in legal_actions(state, 0) if o.type == "allocate_staff")
    assert option.template["max_students"] == state.settings.student_base_hire_cap + 2


def test_a_game_saved_before_the_table_keeps_its_old_rule():
    """A saved game's settings have no table: the position itself is the bonus and the reliability."""
    saved = settings().model_dump(mode="json")
    del saved["talent_development_track"]
    old = Settings.model_validate(saved)
    assert old.student_hire_cap(2) == old.student_base_hire_cap + 2
    assert old.student_leave_threshold(2) == old.student_unassigned_base_threshold - 2


def test_settings_survive_being_saved_and_loaded():
    s = settings()
    assert Settings.model_validate(s.model_dump(mode="json")) == s
    assert Settings.model_validate_json(s.model_dump_json()) == s


def test_the_table_must_cover_every_reachable_position():
    with pytest.raises(SettingsError, match="talent_development_track: no entry for position 3"):
        settings(talent_development_track=_TRACK[:3], talent_track_max=3)


def test_the_parameter_file_must_list_the_table(tmp_path):
    data = yaml.safe_load(PARAMETER_DEFAULTS.read_text(encoding="utf-8"))
    del data["talent_development_track"]
    path = tmp_path / "parameters.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(SettingsError, match="talent_development_track: missing"):
        load_settings(path=path)


# Lab capacity caps Experimentation ----------------------------------------------------------------
def test_researchers_start_with_the_starting_lab_capacity():
    """Game setup: each researcher starts with a lab capacity of [starting_lab_capacity_advanced]."""
    assert all(r.lab_capacity == S.starting_lab_capacity_advanced for r in game(3).researchers)


@pytest.mark.parametrize("students", [0, 1])
def test_experimentation_staff_are_capped_at_the_lab_capacity(students):
    """Hiring and task allocation phase: the Experimentation allocation (postdocs and students
    together) is capped at the researcher's lab capacity."""
    state = game()
    cap = state.researcher(0).lab_capacity
    state.researcher(0).money = 10 * S.cost_of_postdoc
    at_cap = a.AllocateStaff(seat=0, hire_postdocs=cap - students, hire_students=students,
                             allocation={Task.EXPERIMENTATION: StaffCount(postdocs=cap - students, students=students)})
    assert validate(state, at_cap) is None
    over = a.AllocateStaff(seat=0, hire_postdocs=cap + 1 - students, hire_students=students,
                           allocation={Task.EXPERIMENTATION: StaffCount(postdocs=cap + 1 - students, students=students)})
    assert "lab capacity" in validate(state, over)
    template = next(o for o in legal_actions(state, 0) if o.type == "allocate_staff").template
    assert template["task_caps"][Task.EXPERIMENTATION.value] == cap


def test_a_game_saved_before_lab_capacity_has_no_cap():
    state = game()
    state.researcher(0).lab_capacity = None
    n = S.starting_lab_capacity_advanced + 2
    state.researcher(0).money = n * S.cost_of_postdoc
    action = a.AllocateStaff(seat=0, hire_postdocs=n, allocation={Task.EXPERIMENTATION: StaffCount(postdocs=n)})
    assert validate(state, action) is None


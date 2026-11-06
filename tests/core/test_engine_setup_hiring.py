"""Rules engine: Game setup, Hiring and task allocation, Student task check, Experimentation and
equipment, Probe time, Sensor installation and upgrade, Revealing input parameters."""

import pytest

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply, new_game
from nv_core.engine.context import Ctx
from nv_core.engine.observation import deal_probes
from nv_core.engine.setup import specialty_parameters
from nv_core.state import Phase, StaffCount, Task
from tests.core.engine_helpers import allocate, do, game, publish, settings, tiny_world, to_phase


# Game setup ------------------------------------------------------------------------------
@pytest.mark.parametrize("n", [2, 3, 5])
def test_setup_starting_values(n):
    """Game setup: starting positions, money, credit; World Grid has players + 1 Probes."""
    s = settings()
    state = game(n)
    assert len(state.probes) == n + 1
    assert state.hot_topic == 0
    for r in state.researchers:
        assert r.credit == s.starting_academic_credit
        assert r.grant_position == s.grant_track_starting_position
        assert r.talent_position == s.talent_development_track_starting_position
        assert r.money == s.grant_track[s.grant_track_starting_position - 1].funding
    assert state.phase == Phase.HIRING and sorted(state.waiting) == list(range(n))


def test_period_deck_has_warning_and_crisis_in_their_parts():
    """Game setup: Crisis card in the bottom part, Warning shot in the middle, Calm cards on top."""
    s = settings()
    n = 3
    deck = game(n).period_deck
    top, warning = s.calm_cards_per_player_top * n, s.calm_cards_per_player_warning * n + 1
    assert len(deck) == top + warning + s.calm_cards_per_player_crisis * n + 1
    assert set(deck[:top]) == {"c"}
    assert deck[top : top + warning].count("w") == 1
    assert deck[top + warning :].count("x") == 1


def test_specialty_parameters_rotate_from_ip2():
    """Revealing input parameters: IP1 everywhere, then IP2, IP3, IP4, IP2, ... per Probe."""
    from nv_world.game import load_game_world

    world, _, _ = load_game_world("scenarios/venus_expedition/worlds/world_seed1.json")
    assert [specialty_parameters(world, i) for i in range(4)] == [
        ["IP1", "IP2"],
        ["IP1", "IP3"],
        ["IP1", "IP4"],
        ["IP1", "IP2"],
    ]


def test_same_seed_same_game_different_seed_different_deck():
    assert game(seed=5).model_dump() == game(seed=5).model_dump()
    assert game(seed=5).probe_deck != game(seed=6).probe_deck


def test_player_count_limits():
    s = settings()
    with pytest.raises(ValueError):
        new_game(tiny_world(), s, 1, ["only"] * 1)
    with pytest.raises(ValueError):
        new_game(tiny_world(), s, 1, [f"p{i}" for i in range(s.max_players + 1)])


# Hiring and task allocation ---------------------------------------------------------------
def _refused(state, action, fragment):
    with pytest.raises(IllegalAction, match=fragment):
        apply(state, action)


def test_hiring_limits():
    s = settings()
    state = game()
    r = state.researcher(0)
    too_many = r.money // s.cost_of_postdoc + 1
    _refused(state, a.AllocateStaff(seat=0, hire_postdocs=too_many, allocation={Task.GRANTS: StaffCount(postdocs=too_many)}), "cost")
    cap = s.student_base_hire_cap + r.talent_position
    _refused(state, a.AllocateStaff(seat=0, hire_students=cap + 1, allocation={Task.GRANTS: StaffCount(students=cap + 1)}), "at most")
    _refused(state, a.AllocateStaff(seat=0, hire_students=1, allocation={Task.DEVELOPMENT: StaffCount(students=1)}), "postdoc-only")
    _refused(state, a.AllocateStaff(seat=0, hire_students=2, allocation={Task.GRANTS: StaffCount(students=1)}), "allocate every")


def test_only_one_staff_member_on_talent_development():
    state = game()
    state.researcher(0).money = 10
    _refused(state, a.AllocateStaff(seat=0, hire_postdocs=2, allocation={Task.TALENT_DEVELOPMENT: StaffCount(postdocs=2)}), "only one")


def test_fired_postdoc_penalty_and_period_cards():
    """Fired postdocs cost [fired_postdoc_penalty]; one Game Period card is revealed per staff member."""
    s = settings()
    state = game()
    for r in state.researchers:
        r.postdocs, r.money = 3, 10
    deck_before = len(state.period_deck)
    state = do(
        state,
        a.AllocateStaff(seat=0, fire_postdocs=2, allocation={Task.GRANTS: StaffCount(postdocs=1)}),
        a.CommitPhase(seat=0),
        a.AllocateStaff(seat=1, allocation={Task.GRANTS: StaffCount(postdocs=3)}),
        a.CommitPhase(seat=1),
    )
    assert state.researcher(0).credit == s.starting_academic_credit + 2 * s.fired_postdoc_penalty
    assert state.researcher(0).postdocs == 1
    assert deck_before - len(state.period_deck) == 1 + 3


def test_zero_credit_firing_only_what_cannot_be_paid():
    """Academic credit rules: at 0 credit only the un-fundable postdocs may (and must) be fired."""
    s = settings()
    state = game()
    r = state.researcher(0)
    r.credit, r.postdocs, r.money = 0, 3, 2 * s.cost_of_postdoc
    _refused(state, a.AllocateStaff(seat=0, fire_postdocs=2, allocation={Task.GRANTS: StaffCount(postdocs=1)}), "cannot fire")
    apply(state, a.AllocateStaff(seat=0, fire_postdocs=1, allocation={Task.GRANTS: StaffCount(postdocs=2)}))
    r.money = 3 * s.cost_of_postdoc
    _refused(state, a.AllocateStaff(seat=0, fire_postdocs=1, allocation={Task.GRANTS: StaffCount(postdocs=2)}), "cannot fire")


def test_crisis_card_starts_crisis():
    state = game()
    state.period_deck = "cx" + "c" * 10
    state = to_phase(state, Phase.EXPERIMENTATION, {0: {"experimentation": 1}, 1: {"experimentation": 1}})
    assert state.period == "crisis" and state.rounds_in_crisis == 1 and state.unsuccessful_predictions == 0


# Student task check -----------------------------------------------------------------------
def test_student_task_check_threshold(monkeypatch):
    """Dice below [student_unassigned_base_threshold] minus the Talent position send students away."""
    s = settings()
    threshold = s.student_unassigned_base_threshold - 1
    monkeypatch.setattr("nv_core.rng.Rng.dice", lambda self, stream, count, sides=6: [threshold - 1, threshold] * (count // 2))
    state = game()
    for r in state.researchers:
        r.talent_position = 1
    state = do(
        state,
        a.AllocateStaff(seat=0, hire_students=4, allocation={Task.GRANTS: StaffCount(students=4)}),
        a.CommitPhase(seat=0),
        a.AllocateStaff(seat=1, hire_students=2, allocation={Task.GRANTS: StaffCount(students=1), Task.WRITE_UP: StaffCount(students=1)}),
        a.CommitPhase(seat=1),
    )
    # Seat 0: all students on one task, so the two leavers go automatically.
    assert state.researcher(0).students == 2
    # Seat 1: one leaver, students on two tasks: the researcher chooses.
    assert state.phase == Phase.STUDENT_CHECK and state.waiting == [1]
    _refused(state, a.ChooseLeavingStudents(seat=1, by_task={Task.GRANTS: 1, Task.WRITE_UP: 1}), "exactly 1")
    state = do(state, a.ChooseLeavingStudents(seat=1, by_task={Task.WRITE_UP: 1}), a.CommitPhase(seat=1))
    assert state.researcher(1).staff == {Task.GRANTS: StaffCount(students=1)}


# Running experiments ---------------------------------------------------------------------
def _experiment_state():
    state = game()
    return to_phase(state, Phase.EXPERIMENTATION, {0: {"experimentation": 3}, 1: {"experimentation": 3}})


def test_experiment_specifies_free_parameters_and_reads_the_world_table():
    s = settings()
    state = _experiment_state()
    seat = state.current
    free = dict(list({"IP1": "a", "IP2": "x", "IP3": "p"}.items())[: s.experiment_free_input_parameters])
    state = do(state, a.RunExperiment(seat=seat, specified=free))
    experiment = state.researcher(seat).experiments[-1]
    assert {k: experiment.inputs[k] for k in free} == free
    assert experiment.outcomes == {"WO1": "up" if experiment.inputs["IP1"] == "a" else "down"}
    cards = state.researcher(seat).fresh.cards
    assert len(cards) == 4 and {c.experiment for c in cards} == {experiment.id}


def test_experiment_method_citation():
    """A cited method adds its own input parameter, rewards its author, and turns sideways."""
    s = settings()
    state = _experiment_state()
    seat, other = state.current, 1 - state.current
    method = publish(state, other, parameter="IP3")
    spec = {"IP1": "a", "IP2": "x", "IP3": "p"}
    if s.experiment_free_input_parameters < 3:
        _refused(state, a.RunExperiment(seat=seat, specified=spec), "at most")
    credit = state.researcher(other).credit
    state = do(state, a.RunExperiment(seat=seat, specified=spec, cited_methods=[method.id]))
    assert state.researcher(other).credit == credit + s.experiment_method_citation_AC_reward
    assert state.paper(method.id).sideways
    _refused(state, a.RunExperiment(seat=state.current, cited_methods=[method.id], specified={"IP3": "q"}), "already been cited")


def test_fresh_out_of_print_method_only_for_its_author():
    state = _experiment_state()
    seat = state.current
    method = publish(state, 1 - seat, parameter="IP3", fresh=True)
    _refused(state, a.RunExperiment(seat=seat, specified={"IP3": "p"}, cited_methods=[method.id]), "Fresh out of print")


def test_turns_alternate_and_pass_is_final():
    state = _experiment_state()
    first = state.current
    state = do(state, a.RunExperiment(seat=first))
    assert state.current == 1 - first
    state = do(state, a.Pass(seat=1 - first))
    assert state.current == first
    state = do(state, a.RunExperiment(seat=first))
    assert state.current == first  # the other researcher has passed


# Sensor installation and upgrade, Probe time, Revealing input parameters ---------------------
def test_sensor_install_upgrade_reward_and_probe_time():
    s = settings()
    state = _experiment_state()
    seat = state.current
    # In the tiny world P1 has Specialty IP1 and IP2, so IP3 can take a sensor.
    m1, m2 = publish(state, seat, parameter="IP3"), publish(state, seat, parameter="IP3")
    _refused(state, a.InstallSensor(seat=seat, probe=0, parameter="IP2", cited_methods=[m1.id]), "Specialty")
    credit = state.researcher(seat).credit
    state = do(state, a.InstallSensor(seat=seat, probe=0, parameter="IP3", cited_methods=[m1.id]))
    # self-citation reward plus the sensor reward for level 1
    assert state.researcher(seat).credit == credit + s.experiment_method_citation_AC_reward + s.sensor_install_and_upgrade_AC_reward
    assert state.probes[0].sensors == {"IP3": 1}
    assert state.probes[0].probe_time == seat and state.probes[0].probe_time_from_sensor
    state = do(state, a.Pass(seat=state.current)) if state.current != seat else state
    m3 = publish(state, seat, parameter="IP3")
    _refused(state, a.InstallSensor(seat=seat, probe=0, parameter="IP3", cited_methods=[m3.id]), "needs 2")


def test_probe_time_order_by_credit_and_sensor_holders_skip():
    state = game(n=3)
    state = to_phase(state, Phase.EXPERIMENTATION, {s: {"experimentation": 1} for s in range(3)})
    state.researcher(0).credit, state.researcher(1).credit, state.researcher(2).credit = 5, 30, 20
    state.probes[2].probe_time, state.probes[2].probe_time_from_sensor = 2, True
    order = []
    while state.phase in (Phase.EXPERIMENTATION, Phase.PROBE_TIME):
        if state.phase == Phase.PROBE_TIME:
            order.append(state.current)
            free = next(p.index for p in state.probes if p.probe_time is None)
            state = do(state, a.ClaimProbeTime(seat=state.current, probe=free))
        else:
            state = do(state, a.Pass(seat=state.current))
    # Researcher 2 holds Probe time from a sensor; 1 has more credit than 0. With 4 Probes and
    # 3 free, researcher 1 chooses, then researcher 0 is left two Probes and chooses too.
    assert order == [1, 0]


@pytest.mark.parametrize("level", [1, 2, 3])
def test_sensor_noise_cards_halve_per_level(level):
    s = settings()
    state = game()
    state.probes[0].sensors = {"IP3": level}
    ctx = Ctx(state)
    deal_probes(ctx)
    probe = state.probes[0]
    shown_noise = 1 if probe.readings["IP3"].origin == "input_deck" else 0
    assert len(probe.unrevealed_noise["IP3"]) + shown_noise == s.probe_fake_input_deck_size // 2 ** (level - 1)
    assert probe.readings["IP2"] == next(c for c in [probe.readings["IP2"]] if c.origin == "probe")
    assert probe.readings["IP3"].state is not None


def test_unsensed_rows_are_blank_and_crisis_reveals_truth():
    state = game()
    deal_probes(Ctx(state))
    assert state.probes[0].readings["IP3"].state is None
    state.period = "crisis"
    state.probes[0].sensors = {"IP3": 1}
    deal_probes(Ctx(state))
    truth = state.world.rows[state.stack_rows[state.probes[0].stack]].inputs
    assert {v: c.state for v, c in state.probes[0].readings.items()} == truth

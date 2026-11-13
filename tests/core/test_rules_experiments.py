"""Rulebook "Experimentation and equipment phase": "Running experiments", "Recording experimental
findings", "Sensor installation and upgrade", lab capacity; "Academic credit rules" (at 0 credit, specification 5.7).

The tiny world (tests/core/engine_helpers.py) has inputs IP1, IP2, IP3. Probe 1 (index 0) has
Specialty IP1 and IP2, so IP3 can take a sensor there.
"""

import pytest

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply, legal_actions, validate
from nv_core.state import Phase, Task
from tests.core.engine_helpers import do, game, publish, settings, to_phase

S = settings()


def _experimentation(k=1, n=2, extra=None, **overrides):
    """Reach the Experimentation phase with k experimentation postdocs per researcher."""
    state = game(n, **overrides)
    allocation = {"experimentation": k, **(extra or {})}
    return to_phase(state, Phase.EXPERIMENTATION, {s: dict(allocation) for s in range(n)})


def _until_turn_of(state, seat):
    """Let the other researchers pass until it is ``seat``'s turn again."""
    while state.phase == Phase.EXPERIMENTATION and state.current != seat:
        state = do(state, a.Pass(seat=state.current))
    return state


def _deck_size(state, var):
    return len(state.input_decks[var])


# Running experiments ------------------------------------------------------------------------
def test_specified_states_come_from_supply_unspecified_from_the_input_deck():
    """Running experiments: specified states come from the State Cards; unspecified ones are drawn
    from that parameter's Input Parameter Deck."""
    state = _experimentation()
    seat = state.current
    before = {v: _deck_size(state, v) for v in ("IP1", "IP2", "IP3")}
    state = do(state, a.RunExperiment(seat=seat, specified={"IP1": "a"}))
    experiment = state.researcher(seat).experiments[-1]
    cards = {c.card.var: c.card for c in state.researcher(seat).records.cards if c.experiment == experiment.id}
    assert cards["IP1"].origin == "supply" and cards["IP1"].state == "a"
    assert cards["IP2"].origin == "input_deck" and cards["IP3"].origin == "input_deck"
    assert _deck_size(state, "IP1") == before["IP1"]
    assert _deck_size(state, "IP2") == before["IP2"] - 1
    assert _deck_size(state, "IP3") == before["IP3"] - 1


def test_two_methods_for_the_same_parameter_cannot_be_cited_together():
    """Running experiments: methods cited for one experiment must be specific to different parameters."""
    state = _experimentation(experiment_free_input_parameters=1)
    seat = state.current
    m1 = publish(state, 1 - seat, parameter="IP3")
    m2 = publish(state, 1 - seat, parameter="IP3")
    with pytest.raises(IllegalAction):
        apply(state, a.RunExperiment(seat=seat, specified={"IP1": "a", "IP2": "x", "IP3": "p"}, cited_methods=[m1.id, m2.id]))


def test_each_cited_method_adds_its_own_parameter_and_pays_its_author():
    """Running experiments: one free parameter (hand-set) plus one per cited method; each cited
    author gets [experiment_method_citation_AC_reward]."""
    state = _experimentation(experiment_free_input_parameters=1)
    seat, other = state.current, 1 - state.current
    m2 = publish(state, other, parameter="IP2")
    m3 = publish(state, other, parameter="IP3")
    spec = {"IP1": "a", "IP2": "x", "IP3": "p"}
    # 1 free + 1 method = 2 parameters: three specified states are too many.
    assert validate(state, a.RunExperiment(seat=seat, specified=spec, cited_methods=[m3.id])) is not None
    credit = state.researcher(other).credit
    state = do(state, a.RunExperiment(seat=seat, specified=spec, cited_methods=[m2.id, m3.id]))
    assert state.researcher(other).credit == credit + 2 * S.experiment_method_citation_AC_reward
    # Methods can be cited any number of times.
    assert validate(state, a.RunExperiment(seat=state.current, specified=spec, cited_methods=[m2.id, m3.id])) is None


def test_author_may_cite_own_fresh_out_of_print_method():
    """Running experiments: methods with the Fresh out of print marker can be used by their authors."""
    state = _experimentation()
    seat = state.current
    method = publish(state, seat, parameter="IP3", fresh=True)
    spec = dict(list({"IP1": "a", "IP2": "x"}.items())[: S.experiment_free_input_parameters]) | {"IP3": "p"}
    assert validate(state, a.RunExperiment(seat=seat, specified=spec, cited_methods=[method.id])) is None


def test_experiments_are_limited_by_experimentation_staff():
    """Experimentation and equipment phase: one action per staff member; a researcher who cannot act
    any more must pass, so the phase ends once the others pass."""
    state = _experimentation(k=1)
    first = state.current
    state = do(state, a.RunExperiment(seat=first))
    assert state.current != first
    state = do(state, a.Pass(seat=state.current))
    assert state.phase != Phase.EXPERIMENTATION
    assert len(state.researcher(first).experiments) == 1


def test_only_the_researcher_whose_turn_it_is_may_act():
    """Experimentation and equipment phase: completed sequentially, in turn order."""
    state = _experimentation()
    waiting = 1 - state.current
    with pytest.raises(IllegalAction):
        apply(state, a.RunExperiment(seat=waiting))


def test_at_zero_credit_a_researcher_cannot_pass_with_staff_left():
    """Academic credit rules (specification 5.7): at 0 academic credit a researcher must use every
    staff member that can still be used."""
    state = _experimentation()
    seat = state.current
    state.researcher(seat).credit = 0
    with pytest.raises(IllegalAction):
        apply(state, a.Pass(seat=seat))
    apply(state, a.RunExperiment(seat=seat))


# Sensor installation and upgrade -----------------------------------------------------------
def test_upgrade_needs_level_plus_one_methods_and_pays_per_level_reached():
    """Sensor installation and upgrade: upgrading a level 1 Sensor cites 2 methods for that
    parameter; reward [sensor_install_and_upgrade_AC_reward] x 2, plus each citation reward."""
    state = _experimentation()
    seat = state.current
    state.probes[0].sensors = {"IP3": 1}
    m1, m2 = publish(state, seat, parameter="IP3"), publish(state, seat, parameter="IP3")
    credit = state.researcher(seat).credit
    state = do(state, a.InstallSensor(seat=seat, probe=0, parameter="IP3", cited_methods=[m1.id, m2.id]))
    assert state.probes[0].sensors["IP3"] == 2
    assert state.researcher(seat).credit == credit + 2 * S.sensor_install_and_upgrade_AC_reward + 2 * S.experiment_method_citation_AC_reward


def test_level_3_sensor_cannot_be_upgraded():
    """Sensor installation and upgrade: only level 1 or level 2 Sensors can be upgraded."""
    state = _experimentation()
    seat = state.current
    state.probes[0].sensors = {"IP3": 3}
    methods = [publish(state, seat, parameter="IP3").id for _ in range(4)]
    with pytest.raises(IllegalAction):
        apply(state, a.InstallSensor(seat=seat, probe=0, parameter="IP3", cited_methods=methods))


def test_same_sensor_can_be_upgraded_twice_in_one_round():
    """Sensor installation and upgrade: one level at a time, but several times in the same round."""
    state = _experimentation(k=2)
    seat = state.current
    m1, m2, m3 = (publish(state, seat, parameter="IP3") for _ in range(3))
    state = do(state, a.InstallSensor(seat=seat, probe=0, parameter="IP3", cited_methods=[m1.id]))
    state = _until_turn_of(state, seat)
    state = do(state, a.InstallSensor(seat=seat, probe=0, parameter="IP3", cited_methods=[m2.id, m3.id]))
    assert state.probes[0].sensors["IP3"] == 2


def test_sensor_needs_a_method_for_that_parameter():
    """Sensor installation and upgrade: the cited Method must be specific to that Input Parameter."""
    state = _experimentation()
    seat = state.current
    wrong = publish(state, seat, parameter="IP2")
    with pytest.raises(IllegalAction):
        apply(state, a.InstallSensor(seat=seat, probe=0, parameter="IP3", cited_methods=[wrong.id]))


def test_fresh_out_of_print_method_for_sensors_only_by_its_author():
    """Sensor installation and upgrade: Fresh out of print methods only by their authors."""
    state = _experimentation()
    seat = state.current
    others = publish(state, 1 - seat, parameter="IP3", fresh=True)
    own = publish(state, seat, parameter="IP3", fresh=True)
    assert validate(state, a.InstallSensor(seat=seat, probe=0, parameter="IP3", cited_methods=[others.id])) is not None
    assert validate(state, a.InstallSensor(seat=seat, probe=0, parameter="IP3", cited_methods=[own.id])) is None


def test_sensor_does_not_take_an_occupied_probe_time_slot():
    """Sensor installation and upgrade: the marker goes on the Probe time slot only if it is free."""
    state = _experimentation()
    seat, other = state.current, 1 - state.current
    state.probes[0].probe_time = other
    method = publish(state, seat, parameter="IP3")
    state = do(state, a.InstallSensor(seat=seat, probe=0, parameter="IP3", cited_methods=[method.id]))
    assert state.probes[0].probe_time == other
    assert state.probes[0].sensors == {"IP3": 1}


def test_sensor_installed_this_round_shows_a_reading_this_round():
    """Revealing input parameters: Probes are dealt at the start of the Observation and prediction
    phase, so a sensor installed in the Experimentation phase applies in the same round."""
    state = _experimentation(extra={"data_collection": 1})
    seat = state.current
    method = publish(state, seat, parameter="IP3")
    state = do(state, a.InstallSensor(seat=seat, probe=0, parameter="IP3", cited_methods=[method.id]))
    state = to_phase(state, Phase.PREDICTION)
    assert state.probes[0].readings["IP3"].state is not None
    assert state.probes[0].probe_time == seat


def test_experiment_uses_an_experimentation_staff_member():
    """Task resolution: a staff member who resolves a task is used."""
    state = _experimentation(k=2)
    seat = state.current
    state = do(state, a.RunExperiment(seat=seat))
    assert state.researcher(seat).used.get(Task.EXPERIMENTATION, 0) == 1


# Lab capacity ---------------------------------------------------------------------------------------
COSTS = S.lab_capacity_costs()


def _expand_options(state, seat):
    return [o for o in legal_actions(state, seat) if o.type == "expand_lab"]


def test_lab_capacity_costs_come_from_the_parameter_file():
    assert COSTS == [S.bonus_lab_capacity_1, S.bonus_lab_capacity_2, S.bonus_lab_capacity_3]


def test_increasing_lab_capacity_costs_money_but_no_staff_and_not_the_turn():
    """Experimentation and equipment phase (Lab capacity): pay [bonus_lab_capacity_1] for the first
    step; no staff member is used and it is still the researcher's turn."""
    state = _experimentation(k=1)
    seat = state.current
    before = state.researcher(seat).model_copy(deep=True)
    state = do(state, a.ExpandLab(seat=seat))
    r = state.researcher(seat)
    assert r.lab_capacity == before.lab_capacity + 1
    assert r.money == before.money - COSTS[0]
    assert r.remaining(Task.EXPERIMENTATION) == before.remaining(Task.EXPERIMENTATION)
    assert state.current == seat


def test_lab_capacity_can_be_increased_when_it_is_not_your_turn():
    """Lab capacity: any time during the Experimentation and equipment phase."""
    state = _experimentation(k=1)
    other = 1 - state.current
    assert _expand_options(state, other)
    state = do(state, a.ExpandLab(seat=other))
    assert state.researcher(other).lab_capacity == S.starting_lab_capacity_advanced + 1


def test_only_once_per_round():
    """Lab capacity: by 1, and only 1 per round; the next round it can be increased again."""
    state = _experimentation(k=1)
    seat = state.current
    state = do(state, a.ExpandLab(seat=seat))
    with pytest.raises(IllegalAction, match="only 1 per round"):
        apply(state, a.ExpandLab(seat=seat))
    assert not _expand_options(state, seat)
    state.researcher(seat).lab_expanded = True
    state = to_phase(state, Phase.HIRING)
    assert not state.researcher(seat).lab_expanded


def test_needs_a_staff_member_on_experimentation():
    """Lab capacity: only a player who has at least one staff member allocated to experimentation."""
    state = _experimentation(k=1, n=2)
    seat = state.current
    state.researcher(seat).staff = {}
    with pytest.raises(IllegalAction, match="staff on experimentation"):
        apply(state, a.ExpandLab(seat=seat))
    assert not _expand_options(state, seat)


def test_not_outside_the_experimentation_phase():
    state = game()
    with pytest.raises(IllegalAction):
        apply(state, a.ExpandLab(seat=0))


def test_each_step_costs_more_up_to_the_maximum():
    """Lab capacity: the cost increases with the lab size, up to [starting_lab_capacity_advanced]
    plus the number of steps in the cost list."""
    state = _experimentation(k=1)
    seat = state.current
    r = state.researcher(seat)
    for step, cost in enumerate(COSTS):
        state = state.clone()
        state.researcher(seat).lab_expanded = False
        state.researcher(seat).money = 100
        state = do(state, a.ExpandLab(seat=seat))
        assert state.researcher(seat).money == 100 - cost
        assert state.researcher(seat).lab_capacity == r.lab_capacity + step + 1
    state = state.clone()
    state.researcher(seat).lab_expanded = False
    with pytest.raises(IllegalAction, match="maximum"):
        apply(state, a.ExpandLab(seat=seat))


def test_cannot_pay_more_than_the_money():
    state = _experimentation(k=1)
    seat = state.current
    state.researcher(seat).money = COSTS[0] - 1
    with pytest.raises(IllegalAction, match="costs"):
        apply(state, a.ExpandLab(seat=seat))


def test_a_game_saved_before_lab_capacity_cannot_increase_it():
    state = _experimentation(k=1)
    seat = state.current
    state.researcher(seat).lab_capacity = None
    assert not _expand_options(state, seat)
    with pytest.raises(IllegalAction, match="before lab capacity"):
        apply(state, a.ExpandLab(seat=seat))


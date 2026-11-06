"""Rulebook "Development phase": "Formulating a theory", "Developing methods"; specification 5.2
(Development is simultaneous secret) and 5.7 (at 0 academic credit every usable staff member is used)."""

import pytest

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply
from nv_core.state import Phase
from tests.core.engine_helpers import do, game, to_phase


def _development(k=1):
    return to_phase(game(), Phase.DEVELOPMENT, {0: {"development": k}, 1: {"development": 1}})


def test_theory_needs_at_least_one_world_outcome():
    """Formulating a theory: at least one input parameter and at least one world outcome."""
    state = _development()
    with pytest.raises(IllegalAction):
        apply(state, a.FormulateTheory(seat=0, inputs={"IP1": "a"}, outcomes={}))


def test_theory_states_must_exist_in_the_scenario():
    """Formulating a theory: cards come from the State Cards, so only the scenario's states can be used."""
    state = _development()
    with pytest.raises(IllegalAction):
        apply(state, a.FormulateTheory(seat=0, inputs={"IP1": "c"}, outcomes={"WO1": "up"}))


def test_theory_may_specify_every_input_parameter():
    """Formulating a theory: up to the number of input parameters in the scenario."""
    state = _development()
    state = do(state, a.FormulateTheory(seat=0, inputs={"IP1": "a", "IP2": "x", "IP3": "p"}, outcomes={"WO1": "up"}))
    state = do(state, a.CommitPhase(seat=0), a.CommitPhase(seat=1))
    assert state.researcher(0).ideas[-1].inputs == {"IP1": "a", "IP2": "x", "IP3": "p"}


def test_methods_are_specific_to_an_input_parameter():
    """Developing methods: methods are specific to one of the Input Parameters (not a world outcome)."""
    state = _development()
    with pytest.raises(IllegalAction):
        apply(state, a.DevelopMethod(seat=0, parameter="WO1"))


def test_development_is_secret_until_commit_and_can_be_cancelled():
    """Specification 5.2 and 5.3: Development is simultaneous secret; choices stay editable until commit."""
    state = _development(k=1)
    ideas_before = len(state.researcher(0).ideas)
    state = do(state, a.FormulateTheory(seat=0, inputs={"IP1": "a"}, outcomes={"WO1": "up"}))
    with pytest.raises(IllegalAction):  # the only development staff member is taken
        apply(state, a.DevelopMethod(seat=0, parameter="IP2"))
    state = do(state, a.CancelDevelopment(seat=0, index=0), a.DevelopMethod(seat=0, parameter="IP2"))
    assert len(state.researcher(0).ideas) == ideas_before
    state = do(state, a.CommitPhase(seat=0), a.CommitPhase(seat=1))
    new = state.researcher(0).ideas[ideas_before:]
    assert [(i.kind, i.parameter) for i in new] == [("method", "IP2")]


def test_at_zero_credit_development_staff_must_be_used():
    """Academic credit rules (specification 5.7): at 0 academic credit a researcher must use every
    staff member that can still be used."""
    state = _development()
    state.researcher(0).credit = 0
    with pytest.raises(IllegalAction):
        apply(state, a.CommitPhase(seat=0))
    state = do(state, a.DevelopMethod(seat=0, parameter="IP3"))
    apply(state, a.CommitPhase(seat=0))

"""Rulebook "Probe time", "Observation and prediction phase": "Revealing input parameters" and
"Recording observations"; specification 5.7 (automatic recording, rebuilding the decks)."""

from collections import Counter

import pytest

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply
from nv_core.engine.context import Ctx
from nv_core.engine.observation import deal_probes
from nv_core.state import Phase
from tests.core.engine_helpers import do, game, settings, tiny_world, to_phase

S = settings()


def _state_of(card):
    return getattr(card, "state", card)


# Probe time ------------------------------------------------------------------------------
def test_probe_time_ties_in_credit_follow_turn_order():
    """Probe time: highest academic credit chooses first, with turn order as tiebreaker."""
    state = game(n=3)
    state = to_phase(state, Phase.EXPERIMENTATION, {s: {"experimentation": 1} for s in range(3)})
    for r in state.researchers:
        r.credit = 12
    expected = state.turn_order()
    order = []
    while state.phase in (Phase.EXPERIMENTATION, Phase.PROBE_TIME):
        if state.phase == Phase.PROBE_TIME:
            order.append(state.current)
            free = next(p.index for p in state.probes if p.probe_time is None)
            state = do(state, a.ClaimProbeTime(seat=state.current, probe=free))
        else:
            state = do(state, a.Pass(seat=state.current))
    assert order == expected


def test_an_occupied_probe_cannot_be_claimed():
    """Probe time: only one Researcher's marker per Probe."""
    state = game()
    state = to_phase(state, Phase.PROBE_TIME, {s: {"experimentation": 1} for s in range(2)})
    first = state.current
    state = do(state, a.ClaimProbeTime(seat=first, probe=0))
    assert state.phase == Phase.PROBE_TIME and state.current != first
    with pytest.raises(IllegalAction):
        apply(state, a.ClaimProbeTime(seat=state.current, probe=0))


# Recording observations ------------------------------------------------------------------
def test_probe_time_holder_records_the_full_visible_column():
    """Recording observations (and specification 5.7): the researcher with Probe time always records
    the Probe; the record is the full column as shown, blanks and noise included, put in Fresh."""
    state = game()
    allocation = {"data_collection": 1, "development": 1}
    state = to_phase(state, Phase.PREDICTION, {0: allocation, 1: allocation})
    holders = {p.index: p.probe_time for p in state.probes if p.probe_time is not None}
    assert sorted(holders.values()) == [0, 1]
    shown = {
        p.index: {v: c.state for v, c in p.readings.items()} | {v: c.state for v, c in p.outcomes.items()}
        for p in state.probes
    }
    while state.phase in (Phase.PREDICTION, Phase.REVEAL, Phase.SCORING_ORDER) and state.waiting:
        state = do(state, a.CommitPhase(seat=state.waiting[0]))
    assert state.phase == Phase.DEVELOPMENT
    world = tiny_world()
    for probe, seat in holders.items():
        records = [o for o in state.researcher(seat).fresh.observations if o.probe == probe]
        assert len(records) == 1
        cards = records[0].cards
        assert len(cards) == len(world.input_ids) + len(world.outcome_ids)
        assert {c.var: c.state for c in cards} == shown[probe]


# Revealing input parameters: the decks -----------------------------------------------------
def test_input_parameter_decks_have_equal_state_proportions():
    """Pieces: each Input Parameter Deck has [input_parameter_deck_size] cards in equal proportions."""
    state = game()
    world = tiny_world()
    for var in world.input_parameters:
        deck = state.input_decks[var.id]
        assert len(deck) == S.input_parameter_deck_size
        counts = Counter(_state_of(c) for c in deck)
        assert set(counts) == set(var.states)
        assert set(counts.values()) == {S.input_parameter_deck_size // len(var.states)}


def test_exhausted_probe_deck_with_small_discard_pile_is_rebuilt_in_full():
    """Revealing input parameters (specification 5.7): with fewer than [probe_deck_min_rebuild_stacks]
    stacks in the discard pile, the full Probe deck is rebuilt and reshuffled."""
    state = game()
    if S.probe_deck_min_rebuild_stacks <= len(state.probes):
        pytest.skip("the discard pile could already hold enough stacks")
    state.probe_deck = state.probe_deck[:0]
    deal_probes(Ctx(state))
    full = S.probe_deck_copies * len(tiny_world().rows)
    assert len(state.probe_deck) == full - len(state.probes)
    assert all(p.stack is not None for p in state.probes)


def test_exhausted_input_deck_with_empty_discard_pile_is_rebuilt():
    """Revealing input parameters (specification 5.7): an exhausted Input Parameter Deck with an
    empty discard pile is replaced by a fresh full deck (here: noise cards for one level 1 sensor)."""
    state = game()
    state.input_decks["IP3"] = state.input_decks["IP3"][:0]
    if "IP3" in state.input_discards:
        state.input_discards["IP3"] = state.input_discards["IP3"][:0]
    state.probes[0].sensors = {"IP3": 1}
    deal_probes(Ctx(state))
    assert len(state.input_decks["IP3"]) == S.input_parameter_deck_size - S.probe_fake_input_deck_size
    assert state.probes[0].readings["IP3"].state is not None

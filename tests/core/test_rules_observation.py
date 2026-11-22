"""Rulebook "Probe time", "Observation and prediction phase": "Revealing input parameters" and
"Recording observations"; specification 5.7 (rebuilding the decks)."""

from collections import Counter

import pytest

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply
from nv_core.engine.context import Ctx
from nv_core.engine.experimentation import start_probe_time
from nv_core.engine.observation import deal_probes
from nv_core.state import Phase
from tests.core.engine_helpers import do, game, settings, tiny_world, to_phase

S = settings()


def _state_of(card):
    return getattr(card, "state", card)


# Probe time ------------------------------------------------------------------------------
def _claim(state, hot_topic):
    state.hot_topic = hot_topic
    start_probe_time(Ctx(state))
    return [p.probe_time for p in state.probes]


def test_probe_time_ties_in_credit_follow_turn_order():
    """Claiming Probe time: highest academic credit first, with turn order as tiebreaker; the Probe
    with the Hot topic first when unoccupied, then the next ones."""
    state = game(n=3)
    for r in state.researchers:
        r.credit = 12
    first, second, third = state.turn_order()
    claims = _claim(state, 1)
    assert claims[1] == first and claims[2] == second and claims[3] == third and claims[0] is None


def test_probe_time_wraps_round_after_the_last_probe():
    state = game(n=2)  # three Probes
    state.researcher(0).credit, state.researcher(1).credit = 10, 20
    assert _claim(state, 2) == [0, None, 1]


def test_in_the_simplified_game_p1_counts_as_the_hot_topic():
    state = game(n=2, mode="simplified")
    state.researcher(0).credit, state.researcher(1).credit = 10, 20
    assert _claim(state, None) == [1, 0, None]


def test_more_researchers_than_free_probes_leaves_the_last_without_probe_time():
    state = game(n=3)  # four Probes
    for p in state.probes[:3]:
        p.probe_time, p.probe_time_from_sensor = 2, True
    state.researcher(0).credit, state.researcher(1).credit = 1, 2
    assert _claim(state, 0) == [2, 2, 2, 1]  # researcher 0, with less credit, gets none


# Recording observations ------------------------------------------------------------------
def test_probe_time_holder_records_the_full_visible_column():
    """Recording observations: the researcher with Probe time always records
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
        records = [o for o in state.researcher(seat).records.observations if o.probe == probe]
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

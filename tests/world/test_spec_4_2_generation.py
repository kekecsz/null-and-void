"""Specification section 4.2, "Generating the World Table" (one try, no screening).

Expectations are derived from the Venus scenario's YAML block, or from tmp copies of it with one
setting changed.
"""

import copy
import itertools
import math
from collections import Counter

import pytest

from nv_world.generate import build_world
from nv_world.scenario import load_scenario

from tests.world.conftest import (
    VENUS,
    interactions_signature,
    main_effects_signature,
    rows_signature,
    venus_data,
    world_signature,
    write_scenario,
)

SEEDS = [0, 1, 17]


@pytest.fixture(scope="module")
def venus():
    return load_scenario(VENUS)


@pytest.fixture(scope="module")
def venus_worlds(venus):
    return {seed: build_world(venus, seed) for seed in SEEDS}


def _venus_variant(tmp_path, **effect_model_changes):
    data = copy.deepcopy(venus_data())
    data["effect_model"].update(effect_model_changes)
    return data, load_scenario(write_scenario(tmp_path, data))


def _signed_size(effect: str, sizes: dict) -> float:
    sign = {"+": 1, "-": -1}[effect[0]]
    return sign * sizes[effect[1:]]


def _expected_probabilities(data: dict, world, row) -> dict:
    """Softmax of the scores of 4.2 step 3, recomputed from the recorded effects."""
    sizes = data["effect_model"]["effect_sizes_logit"]
    result = {}
    for outcome in data["world_outcomes"]:
        scores = {}
        for state in outcome["states"]:
            score = 0.0
            for m in world.main_effects:
                if (m.outcome, m.outcome_state) == (outcome["id"], state) and row.inputs[m.input] == m.input_state:
                    score += _signed_size(m.effect, sizes)
            for i in world.interactions:
                if ((i.outcome, i.outcome_state) == (outcome["id"], state)
                        and row.inputs[i.input_a] == i.state_a and row.inputs[i.input_b] == i.state_b):
                    score += i.sign * sizes[i.size]
            scores[state] = score
        top = max(scores.values())
        exps = {s: math.exp(v - top) for s, v in scores.items()}
        total = sum(exps.values())
        result[outcome["id"]] = {s: e / total for s, e in exps.items()}
    return result


def _input_states(data: dict) -> set:
    return {(p["id"], s) for p in data["input_parameters"] for s in p["states"]}


# --- what the world records ---------------------------------------------------------------

def test_world_records_seed_and_scenario(venus, venus_worlds):
    """4.2 Generating the World Table, step 4 (Record): the seed and the scenario."""
    for seed, world in venus_worlds.items():
        assert world.scenario_id == venus.id
        assert world.yaml_hash == venus.yaml_hash
        assert world.seed == seed
        assert world.requested_seed == seed
        assert world.screening is None


# --- step 1: main effects -----------------------------------------------------------------

def _check_main_effects(data, world, reference: bool):
    urn = sorted(data["effect_model"]["main_effect_urn"])
    valid_inputs = _input_states(data)
    by_state = {}
    for m in world.main_effects:
        assert (m.input, m.input_state) in valid_inputs, m
        by_state.setdefault((m.outcome, m.outcome_state), []).append(m)
    for outcome in data["world_outcomes"]:
        for position, state in enumerate(outcome["states"]):
            effects = by_state.pop((outcome["id"], state), [])
            if reference and position == 0:
                assert effects == [], f"reference state {state!r} got main effects"
                continue
            assert sorted(m.effect for m in effects) == urn, (outcome["id"], state)
            # One value per input state.
            targets = [(m.input, m.input_state) for m in effects]
            assert len(set(targets)) == len(targets), (outcome["id"], state)
    assert by_state == {}, f"main effects on unknown outcome states: {list(by_state)}"


def test_main_effects_are_the_urn_for_every_outcome_state(venus_worlds):
    """4.2 Generating the World Table, step 1 (Main effects): each outcome state draws the urn."""
    data = venus_data()
    assert data["effect_model"]["reference_state_per_outcome"] is False
    for world in venus_worlds.values():
        _check_main_effects(data, world, reference=False)


def test_reference_state_gets_no_effects(tmp_path):
    """4.2 Generating the World Table, step 1: the first listed state is the reference."""
    data, scenario = _venus_variant(tmp_path, reference_state_per_outcome=True)
    for seed in (0, 1):
        world = build_world(scenario, seed)
        _check_main_effects(data, world, reference=True)
        references = {(o["id"], o["states"][0]) for o in data["world_outcomes"]}
        for i in world.interactions:
            assert (i.outcome, i.outcome_state) not in references, i


def test_main_effects_are_shuffled_across_input_states(venus_worlds):
    """4.2 Generating the World Table, step 1: the padded urn is shuffled for each outcome state."""
    placements = set()
    for world in venus_worlds.values():
        placements.add(tuple(sorted((m.outcome, m.outcome_state, m.input, m.input_state, m.effect)
                                    for m in world.main_effects)))
    assert len(placements) == len(venus_worlds)


# --- step 2: interactions -------------------------------------------------------------

def _check_interactions(data, world, reference: bool = False):
    model = data["effect_model"]
    assert len(world.interactions) == len(model["interactions"])
    assert sorted(i.size for i in world.interactions) == sorted(model["interactions"])
    valid_inputs = _input_states(data)
    outcome_states = {
        (o["id"], s) for o in data["world_outcomes"]
        for k, s in enumerate(o["states"]) if not (reference and k == 0)
    }
    per_state = Counter()
    for i in world.interactions:
        assert i.input_a != i.input_b, i
        assert (i.input_a, i.state_a) in valid_inputs, i
        assert (i.input_b, i.state_b) in valid_inputs, i
        assert (i.outcome, i.outcome_state) in outcome_states, i
        assert i.size in model["effect_sizes_logit"], i
        assert i.sign in (1, -1), i
        per_state[(i.outcome, i.outcome_state)] += 1
    assert max(per_state.values(), default=0) <= model["max_interactions_per_outcome_state"]


def test_interactions_follow_the_effect_model(venus_worlds):
    """4.2 Generating the World Table, step 2 (Interactions)."""
    data = venus_data()
    for world in venus_worlds.values():
        _check_interactions(data, world)


def test_random_interaction_signs_take_both_values(venus):
    """4.2 Generating the World Table, step 2: interaction_sign random gives either sign."""
    assert venus_data()["effect_model"]["interaction_sign"] == "random"
    signs = Counter(i.sign for seed in range(10) for i in build_world(venus, seed).interactions)
    assert set(signs) == {1, -1}, signs


@pytest.mark.parametrize("setting, sign", [("positive", 1), ("negative", -1)])
def test_fixed_interaction_sign(tmp_path, setting, sign):
    """4.2 Generating the World Table, step 2: the sign follows interaction_sign."""
    data, scenario = _venus_variant(tmp_path, interaction_sign=setting)
    for seed in (0, 1, 2):
        world = build_world(scenario, seed)
        _check_interactions(data, world)
        assert all(i.sign == sign for i in world.interactions)


def test_interactions_spread_over_outcome_states(tmp_path):
    """4.2 Generating the World Table, step 2: only states with room left can be picked."""
    data = copy.deepcopy(venus_data())
    room = sum(len(o["states"]) for o in data["world_outcomes"])
    # As many interactions as there is room for at one per outcome state: every state gets one.
    data["effect_model"]["interactions"] = [next(iter(data["effect_model"]["effect_sizes_logit"]))] * room
    data["effect_model"]["max_interactions_per_outcome_state"] = 1
    scenario = load_scenario(write_scenario(tmp_path, data))
    world = build_world(scenario, 3)
    _check_interactions(data, world)
    assert len({(i.outcome, i.outcome_state) for i in world.interactions}) == room


# --- step 3: rows -----------------------------------------------------------------------

def test_rows_are_every_input_combination_in_order(venus_worlds):
    """4.2 Generating the World Table, step 3 (Rows): one row per input combination."""
    data = venus_data()
    ids = [p["id"] for p in data["input_parameters"]]
    expected = list(itertools.product(*[p["states"] for p in data["input_parameters"]]))
    outcome_ids = {o["id"] for o in data["world_outcomes"]}
    for world in venus_worlds.values():
        assert [tuple(r.inputs[i] for i in ids) for r in world.rows] == expected
        for row in world.rows:
            assert set(row.inputs) == set(ids)
            assert set(row.outcomes) == outcome_ids


def test_realised_outcomes_are_states_of_their_outcome(venus_worlds):
    """4.2 Generating the World Table, step 3: each outcome is realised as one of its states."""
    data = venus_data()
    states = {o["id"]: o["states"] for o in data["world_outcomes"]}
    for world in venus_worlds.values():
        for row in world.rows:
            for outcome, state in row.outcomes.items():
                assert state in states[outcome], (outcome, state)
                assert row.probabilities[outcome][state] > 0


def test_probabilities_are_softmax_of_scores(venus_worlds):
    """4.2 Generating the World Table, step 3: scores from main effects and interactions, softmax."""
    data = venus_data()
    for world in venus_worlds.values():
        for row in world.rows:
            expected = _expected_probabilities(data, world, row)
            assert set(row.probabilities) == set(expected)
            for outcome, states in expected.items():
                assert set(row.probabilities[outcome]) == set(states)
                for state, p in states.items():
                    assert row.probabilities[outcome][state] == pytest.approx(p, abs=1e-12), (outcome, state)
                assert sum(row.probabilities[outcome].values()) == pytest.approx(1.0, abs=1e-12)


def test_probabilities_with_a_reference_state(tmp_path):
    """4.2 Generating the World Table, step 3: the reference state scores 0."""
    data, scenario = _venus_variant(tmp_path, reference_state_per_outcome=True, interaction_sign="negative")
    world = build_world(scenario, 5)
    for row in world.rows:
        expected = _expected_probabilities(data, world, row)
        for outcome, states in expected.items():
            for state, p in states.items():
                assert row.probabilities[outcome][state] == pytest.approx(p, abs=1e-12)


def test_rows_with_impossible_effects_are_realised_by_their_probabilities(tmp_path):
    """4.2 Generating the World Table, step 3: outcomes are drawn from the softmax probabilities."""
    data = copy.deepcopy(venus_data())
    # Huge effects make nearly every row's probability 0 or 1 for each state.
    data["effect_model"]["effect_sizes_logit"] = {k: 60.0 for k in data["effect_model"]["effect_sizes_logit"]}
    scenario = load_scenario(write_scenario(tmp_path, data))
    world = build_world(scenario, 11)
    for row in world.rows:
        for outcome, state in row.outcomes.items():
            # A state with probability below 1e-12 is never realised in a fair draw.
            assert row.probabilities[outcome][state] > 1e-12, (row.inputs, outcome, state)


# --- determinism (Milestone 1) ----------------------------------------------------------

def test_same_scenario_and_seed_give_the_same_world(venus_worlds):
    """13. Milestones (1): the same scenario and seed always give the same World Table."""
    reloaded = load_scenario(VENUS)
    for seed, world in venus_worlds.items():
        again = build_world(reloaded, seed)
        assert world_signature(again) == world_signature(world)


def test_different_seeds_give_different_worlds(venus_worlds):
    """4.2 Generating the World Table: the seed drives every random choice."""
    signatures = [
        (main_effects_signature(w), interactions_signature(w), rows_signature(w.rows))
        for w in venus_worlds.values()
    ]
    for a, b in itertools.combinations(signatures, 2):
        assert a != b
    tables = [rows_signature(w.rows) for w in venus_worlds.values()]
    for a, b in itertools.combinations(tables, 2):
        assert a != b

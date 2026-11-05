"""Specification section 4.4, "World files"."""

import json
from fractions import Fraction

import pytest

from nv_world.generate import build_world, generate_world
from nv_world.scenario import load_scenario
from nv_world.screening import screen
from nv_world.worldfile import load_world, save_world, scenario_changed

from tests.world.conftest import (
    VENUS,
    interactions_signature,
    main_effects_signature,
    rows_signature,
    screening_signature,
    tiny_data,
    two_outcome_data,
    venus_data,
    with_criteria,
    write_scenario,
)


@pytest.fixture
def tiny_world(tmp_path):
    # Two outcomes and IP2 weights, so the screening report has something in every field;
    # min_accuracy 0.6 keeps some theories out of the Nobel-grade list.
    data = two_outcome_data()
    data["input_parameters"][1]["weights"] = [2, 1, 1]
    data = with_criteria(data, nobel_min_accuracy=0.6, max_generation_tries=5)
    scenario = load_scenario(write_scenario(tmp_path, data))
    return scenario, generate_world(scenario, 3)


def test_round_trip(tmp_path, tiny_world):
    """4.4 World files: the world file holds everything the world records."""
    _, world = tiny_world
    path = tmp_path / "world.json"
    save_world(world, path)
    loaded = load_world(path)
    assert loaded.scenario_id == world.scenario_id
    assert loaded.yaml_hash == world.yaml_hash
    assert loaded.requested_seed == world.requested_seed
    assert loaded.seed == world.seed
    assert loaded.tries == world.tries
    assert main_effects_signature(loaded) == main_effects_signature(world)
    assert interactions_signature(loaded) == interactions_signature(world)
    assert rows_signature(loaded.rows) == rows_signature(world.rows)
    for before, after in zip(world.rows, loaded.rows):
        assert set(after.probabilities) == set(before.probabilities)
        for outcome, states in before.probabilities.items():
            assert after.probabilities[outcome] == pytest.approx(states, rel=1e-12, abs=1e-15)
    assert screening_signature(loaded.screening) == screening_signature(world.screening)


def test_saved_twice_gives_the_same_world(tmp_path, tiny_world):
    """4.4 World files: loading and saving again loses nothing."""
    _, world = tiny_world
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    save_world(world, first)
    save_world(load_world(first), second)
    assert json.loads(first.read_text(encoding="utf-8")) == json.loads(second.read_text(encoding="utf-8"))


def test_file_is_json_with_seeds_and_no_decks(tmp_path, tiny_world):
    """4.4 World files: a JSON file that holds no decks."""
    _, world = tiny_world
    path = tmp_path / "world.json"
    save_world(world, path)
    content = json.loads(path.read_text(encoding="utf-8"))

    def keys(value):
        if isinstance(value, dict):
            for k, v in value.items():
                yield str(k)
                yield from keys(v)
        elif isinstance(value, list):
            for v in value:
                yield from keys(v)

    deck_keys = [k for k in keys(content) if "deck" in k.lower()]
    assert deck_keys == [], f"world file holds decks: {deck_keys}"


# --- what the JSON holds, checked by value ----------------------------------------------------

def _containers(value):
    """Every dict and list in a JSON value, the value itself included."""
    if isinstance(value, (dict, list)):
        yield value
        for child in (value.values() if isinstance(value, dict) else value):
            yield from _containers(child)


def _leaves(value) -> list:
    """Every scalar in a JSON value (dict keys excluded)."""
    if isinstance(value, dict):
        return [leaf for child in value.values() for leaf in _leaves(child)]
    if isinstance(value, list):
        return [leaf for child in value for leaf in _leaves(child)]
    return [value]


def _items(value):
    """Every (key, value) pair of every dict in a JSON value."""
    for container in _containers(value):
        if isinstance(container, dict):
            yield from container.items()


def _as_number(value):
    """A share as written in the file (number or text such as "1/2" or "0.5"), as a float."""
    if isinstance(value, bool):
        return None
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return None


@pytest.fixture
def retried_world(tmp_path):
    """A saved world whose accepted seed differs from the requested one.

    Tiny two-outcome scenario (unweighted, 6 rows): max_base_rate 0.5 passes only when each
    outcome splits 3 to 3, so many seeds fail. The requested seed is chosen (by building and
    screening single tries) so that its first try fails, which makes tries > 1 certain.
    """
    data = with_criteria(two_outcome_data(), max_base_rate=0.5, nobel_min_accuracy=0.6,
                         max_generation_tries=300)
    scenario = load_scenario(write_scenario(tmp_path, data))
    requested = next(s for s in range(7001, 7101) if not screen(scenario, build_world(scenario, s).rows).passed)
    world = generate_world(scenario, requested)
    path = tmp_path / "world.json"
    save_world(world, path)
    return world, json.loads(path.read_text(encoding="utf-8"))


def test_file_holds_scenario_id_hash_seeds_and_tries(retried_world):
    """4.4 World files: the scenario id, the hash, the requested and accepted seeds, the number of tries."""
    world, content = retried_world
    assert world.tries > 1 and world.seed != world.requested_seed
    leaves = _leaves(content)
    assert world.scenario_id in leaves
    assert world.yaml_hash in leaves, "the yaml hash is not stored as a value"
    assert world.requested_seed in leaves, "the requested seed is not stored"
    assert world.seed in leaves, "the accepted seed is not stored"
    # The number of tries is a small number that may appear elsewhere too: look for it under
    # a key that names it.
    tries_fields = [(k, v) for k, v in _items(content) if "tr" in str(k).lower() and v == world.tries]
    assert tries_fields, "no field named after the tries holds the number of tries"


def test_file_holds_the_effect_assignments(retried_world):
    """4.4 World files: the effect assignments."""
    world, content = retried_world
    records = [c for c in _containers(content) if isinstance(c, dict)]
    for m in world.main_effects:
        wanted = [m.outcome, m.outcome_state, m.input, m.input_state, m.effect]
        assert any(all(v in list(r.values()) for v in wanted) for r in records), wanted


def test_file_holds_the_interactions(retried_world):
    """4.4 World files: the interactions (outcome state, pair of input states, size, sign)."""
    world, content = retried_world
    assert world.interactions, "the fixture has interactions"
    records = [c for c in _containers(content) if isinstance(c, dict)]
    for i in world.interactions:
        wanted = [i.outcome, i.outcome_state, i.input_a, i.state_a, i.input_b, i.state_b, i.size]
        matches = [r for r in records if all(v in _leaves(r) for v in wanted)
                   and len(_leaves(r)) <= len(wanted) + 3]
        assert matches, wanted


def test_file_holds_the_world_table(retried_world):
    """4.4 World files: the World Table, row by row in table order."""
    world, content = retried_world
    n = len(world.rows)

    def holds_rows(candidate):
        return (isinstance(candidate, list) and len(candidate) == n
                and all(set(row.inputs.values()) | set(row.outcomes.values()) <= set(_leaves(entry))
                        for row, entry in zip(world.rows, candidate)))

    assert any(holds_rows(c) for c in _containers(content)), "no list of rows matches the World Table"


def test_file_holds_the_screening_report(retried_world):
    """4.4 World files: the screening report (base rates and the Nobel-grade counts)."""
    world, content = retried_world
    report = world.screening
    dicts = [c for c in _containers(content) if isinstance(c, dict)]
    # The Nobel-grade counts, under their names.
    assert any(all(d.get(name) == count for name, count in report.nobel_counts.items()) for d in dicts), (
        dict(report.nobel_counts))

    # The base rates: a mapping outcome id -> state -> share.
    def holds_base_rates(d):
        if set(d) != set(report.base_rates):
            return False
        for outcome, states in report.base_rates.items():
            stored = d[outcome]
            if not isinstance(stored, dict) or set(stored) != set(states):
                return False
            for state, rate in states.items():
                number = _as_number(stored[state])
                if number is None or number != pytest.approx(float(rate), abs=1e-9):
                    return False
        return True

    assert any(holds_base_rates(d) for d in dicts), "no mapping in the file holds the base rates"


def test_scenario_unchanged(tiny_world):
    """4.4 World files: the hash lets the software warn when a scenario's data was edited."""
    scenario, world = tiny_world
    assert scenario_changed(world, scenario) is False


def test_scenario_changed_after_a_value_edit(tmp_path):
    """4.4 World files: editing a value changes the hash; comments and layout do not."""
    data = with_criteria(tiny_data(), max_generation_tries=5)
    original = load_scenario(write_scenario(tmp_path, data, "original.md"))
    world = generate_world(original, 1)

    relaid = load_scenario(write_scenario(tmp_path, data, "relaid.md", flow_style=True, comments=True,
                                          story="A different story."))
    assert scenario_changed(world, relaid) is False

    edited_data = with_criteria(data)
    edited_data["effect_model"]["effect_sizes_logit"]["large"] = 2.5
    edited = load_scenario(write_scenario(tmp_path, edited_data, "edited.md"))
    assert scenario_changed(world, edited) is True


def test_scenario_changed_after_a_saved_round_trip(tmp_path):
    """4.4 World files: the hash is stored in the file."""
    data = with_criteria(tiny_data(), max_generation_tries=5)
    scenario = load_scenario(write_scenario(tmp_path, data, "a.md"))
    path = tmp_path / "world.json"
    save_world(generate_world(scenario, 2), path)
    world = load_world(path)
    assert scenario_changed(world, scenario) is False
    data["world_outcomes"][0]["states"] = ["hit", "missed"]
    assert scenario_changed(world, load_scenario(write_scenario(tmp_path, data, "b.md"))) is True


def test_copy_of_venus_with_an_edited_value(tmp_path):
    """4.4 World files: a copy of a real scenario file with one value edited is detected."""
    venus = load_scenario(VENUS)
    world = build_world(venus, 0)
    copy_path = tmp_path / "scenario.md"
    copy_path.write_text(VENUS.read_text(encoding="utf-8"), encoding="utf-8")
    assert scenario_changed(world, load_scenario(copy_path)) is False

    text = VENUS.read_text(encoding="utf-8")
    sizes = venus_data()["effect_model"]["effect_sizes_logit"]
    name, value = next(iter(sizes.items()))
    old_line = f"{name}: {value}"
    assert old_line in text, old_line
    copy_path.write_text(text.replace(old_line, f"{name}: {value + 0.25}", 1), encoding="utf-8")
    assert scenario_changed(world, load_scenario(copy_path)) is True

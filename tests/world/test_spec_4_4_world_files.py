"""Specification section 4.4, "World files"."""

import json

import pytest

from nv_world.generate import build_world, generate_world
from nv_world.scenario import load_scenario
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

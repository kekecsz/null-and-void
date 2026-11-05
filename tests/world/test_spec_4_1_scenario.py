"""Specification section 4.1, "Reading the scenario file".

The Venus scenario's expectations are read from its own YAML block; the error cases use the
hand-made tiny scenario from conftest.py.
"""

import copy
from fractions import Fraction

import pytest
import yaml

from nv_core.paths import PARAMETER_DEFAULTS, SCENARIOS_DIR
from nv_core.settings import SettingsError, load_settings
from nv_world.scenario import ScenarioError, load_scenario

from tests.world.conftest import (
    VENUS,
    scenario_markdown,
    story_section,
    tiny_data,
    venus_data,
    write_scenario,
    yaml_block_data,
)


def _exact(value) -> Fraction:
    """The decimal as written in the YAML, as an exact fraction (0.90 -> 9/10)."""
    return Fraction(str(value))


# --- the Venus scenario ----------------------------------------------------------------

@pytest.mark.parametrize("path", sorted(SCENARIOS_DIR.glob("*/scenario.md")), ids=lambda p: p.parent.name)
def test_every_scenario_file_loads(path):
    """4.1 Reading the scenario file: every scenario file passes its schema (also section 13)."""
    scenario = load_scenario(path)
    assert scenario.id == yaml_block_data(path)["scenario"]["id"]
    # The scenario folder is named after the scenario id (scenarios/<id>/scenario.md, section 1).
    assert path.parent.name == scenario.id


def test_venus_identity():
    """4.1 Reading the scenario file: the first fenced yaml block is read."""
    data = venus_data()
    scenario = load_scenario(VENUS)
    assert scenario.id == data["scenario"]["id"]
    assert scenario.title == data["scenario"]["title"]
    assert scenario.parameter_overrides == (data.get("parameter_overrides") or {})


@pytest.mark.parametrize("kind", ["input_parameters", "world_outcomes"])
def test_venus_variables_match_yaml(kind):
    """4.1 Reading the scenario file: ids, names and states in YAML order."""
    expected = venus_data()[kind]
    variables = getattr(load_scenario(VENUS), kind)
    assert len(variables) == len(expected)
    for variable, raw in zip(variables, expected):
        assert variable.id == raw["id"]
        assert variable.name == raw["name"]
        assert list(variable.states) == raw["states"]
        if "weights" not in raw:
            n = len(raw["states"])
            assert list(variable.weights) == [Fraction(1, n)] * n


def test_venus_effect_model_matches_yaml():
    """4.1 Reading the scenario file: the effect model is read as written."""
    raw = venus_data()["effect_model"]
    model = load_scenario(VENUS).effect_model
    for key, value in raw.items():
        actual = getattr(model, key)
        if isinstance(value, dict):
            assert dict(actual) == value, key
        elif isinstance(value, list):
            assert list(actual) == value, key
        else:
            assert actual == value, key


def test_venus_acceptance_criteria_match_yaml():
    """4.1 Reading the scenario file; 4.3 Screening: thresholds are exact fractions."""
    raw = venus_data()["acceptance_criteria"]
    criteria = load_scenario(VENUS).acceptance_criteria
    for key in ("max_base_rate", "max_one_input_theory_accuracy"):
        assert getattr(criteria, key) == _exact(raw[key]), key
        assert isinstance(getattr(criteria, key), Fraction), key
    assert criteria.max_generation_tries == raw["max_generation_tries"]
    nobel_raw = raw["nobel_grade"]
    nobel = criteria.nobel_grade
    assert nobel.min_accuracy == _exact(nobel_raw["min_accuracy"])
    assert isinstance(nobel.min_accuracy, Fraction)
    for key in ("max_input_parameters", "count", "min_count", "max_count"):
        assert getattr(nobel, key) == nobel_raw[key], key


def test_decimal_thresholds_are_converted_exactly(tmp_path):
    """4.3 Screening (Comparisons): shares are compared as exact fractions."""
    data = tiny_data()
    data["acceptance_criteria"]["max_base_rate"] = 0.7
    data["acceptance_criteria"]["max_one_input_theory_accuracy"] = 0.85
    data["acceptance_criteria"]["nobel_grade"]["min_accuracy"] = 0.9
    criteria = load_scenario(write_scenario(tmp_path, data)).acceptance_criteria
    assert criteria.max_base_rate == Fraction(7, 10)
    assert criteria.max_one_input_theory_accuracy == Fraction(17, 20)
    assert criteria.nobel_grade.min_accuracy == Fraction(9, 10)


def test_venus_settings_are_defaults_plus_overrides():
    """4.1 Reading the scenario file; 11. Configuration: defaults, then parameter_overrides."""
    overrides = venus_data().get("parameter_overrides") or {}
    scenario = load_scenario(VENUS)
    assert scenario.settings.model_dump() == load_settings(overrides).model_dump()


def test_venus_story_is_the_story_section():
    """4.1 Reading the scenario file: the Story section is passed as text."""
    story = load_scenario(VENUS).story
    section = story_section(VENUS)
    for line in section.splitlines():
        if line.strip():
            assert line.strip().strip("*") in story
    assert "## Story" not in story
    assert "```" not in story
    assert "input_parameters" not in story


def test_story_of_a_tmp_scenario(tmp_path):
    """4.1 Reading the scenario file: the Story section is passed as text."""
    path = write_scenario(tmp_path, tiny_data(), story="First paragraph.\n\nSecond paragraph.")
    story = load_scenario(path).story
    assert "First paragraph." in story
    assert "Second paragraph." in story
    assert "Intro text" not in story
    assert "Text after the data block" not in story
    assert "## " not in story


def test_only_the_first_yaml_block_is_read(tmp_path):
    """4.1 Reading the scenario file: the first fenced yaml block."""
    second = tiny_data()
    second["scenario"]["id"] = "second_block"
    text = scenario_markdown(tiny_data()) + "\n```yaml\n" + yaml.safe_dump(second) + "```\n"
    path = tmp_path / "scenario.md"
    path.write_text(text, encoding="utf-8")
    assert load_scenario(path).id == "tiny"


# --- weights ----------------------------------------------------------------------------

def test_weights_are_normalised(tmp_path):
    """4.1 Reading the scenario file: weights are normalised to sum to 1."""
    data = tiny_data()
    data["input_parameters"][1]["weights"] = [2, 1, 1]
    scenario = load_scenario(write_scenario(tmp_path, data))
    ip1, ip2 = scenario.input_parameters
    assert list(ip2.weights) == [Fraction(1, 2), Fraction(1, 4), Fraction(1, 4)]
    assert all(isinstance(w, Fraction) for w in ip2.weights)
    # Omitted weights: every state equally common.
    assert list(ip1.weights) == [Fraction(1, 2), Fraction(1, 2)]
    assert sum(ip2.weights) == 1


def test_same_state_name_in_different_variables_is_fine(tmp_path):
    """4.1 Reading the scenario file: the same name in different variables is fine."""
    data = tiny_data()
    data["input_parameters"][0]["states"] = ["hit", "miss"]
    data["input_parameters"][1]["states"] = ["round", "hit", "flat"]
    scenario = load_scenario(write_scenario(tmp_path, data))
    assert scenario.input_parameters[0].states == ["hit", "miss"]


# --- errors naming the field ------------------------------------------------------------

def _set(path, value):
    def mutate(data):
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return mutate


def _delete(path):
    def mutate(data):
        target = data
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]
    return mutate


def _both(*mutators):
    def mutate(data):
        for m in mutators:
            m(data)
    return mutate


ERROR_CASES = [
    # (case id, mutation of tiny_data(), text the error must contain)
    ("missing scenario id", _delete(["scenario", "id"]), "scenario.id"),
    ("missing input_parameters", _delete(["input_parameters"]), "input_parameters"),
    ("missing world_outcomes", _delete(["world_outcomes"]), "world_outcomes"),
    ("missing states", _delete(["input_parameters", 1, "states"]), "input_parameters[1].states"),
    ("missing urn", _delete(["effect_model", "main_effect_urn"]), "effect_model.main_effect_urn"),
    ("missing effect sizes", _delete(["effect_model", "effect_sizes_logit"]),
     "effect_model.effect_sizes_logit"),
    ("missing min_accuracy", _delete(["acceptance_criteria", "nobel_grade", "min_accuracy"]),
     "acceptance_criteria.nobel_grade.min_accuracy"),
    ("missing max_generation_tries", _delete(["acceptance_criteria", "max_generation_tries"]),
     "acceptance_criteria.max_generation_tries"),
    ("repeated input state", _set(["input_parameters", 1, "states"], ["round", "square", "round"]),
     "input_parameters[1].states"),
    ("repeated outcome state", _set(["world_outcomes", 0, "states"], ["hit", "hit"]),
     "world_outcomes[0].states"),
    ("unknown urn size", _set(["effect_model", "main_effect_urn"], ["+large", "-huge"]),
     "effect_model.main_effect_urn"),
    ("urn entry without sign", _set(["effect_model", "main_effect_urn"], ["large", "-small"]),
     "effect_model.main_effect_urn"),
    ("urn entry with a bad sign", _set(["effect_model", "main_effect_urn"], ["*large", "-small"]),
     "effect_model.main_effect_urn"),
    # tiny has 2 + 3 = 5 input states, so 6 urn entries are too many.
    ("urn longer than input states",
     _set(["effect_model", "main_effect_urn"], ["+large", "-large", "+small", "-small", "+large", "-large"]),
     "effect_model.main_effect_urn"),
    ("unknown interaction size", _set(["effect_model", "interactions"], ["huge"]),
     "effect_model.interactions"),
    ("weights of the wrong length", _set(["input_parameters", 1, "weights"], [1, 1]),
     "input_parameters[1].weights"),
    ("zero weight", _set(["input_parameters", 1, "weights"], [1, 0, 1]),
     "input_parameters[1].weights"),
    ("negative weight", _set(["input_parameters", 1, "weights"], [1, -1, 1]),
     "input_parameters[1].weights"),
    # WO1 has 2 states and max 1 interaction per state: room for 2 interactions, not 3.
    ("too many interactions", _set(["effect_model", "interactions"], ["large", "large", "small"]),
     "effect_model.interactions"),
    # With a reference state only "miss" can take interactions: room for 1, not 2.
    ("too many interactions with a reference state",
     _both(_set(["effect_model", "reference_state_per_outcome"], True),
           _set(["effect_model", "interactions"], ["large", "small"])),
     "effect_model.interactions"),
    ("unknown outcome_realisation", _set(["effect_model", "outcome_realisation"], "draw_twice"),
     "effect_model.outcome_realisation"),
    ("unknown interaction_sign", _set(["effect_model", "interaction_sign"], "sideways"),
     "effect_model.interaction_sign"),
    ("unknown nobel count", _set(["acceptance_criteria", "nobel_grade", "count"], "papers"),
     "acceptance_criteria.nobel_grade.count"),
]


@pytest.mark.parametrize("mutate, field", [c[1:] for c in ERROR_CASES], ids=[c[0] for c in ERROR_CASES])
def test_inconsistent_scenario_names_the_field(tmp_path, mutate, field):
    """4.1 Reading the scenario file: stops with an error naming the field."""
    data = tiny_data()
    mutate(data)
    path = write_scenario(tmp_path, data)
    with pytest.raises(ScenarioError) as excinfo:
        load_scenario(path)
    assert field in str(excinfo.value), f"error does not name {field!r}: {excinfo.value}"


def test_tiny_scenario_itself_is_valid(tmp_path):
    """4.1 Reading the scenario file: the fixture the error cases start from loads cleanly."""
    scenario = load_scenario(write_scenario(tmp_path, tiny_data()))
    assert scenario.id == "tiny"
    assert [v.id for v in scenario.input_parameters] == ["IP1", "IP2"]
    assert [v.id for v in scenario.world_outcomes] == ["WO1"]


def test_interactions_that_exactly_fill_the_room_are_fine(tmp_path):
    """4.2 Generating the World Table (Interactions): room is states x max per state."""
    data = tiny_data()
    data["effect_model"]["interactions"] = ["large", "small"]
    load_scenario(write_scenario(tmp_path, data))


def test_interactions_need_two_input_parameters(tmp_path):
    """4.2 Generating the World Table (Interactions): pairs from different input parameters."""
    data = tiny_data()
    data["input_parameters"] = data["input_parameters"][1:]
    data["effect_model"]["main_effect_urn"] = ["+large"]
    path = write_scenario(tmp_path, data)
    with pytest.raises(ScenarioError) as excinfo:
        load_scenario(path)
    message = str(excinfo.value)
    assert "interactions" in message or "input_parameters" in message, message


def test_one_input_parameter_without_interactions_is_fine(tmp_path):
    """4.2 Generating the World Table (Interactions): no interactions, no pairs needed."""
    data = tiny_data()
    data["input_parameters"] = data["input_parameters"][1:]
    data["effect_model"]["interactions"] = []
    load_scenario(write_scenario(tmp_path, data))


def test_no_yaml_block(tmp_path):
    """4.1 Reading the scenario file: the generator reads the first fenced yaml block."""
    path = tmp_path / "scenario.md"
    path.write_text("# Scenario\n\n## Story\n\nNo data here.\n", encoding="utf-8")
    with pytest.raises(ScenarioError):
        load_scenario(path)


# --- Input Parameter Deck size ----------------------------------------------------------

def test_deck_size_not_divisible_by_state_count(tmp_path):
    """4.1 Reading the scenario file: the deck size (after overrides) must divide by each state count."""
    data = tiny_data()
    # 4 divides by IP1's 2 states but not by IP2's 3 states.
    data["parameter_overrides"] = {"input_parameter_deck_size": 4}
    path = write_scenario(tmp_path, data)
    with pytest.raises(ScenarioError) as excinfo:
        load_scenario(path)
    message = str(excinfo.value)
    assert "input_parameter_deck_size" in message or "input_parameters[1]" in message, message


def test_deck_size_from_the_defaults_file_is_checked(tmp_path):
    """4.1 Reading the scenario file: the deck size comes from parameter_defaults.yaml."""
    defaults = yaml.safe_load(PARAMETER_DEFAULTS.read_text(encoding="utf-8"))
    defaults["input_parameter_deck_size"] = 4
    defaults_path = tmp_path / "defaults.yaml"
    defaults_path.write_text(yaml.safe_dump(defaults, sort_keys=False), encoding="utf-8")
    path = write_scenario(tmp_path, tiny_data())
    with pytest.raises(ScenarioError) as excinfo:
        load_scenario(path, parameter_defaults=defaults_path)
    message = str(excinfo.value)
    assert "input_parameter_deck_size" in message or "input_parameters[1]" in message, message


def test_divisible_deck_size_override_is_applied(tmp_path):
    """4.1 Reading the scenario file; 11. Configuration: overrides apply to the scenario's settings."""
    data = tiny_data()
    # 6 divides by 2 and by 3.
    data["parameter_overrides"] = {"input_parameter_deck_size": 6}
    scenario = load_scenario(write_scenario(tmp_path, data))
    assert scenario.settings.input_parameter_deck_size == 6
    assert scenario.parameter_overrides == {"input_parameter_deck_size": 6}
    expected = load_settings({"input_parameter_deck_size": 6}).model_dump()
    assert scenario.settings.model_dump() == expected


def test_unknown_override_is_rejected(tmp_path):
    """4.1 Reading the scenario file; 11. Configuration: overrides must name existing settings."""
    data = tiny_data()
    data["parameter_overrides"] = {"no_such_setting": 3}
    path = write_scenario(tmp_path, data)
    with pytest.raises((ScenarioError, SettingsError)) as excinfo:
        load_scenario(path)
    assert "no_such_setting" in str(excinfo.value)


# --- the hash of the YAML data ------------------------------------------------------------

def test_hash_is_stable():
    """4.4 World files: a hash of the scenario's YAML block."""
    assert load_scenario(VENUS).yaml_hash == load_scenario(VENUS).yaml_hash
    assert load_scenario(VENUS).yaml_hash


def test_hash_ignores_comments_layout_and_story(tmp_path):
    """4.4 World files: the hash is of the parsed data; comments or layout do not change it."""
    data = tiny_data()
    plain = load_scenario(write_scenario(tmp_path, data, "a.md")).yaml_hash
    flow = load_scenario(write_scenario(tmp_path, data, "b.md", flow_style=True)).yaml_hash
    commented = load_scenario(write_scenario(tmp_path, data, "c.md", comments=True)).yaml_hash
    other_story = load_scenario(write_scenario(tmp_path, data, "d.md", story="Another story.")).yaml_hash
    assert plain == flow == commented == other_story


def test_hash_of_venus_ignores_comments(tmp_path):
    """4.4 World files: editing comments or layout does not change the hash."""
    data = venus_data()
    rewritten = load_scenario(write_scenario(tmp_path, data, flow_style=True)).yaml_hash
    assert rewritten == load_scenario(VENUS).yaml_hash


@pytest.mark.parametrize(
    "mutate",
    [
        _set(["effect_model", "effect_sizes_logit", "large"], 2.5),
        _set(["acceptance_criteria", "max_base_rate"], 0.95),
        _set(["input_parameters", 1, "states"], ["round", "square", "oval"]),
        _set(["parameter_overrides"], {"input_parameter_deck_size": 6}),
    ],
    ids=["effect size", "criterion", "state name", "override"],
)
def test_hash_changes_when_a_value_changes(tmp_path, mutate):
    """4.4 World files: the hash lets the software warn when a scenario's data was edited."""
    data = tiny_data()
    before = load_scenario(write_scenario(tmp_path, data, "before.md")).yaml_hash
    changed = copy.deepcopy(data)
    mutate(changed)
    after = load_scenario(write_scenario(tmp_path, changed, "after.md")).yaml_hash
    assert before != after

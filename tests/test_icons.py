"""The icon tiles (asset_generation/) match the scenario whose states they represent."""

import json

import yaml

from nv_core.paths import REPO_ROOT, SCENARIOS_DIR
from nv_world.scenario import load_scenario

ASSETS = REPO_ROOT / "asset_generation"


def test_every_state_has_exactly_one_icon_with_a_source_image_and_a_generated_tile():
    config = yaml.safe_load((ASSETS / "icons.yaml").read_text(encoding="utf-8"))
    scenario = load_scenario(SCENARIOS_DIR / config["scenario"] / "scenario.md")
    states = {s for v in scenario.input_parameters + scenario.world_outcomes for s in v.states}
    assert set(config["icons"]) == states
    output = REPO_ROOT / "web" / "icons" / config["scenario"]
    for state, icon in config["icons"].items():
        assert (ASSETS / "icons_source" / icon["source"]).exists(), state
        assert (output / f"{state.replace(' ', '_')}.png").exists(), state


def test_the_web_client_gets_each_tile_colour_from_icons_yaml():
    config = yaml.safe_load((ASSETS / "icons.yaml").read_text(encoding="utf-8"))
    path = REPO_ROOT / "web" / "icons" / config["scenario"] / "colours.json"
    colours = json.loads(path.read_text(encoding="utf-8"))
    assert {s: c["background"].lower() for s, c in colours.items()} == {
        s: icon["colour"][:7].lower() for s, icon in config["icons"].items()
    }

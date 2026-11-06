"""Turn a scenario and a world file into the data the rules engine plays with."""

from pathlib import Path

from nv_core.paths import SCENARIOS_DIR
from nv_core.settings import Settings
from nv_core.world_data import Variable, WorldData, WorldRow
from nv_world.generate import World
from nv_world.scenario import Scenario, load_scenario
from nv_world.screening import check_rows
from nv_world.worldfile import load_world, scenario_changed


def world_data(scenario: Scenario, world: World, world_id: str) -> WorldData:
    check_rows(scenario, world.rows)
    return WorldData(
        scenario_id=scenario.id,
        title=scenario.title,
        story=scenario.story,
        world_id=world_id,
        input_parameters=[Variable(id=v.id, name=v.name, states=list(v.states)) for v in scenario.input_parameters],
        world_outcomes=[Variable(id=v.id, name=v.name, states=list(v.states)) for v in scenario.world_outcomes],
        rows=[WorldRow(inputs=dict(r.inputs), outcomes=dict(r.outcomes)) for r in world.rows],
    )


def load_game_world(world_path: Path, scenario_path: Path | None = None) -> tuple[WorldData, Settings, list[str]]:
    """Read a world file and its scenario; return the world data, the scenario's settings and any warnings."""
    world_path = Path(world_path)
    world = load_world(world_path)
    scenario_path = Path(scenario_path) if scenario_path else SCENARIOS_DIR / world.scenario_id / "scenario.md"
    scenario = load_scenario(scenario_path)
    warnings = []
    if scenario_changed(world, scenario):
        warnings.append(f"the data in {scenario_path} changed after this world was generated")
    return world_data(scenario, world, world_path.stem), scenario.settings, warnings

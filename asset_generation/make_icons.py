"""Turn the source images into the icon tiles that represent world states.

    .venv/Scripts/python asset_generation/make_icons.py     # needs: pip install -e ".[assets]"

icons.yaml says which source image and colour each state gets. The tiles go to
web/icons/<scenario>/, one per state, named after the state with spaces as underscores
(fat blue -> fat_blue.png); the server already serves that folder at /web/icons/<scenario>/.
"""

import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from nv_core.paths import REPO_ROOT, SCENARIOS_DIR  # noqa: E402
from nv_world.scenario import load_scenario  # noqa: E402

SOURCE_DIR = HERE / "icons_source"
OUTPUT_ROOT = REPO_ROOT / "web" / "icons"

SIZE, SS = 512, 4  # output size, supersampling factor
S = SIZE * SS
BORDER, RADIUS, MARGIN, ICON = 22 * SS, 96 * SS, 6 * SS, 0.66  # ICON = share of the tile's width


def check_states(icons: dict[str, dict[str, str]], scenario_id: str) -> None:
    """Every state of the scenario needs an icon, and every icon must belong to a state."""
    scenario = load_scenario(SCENARIOS_DIR / scenario_id / "scenario.md")
    states = {s for v in scenario.input_parameters + scenario.world_outcomes for s in v.states}
    missing, unknown = sorted(states - set(icons)), sorted(set(icons) - states)
    if missing or unknown:
        sys.exit(f"icons.yaml does not match scenario {scenario_id}: no icon for {missing}; not states: {unknown}")


def make_tile(source: Path, colour: str) -> Image.Image:
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(tile).rounded_rectangle([MARGIN, MARGIN, S - 1 - MARGIN, S - 1 - MARGIN], radius=RADIUS,
                                           fill=colour, outline="black", width=BORDER)
    with Image.open(source) as opened:
        icon = opened.convert("RGBA")
    icon = icon.crop(icon.getbbox())  # trim empty margins
    scale = ICON * S / max(icon.size)
    icon = icon.resize((round(icon.width * scale), round(icon.height * scale)), Image.LANCZOS)
    tile.alpha_composite(icon, ((S - icon.width) // 2, (S - icon.height) // 2))
    return tile.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    config = yaml.safe_load((HERE / "icons.yaml").read_text(encoding="utf-8"))
    scenario_id, icons = config["scenario"], config["icons"]
    check_states(icons, scenario_id)
    output = OUTPUT_ROOT / scenario_id
    output.mkdir(parents=True, exist_ok=True)
    for state, icon in icons.items():
        make_tile(SOURCE_DIR / icon["source"], icon["colour"]).save(output / f"{state.replace(' ', '_')}.png")
    print(f"{len(icons)} icons in {output.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

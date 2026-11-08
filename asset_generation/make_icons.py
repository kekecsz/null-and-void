"""Turn the source images into the icon tiles that represent world states.

    .venv/Scripts/python asset_generation/make_icons.py     # needs: pip install -e ".[assets]"

icons.yaml says which source image and colour each state gets. The tiles go to
web/icons/<scenario>/, one per state, named after the state with spaces as underscores
(fat blue -> fat_blue.png), with colours.json for the compact tiles; the server already serves
that folder at /web/icons/<scenario>/.
"""

import json
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


def tile_colours(colour: str) -> dict[str, str]:
    """The colour of a state's tile, and a readable text colour on it (for the compact tiles)."""
    rgb = colour[1:7]
    red, green, blue = (int(rgb[i : i + 2], 16) for i in (0, 2, 4))
    brightness = 0.299 * red + 0.587 * green + 0.114 * blue
    return {"background": f"#{rgb}", "text": "#ffffff" if brightness < 140 else "#1d1d1b"}


def main() -> None:
    config = yaml.safe_load((HERE / "icons.yaml").read_text(encoding="utf-8"))
    scenario_id, icons = config["scenario"], config["icons"]
    check_states(icons, scenario_id)
    output = OUTPUT_ROOT / scenario_id
    output.mkdir(parents=True, exist_ok=True)
    for state, icon in icons.items():
        make_tile(SOURCE_DIR / icon["source"], icon["colour"]).save(output / f"{state.replace(' ', '_')}.png")
    # The web client reads this; asset_generation/ itself is not deployed.
    colours = {state: tile_colours(icon["colour"]) for state, icon in icons.items()}
    (output / "colours.json").write_text(json.dumps(colours, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(icons)} icons in {output.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

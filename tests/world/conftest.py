"""Shared helpers for the world generator tests (specification section 4).

The tiny scenarios below are hand-made fixtures: their values are chosen here, not taken from
the game documents, so the tests can work out expected results by hand.
"""

import copy
import re
from pathlib import Path

import yaml

from nv_core.paths import SCENARIOS_DIR

VENUS = SCENARIOS_DIR / "venus_expedition" / "scenario.md"

DEFAULT_STORY = "A tiny world made for the tests.\n\nIt has a second paragraph."

# The tiny scenarios set their own Input Parameter Deck size (4.1: it must divide by every
# parameter's state count), so they never depend on the value in parameter_defaults.yaml.
TINY_DECK_SIZE = 12  # divides by 2 and by 3

# Criteria that every world passes: no base rate or accuracy can exceed 1, and with
# min_accuracy 0 every theory is Nobel-grade, which no count range below excludes.
EASY_CRITERIA = {
    "max_base_rate": 1.0,
    "max_one_input_theory_accuracy": 1.0,
    "nobel_grade": {
        "min_accuracy": 0.0,
        "max_input_parameters": 2,
        "count": "theories",
        "min_count": 0,
        "max_count": 1000000,
    },
    "max_generation_tries": 5,
}


def tiny_data() -> dict:
    """Two input parameters (2 and 3 states), one world outcome with 2 states.

    5 input states in total. The scenario overrides input_parameter_deck_size with
    TINY_DECK_SIZE, which divides by 2 and 3.
    """
    return {
        "scenario": {"id": "tiny", "title": "Tiny test world"},
        "input_parameters": [
            {"id": "IP1", "name": "colour", "states": ["red", "blue"]},
            {"id": "IP2", "name": "shape", "states": ["round", "square", "flat"]},
        ],
        "world_outcomes": [
            {"id": "WO1", "name": "result", "states": ["hit", "miss"]},
        ],
        "effect_model": {
            "effect_sizes_logit": {"small": 0.5, "large": 2.0},
            "main_effect_urn": ["+large", "-small"],
            "reference_state_per_outcome": False,
            "interactions": ["large"],
            "interaction_sign": "random",
            "max_interactions_per_outcome_state": 1,
            "outcome_realisation": "draw_once",
        },
        "acceptance_criteria": copy.deepcopy(EASY_CRITERIA),
        "parameter_overrides": {"input_parameter_deck_size": TINY_DECK_SIZE},
    }


def two_outcome_data() -> dict:
    """The tiny scenario with a second world outcome WO2 (tone: light, dark)."""
    data = tiny_data()
    data["scenario"]["id"] = "tiny_two"
    data["world_outcomes"].append({"id": "WO2", "name": "tone", "states": ["light", "dark"]})
    return data


def with_criteria(data: dict, **changes) -> dict:
    """Copy of `data` with acceptance criteria changed.

    Keys of `changes` are top-level criteria, or `nobel_<field>` for a nobel_grade field.
    """
    data = copy.deepcopy(data)
    criteria = data["acceptance_criteria"]
    for key, value in changes.items():
        if key.startswith("nobel_"):
            criteria["nobel_grade"][key[len("nobel_"):]] = value
        else:
            criteria[key] = value
    return data


def scenario_markdown(data, story: str = DEFAULT_STORY, *, flow_style: bool = False,
                      comments: bool = False) -> str:
    """A scenario file: a Story section and a Scenario data section with one yaml block.

    `data` is a dict (dumped as YAML) or ready-made YAML text.
    """
    if isinstance(data, str):
        block = data
    else:
        block = yaml.safe_dump(data, sort_keys=False, default_flow_style=flow_style, width=4096)
    if comments:
        lines = []
        for line in block.splitlines():
            if lines and line and not line[0].isspace():
                lines.append("")
                lines.append("# a comment between top-level keys")
            lines.append(line + "   # trailing comment" if line.rstrip().endswith(":") else line)
        block = "# a comment added at the top\n" + "\n".join(lines) + "\n# and one at the end\n"
    return (
        "# Scenario: test\n\n"
        "Intro text that is not part of the story.\n\n"
        "## Story\n\n"
        f"{story}\n\n"
        "## Scenario data\n\n"
        "```yaml\n"
        f"{block.rstrip()}\n"
        "```\n\n"
        "## How these values are used\n\n"
        "Text after the data block.\n"
    )


def write_scenario(directory: Path, data, filename: str = "scenario.md", **kwargs) -> Path:
    path = Path(directory) / filename
    path.write_text(scenario_markdown(data, **kwargs), encoding="utf-8")
    return path


def yaml_block_text(path: Path) -> str:
    """The first fenced yaml block of a scenario file."""
    text = Path(path).read_text(encoding="utf-8")
    match = re.search(r"```yaml[ \t]*\r?\n(.*?)\r?\n```", text, re.DOTALL)
    assert match, f"no yaml block in {path}"
    return match.group(1)


def yaml_block_data(path: Path) -> dict:
    return yaml.safe_load(yaml_block_text(path))


def venus_data() -> dict:
    return yaml_block_data(VENUS)


def story_section(path: Path) -> str:
    """The text of the "Story" section of a scenario file (heading excluded)."""
    text = Path(path).read_text(encoding="utf-8")
    match = re.search(r"^## Story[ \t]*\r?\n(.*?)(?=^## )", text, re.DOTALL | re.MULTILINE)
    assert match, f"no Story section in {path}"
    return match.group(1).strip()


# --- comparing worlds through the public attributes only ---------------------------------

def main_effects_signature(world) -> list:
    return [(m.outcome, m.outcome_state, m.input, m.input_state, m.effect) for m in world.main_effects]


def interactions_signature(world) -> list:
    return [
        (i.outcome, i.outcome_state, i.input_a, i.state_a, i.input_b, i.state_b, i.size, i.sign)
        for i in world.interactions
    ]


def rows_signature(rows) -> list:
    return [(dict(r.inputs), dict(r.outcomes)) for r in rows]


def probabilities_signature(rows) -> list:
    return [{o: dict(states) for o, states in r.probabilities.items()} for r in rows]


def world_signature(world) -> tuple:
    """Everything 4.2 says a generated world records, as plain Python values."""
    return (
        main_effects_signature(world),
        interactions_signature(world),
        rows_signature(world.rows),
        probabilities_signature(world.rows),
    )


def screening_signature(report) -> tuple:
    return (
        {o: dict(states) for o, states in report.base_rates.items()},
        dict(report.best_accuracy_by_inputs),
        sorted(
            (sorted(s.theory.inputs.items()), sorted(s.theory.outcomes.items()), s.coverage, s.accuracy)
            for s in report.nobel_grade
        ),
        dict(report.nobel_counts),
        sorted(report.failed),
        report.passed,
    )

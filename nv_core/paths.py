"""Locations of the project's source-of-truth documents."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
RULEBOOK = DOCS_DIR / "rules.md"
PARAMETER_DEFAULTS = DOCS_DIR / "parameter_defaults.yaml"
SPECIFICATION = DOCS_DIR / "specification.md"
SCENARIOS_DIR = REPO_ROOT / "scenarios"
SETTINGS_DIR = REPO_ROOT / "settings"


def scenario_files() -> list[Path]:
    """Every scenario file (scenarios/<id>/scenario.md)."""
    return sorted(SCENARIOS_DIR.glob("*/scenario.md"))

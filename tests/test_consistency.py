"""Consistency check between the documents (specification section 13, "Testing throughout").

- Every [parameter] named in the rulebook or docs/pieces.md exists in parameter_defaults.yaml, as a
  top-level setting or as a field of the grant_track / journal_tiers tables.
- Every top-level setting is named in the rulebook, docs/pieces.md or specification section 5.7.
- Every scenario file passes its schema.
"""

import pytest
import yaml

from nv_core.markdown_text import parameter_references, read_markdown, section_text
from nv_core.paths import PARAMETER_DEFAULTS, PIECES, RULEBOOK, SPECIFICATION, scenario_files
from nv_world.scenario import load_scenario

TABLES = ("grant_track", "journal_tiers")


def _parameters() -> dict:
    return yaml.safe_load(PARAMETER_DEFAULTS.read_text(encoding="utf-8"))


def _table_fields(parameters: dict) -> set[str]:
    return {field for table in TABLES for row in parameters[table] for field in row}


def test_rulebook_parameters_exist_in_parameter_file():
    parameters = _parameters()
    known = set(parameters) | _table_fields(parameters)
    referenced = parameter_references(read_markdown(RULEBOOK)) | parameter_references(read_markdown(PIECES))
    missing = sorted(referenced - known)
    assert not missing, f"named in the rulebook or docs/pieces.md but not in parameter_defaults.yaml: {missing}"


def test_every_parameter_is_used():
    parameters = _parameters()
    used = parameter_references(read_markdown(RULEBOOK)) | parameter_references(read_markdown(PIECES))
    clarifications = section_text(read_markdown(SPECIFICATION), "5.7")
    used |= parameter_references(clarifications)
    unused = sorted(set(parameters) - used)
    assert not unused, (
        "settings in parameter_defaults.yaml named neither in the rulebook, docs/pieces.md "
        f"nor in specification section 5.7: {unused}"
    )


def test_markdown_escapes_are_stripped():
    # The rulebook is a Google Docs export: references must be found through the escapes.
    assert parameter_references(read_markdown(RULEBOOK)), "no [parameter] found in the rulebook"


@pytest.mark.parametrize("path", scenario_files(), ids=lambda p: p.parent.name)
def test_scenario_file_passes_its_schema(path):
    scenario = load_scenario(path)
    assert scenario.id == path.parent.name, "a scenario's folder is named after its id"

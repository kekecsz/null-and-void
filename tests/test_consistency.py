"""Consistency check between the documents (specification section 13, "Testing throughout").

- Every [parameter] named in the rulebook exists in parameter_defaults.yaml, as a
  top-level setting or as a field of the grant_track / journal_tiers tables.
- Every top-level setting is named in the rulebook or in specification section 5.7.
- Every scenario file passes its schema (added with the scenario reader, Milestone 1).
"""

import yaml

from nv_core.markdown_text import parameter_references, read_markdown, section_text
from nv_core.paths import PARAMETER_DEFAULTS, RULEBOOK, SPECIFICATION

TABLES = ("grant_track", "journal_tiers")


def _parameters() -> dict:
    return yaml.safe_load(PARAMETER_DEFAULTS.read_text(encoding="utf-8"))


def _table_fields(parameters: dict) -> set[str]:
    return {field for table in TABLES for row in parameters[table] for field in row}


def test_rulebook_parameters_exist_in_parameter_file():
    parameters = _parameters()
    known = set(parameters) | _table_fields(parameters)
    referenced = parameter_references(read_markdown(RULEBOOK))
    missing = sorted(referenced - known)
    assert not missing, f"named in the rulebook but not in parameter_defaults.yaml: {missing}"


def test_every_parameter_is_used():
    parameters = _parameters()
    used = parameter_references(read_markdown(RULEBOOK))
    clarifications = section_text(read_markdown(SPECIFICATION), "5.7")
    used |= parameter_references(clarifications)
    unused = sorted(set(parameters) - used)
    assert not unused, (
        "settings in parameter_defaults.yaml named neither in the rulebook "
        f"nor in specification section 5.7: {unused}"
    )


def test_markdown_escapes_are_stripped():
    # The rulebook is a Google Docs export: references must be found through the escapes.
    assert parameter_references(read_markdown(RULEBOOK)), "no [parameter] found in the rulebook"

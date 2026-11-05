"""Reading the Google Docs export: escape removal, [parameter] references and sections.

Supports the consistency check of specification section 13. The rulebook-wide count check guards
against a pattern that silently drops escaped references.
"""

import re

import pytest

from nv_core.markdown_text import parameter_references, read_markdown, section_text, strip_escapes
from nv_core.paths import RULEBOOK


def test_escapes_are_removed():
    assert strip_escapes(r"\[cost\_of\_postdoc\] \* 3\! \(note\)") == "[cost_of_postdoc] * 3! (note)"


def test_backslash_before_a_letter_is_kept():
    assert strip_escapes(r"C:\Users") == r"C:\Users"


def test_references_found_through_escapes():
    text = strip_escapes(r"pay \[cost\_of\_postdoc\] and \[OA\_publication\_AC\_reward\].")
    assert parameter_references(text) == {"cost_of_postdoc", "OA_publication_AC_reward"}


@pytest.mark.parametrize(
    "text",
    [
        "[a link](https://example.org)",
        "[Designer note: prose in brackets]",
        "[See the Specs document.]",
    ],
)
def test_non_parameters_are_ignored(text):
    assert parameter_references(text) == set()


def test_every_escaped_reference_in_the_rulebook_is_found():
    raw = RULEBOOK.read_text(encoding="utf-8")
    # Independent count on the raw export: \[name\] with escaped underscores.
    raw_names = {m.replace("\\_", "_") for m in re.findall(r"\\\[([A-Za-z0-9\\_]+?)\\\]", raw)}
    assert raw_names, "the rulebook export should contain escaped [parameter] references"
    assert raw_names <= parameter_references(read_markdown(RULEBOOK))


def test_section_text_stops_at_same_or_higher_heading():
    text = "# A\nintro\n## A.1 Sub\nbody\n### deeper\nmore\n## A.2 Next\nother\n# B\nend\n"
    assert section_text(text, "A.1") == "body\n### deeper\nmore"
    assert section_text(text, "A") == "intro\n## A.1 Sub\nbody\n### deeper\nmore\n## A.2 Next\nother"
    with pytest.raises(KeyError):
        section_text(text, "Z")

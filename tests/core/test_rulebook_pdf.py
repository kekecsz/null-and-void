"""The reader's edition of the rulebook: every [parameter] filled in, both tables in place."""

import pytest

from nv_core.markdown_text import parameter_references, read_markdown
from nv_core.paths import RULEBOOK
from nv_core.settings import load_settings
from nv_rulebook.fill import TABLE_LINE, FillError, fill_rulebook, table_rows
from nv_rulebook.pdf import check_printable, make_pdf

# Hand-made settings: the numbers are this test's own, not the game's.
SETTINGS = {
    "gain": 7,
    "one": 1,
    "fine": -3,
    "small_fine": -1,
    "cards": 5,
    "rounds": 3,
    "some_AC_reward": 1,
    "journal_tiers": [
        {"min_records": 0, "peer_review": False, "apc": 2},
        {"min_records": 1, "peer_review": True, "apc": 4},
    ],
    "grant_track": [{"funding": 1, "expected_to_increase": 2}, {"funding": 3, "expected_to_increase": None}],
}


def fill(text: str) -> str:
    return fill_rulebook(text, SETTINGS)


def test_plain_value():
    assert fill("You get [gain] coins.") == "You get 7 coins."


def test_value_after_a_penalty_loses_its_minus_sign():
    assert fill("suffers a penalty of [fine] academic credits.") == "suffers a penalty of 3 academic credits."
    assert fill("suffers [small_fine] academic credit penalty") == "suffers 1 academic credit penalty"


def test_value_scored_directly_keeps_its_minus_sign():
    assert fill("[fine] academic credits are scored") == "-3 academic credits are scored"


def test_singular_after_one():
    assert fill("[one] academic credits are awarded") == "1 academic credit is awarded"
    assert fill("a penalty of [small_fine] academic credits.") == "a penalty of 1 academic credit."


def test_reward_without_a_unit_gets_one():
    assert fill("immediately gets [some_AC_reward].") == "immediately gets 1 academic credit."


@pytest.mark.parametrize(
    "text, expected",
    [
        ("[cards] / 2, rounded down Noise cards", "2 Noise cards"),
        ("[cards] / 4, rounded down, Noise cards", "1 Noise card"),
        ("[cards] * 3 credits", "15 credits"),
        ("have: [cards] + 3).", "have: 8)."),
    ],
)
def test_arithmetic_is_worked_out(text, expected):
    assert fill(text) == expected


def test_division_that_does_not_come_out_even_is_refused():
    with pytest.raises(FillError, match="cards"):
        fill("[cards] / 2 tokens")


def test_multiplying_by_player_number_stays_a_formula():
    assert fill("([cards] * player number) cards") == "(5 × player number) cards"


def test_ordinal():
    assert fill("the [rounds]th round") == "the 3rd round"


@pytest.mark.parametrize(
    "sentence, table",
    [
        ("The values are in parameter_defaults.yaml in the [journal_tiers] table.", "journal_tiers"),
        ("The values for each position are in parameter_defaults.yaml in the [grant_track] table.", "grant_track"),
    ],
)
def test_table_goes_straight_after_its_sentence(sentence, table):
    lines = [line for line in fill(f"Before. {sentence} After.\nNext paragraph.").splitlines() if line]
    assert lines[0] == "Before. The values are in the table below. After."
    assert TABLE_LINE.match(lines[1]).group(1) == table
    assert lines[2] == "Next paragraph."


def test_tier_fields_point_at_the_table():
    assert "[" not in fill("Each tier also charges its [submission_fee].")
    assert "[" not in fill("pay (APC), [apc] amount of money into the bank.")


def test_a_reference_that_cannot_be_filled_stops_the_build():
    with pytest.raises(FillError, match="mystery_setting"):
        fill("Pay [mystery_setting] coins.")
    with pytest.raises(FillError, match="apc"):  # a per-tier field in a sentence nobody planned for
        fill("The charge is [apc].")


def test_prose_in_brackets_is_left_alone():
    assert fill("[Designer note: this is prose.]") == "[Designer note: this is prose.]"


def test_table_rows():
    header, rows = table_rows("journal_tiers", SETTINGS)
    assert header == ["Tier", "Min records", "Peer review", "APC"]
    assert rows == [["0", "0", "No", "2"], ["1", "1", "Yes", "4"]]
    header, rows = table_rows("grant_track", SETTINGS)
    assert header == ["Position", "Funding", "Expected to increase"]
    assert rows == [["1", "1", "2"], ["2", "3", "–"]]


def test_real_rulebook_fills_completely_and_can_be_printed():
    """Fails when a rulebook export brings a reference the PDF cannot handle yet."""
    settings = load_settings().model_dump()
    filled = fill_rulebook(read_markdown(RULEBOOK), settings)
    assert not parameter_references(filled)
    assert {m.group(1) for line in filled.splitlines() if (m := TABLE_LINE.match(line))} == {
        "journal_tiers",
        "grant_track",
        "talent_development_track",
    }
    check_printable(filled)


def test_uses_the_values_it_is_given():
    settings = load_settings({"nobel_condition": 987}).model_dump()
    assert "987" in fill_rulebook(read_markdown(RULEBOOK), settings)


def test_character_the_fonts_cannot_draw_is_refused():
    with pytest.raises(ValueError, match="cannot print"):
        check_printable("arrow → here")


def test_pdf_is_written(tmp_path):
    out = make_pdf(tmp_path / "sub" / "rulebook.pdf")
    assert out.read_bytes().startswith(b"%PDF")

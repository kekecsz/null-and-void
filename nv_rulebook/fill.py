"""Replacing the rulebook's [parameter] references with values from the parameter file.

The values and the rule text are only ever read from the documents. What is written here is how a
reference turns into readable English. Anything this module cannot fill stops with an error, so a
new kind of reference in a later rulebook export can never reach the PDF as a raw [name].
"""

import re
from fractions import Fraction
from typing import Any

from nv_core.markdown_text import parameter_references

TABLES = ("journal_tiers", "grant_track")
_TABLE_MARKER = "<<table:{}>>"
TABLE_LINE = re.compile(r"^<<table:(\w+)>>$")

_TABLE_SENTENCE = re.compile(r"The values(?: for each position)? are in parameter_defaults\.yaml in the \[(\w+)\] table\.")

# Fields of journal_tiers: one value per tier, so the sentence has to point at the table.
_TIER_FIELD_PHRASES = {
    "[apc] amount of money": "the amount given in the journal tier table,",
    "its [submission_fee]": "its submission fee (see the table below)",
}

_ORDINAL = re.compile(r"\[(\w+)\]th\b")
_ARITHMETIC = re.compile(r"\[(\w+)\]\s*([*+/])\s*(\d+)(, rounded down,?)?")
_REFERENCE = re.compile(r"\[(\w+)\](?!\()")

_TIER_FIRST_NUMBER = {"journal_tiers": 0, "grant_track": 1}  # see the comments in the parameter file
_FIRST_COLUMN = {"journal_tiers": "Tier", "grant_track": "Position"}
_COLUMN_LABELS = {"apc": "APC"}


class FillError(ValueError):
    """The rulebook holds a reference this module cannot turn into text."""


def _ordinal(number: int) -> str:
    if 10 <= number % 100 <= 20:
        return f"{number}th"
    return f"{number}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th') }"


def _insert_tables(text: str) -> str:
    """Point the two "values are in the parameter file" sentences at a table placed right after them."""
    lines = []
    for line in text.splitlines():
        match = _TABLE_SENTENCE.search(line)
        if match is None:
            lines.append(line)
            continue
        lines.append(line[: match.start()] + "The values are in the table below." + line[match.end() :])
        lines += ["", _TABLE_MARKER.format(match.group(1)), ""]
    return "\n".join(lines)


def _number(name: str, numbers: dict[str, int]) -> int:
    if name not in numbers:
        raise FillError(f"[{name}] is used in a calculation but is not a number in the parameter file")
    return numbers[name]


def _calculate(match: re.Match, numbers: dict[str, int]) -> str:
    value = _number(match.group(1), numbers)
    operand = int(match.group(3))
    if match.group(2) == "*":
        return str(value * operand)
    if match.group(2) == "+":
        return str(value + operand)
    if match.group(4):  # "/ n, rounded down"
        return str(value // operand)
    result = Fraction(value, operand)
    if result.denominator != 1:
        raise FillError(f"[{match.group(1)}] / {operand} is not a whole number and the rulebook does not round it")
    return str(result.numerator)


def _plain(match: re.Match, numbers: dict[str, int]) -> str:
    name = match.group(1)
    if name not in numbers:
        return match.group(0)  # reported as a leftover by fill_rulebook
    value = numbers[name]
    before, after = match.string[: match.start()], match.string[match.end() :]
    if value < 0 and (before.endswith("penalty of ") or after.startswith(" academic credit penalty")):
        value = -value  # the word "penalty" already says it is a loss
    if name.endswith("_AC_reward") and after.startswith("."):
        return f"{value} academic credit{'' if value == 1 else 's'}"  # the rulebook names no unit here
    return str(value)


def _fix_grammar(text: str) -> str:
    text = re.sub(r"(?<![\d.])(-?1) academic credits are\b", r"\1 academic credit is", text)
    text = re.sub(r"(?<![\d.])(-?1) academic credits\b", r"\1 academic credit", text)
    text = re.sub(r"(?<![\d.])1 Noise cards\b", "1 Noise card", text)
    return text.replace(" * player number", " × player number")


def fill_rulebook(text: str, settings: dict[str, Any]) -> str:
    """The rulebook text (already unescaped) with every [parameter] replaced by its value.

    ``settings`` has the shape of parameter_defaults.yaml. The two tables become lines that
    TABLE_LINE matches, for the renderer to draw with table_rows().
    """
    numbers = {k: v for k, v in settings.items() if isinstance(v, int) and not isinstance(v, bool)}
    text = _insert_tables(text)
    for phrase, replacement in _TIER_FIELD_PHRASES.items():
        text = text.replace(phrase, replacement)
    text = _ORDINAL.sub(lambda m: _ordinal(_number(m.group(1), numbers)), text)
    text = _ARITHMETIC.sub(lambda m: _calculate(m, numbers), text)
    text = _REFERENCE.sub(lambda m: _plain(m, numbers), text)
    leftovers = sorted(parameter_references(text))
    if leftovers:
        raise FillError(f"cannot fill these rulebook references: {leftovers}")
    return _fix_grammar(text)


def table_rows(name: str, settings: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    """Column headings and text rows of grant_track or journal_tiers."""
    if name not in TABLES:
        raise FillError(f"no table called {name!r}")
    entries = settings[name]
    fields = list(entries[0])
    header = [_FIRST_COLUMN[name], *(_COLUMN_LABELS.get(f, f.replace("_", " ").capitalize()) for f in fields)]

    def cell(value: Any) -> str:
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return "–" if value is None else str(value)

    first = _TIER_FIRST_NUMBER[name]
    return header, [[str(first + i), *(cell(entry[f]) for f in fields)] for i, entry in enumerate(entries)]

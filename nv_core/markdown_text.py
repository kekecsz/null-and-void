"""Reading the Markdown documents: escape removal, sections and [parameter] references.

The rulebook is exported from Google Docs, which escapes Markdown punctuation
(``\\_``, ``\\[``, ``\\]``, ``\\!`` ...). Everything here works on the unescaped text.
"""

import re
from pathlib import Path

# CommonMark: a backslash before any ASCII punctuation character is an escape.
_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")

# [name] where name is an identifier, not followed by "(" (that would be a Markdown link).
_REFERENCE = re.compile(r"\[([A-Za-z_][A-Za-z0-9_]*)\](?!\()")

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def strip_escapes(text: str) -> str:
    """Remove Markdown backslash escapes."""
    return _ESCAPE.sub(r"\1", text)


def read_markdown(path: Path) -> str:
    """Read a Markdown file and remove its backslash escapes."""
    return strip_escapes(path.read_text(encoding="utf-8"))


def parameter_references(text: str) -> set[str]:
    """Names written as [name] in the text."""
    return set(_REFERENCE.findall(text))


def section_text(text: str, heading_prefix: str) -> str:
    """The body of the first section whose heading starts with ``heading_prefix``.

    The section ends at the next heading of the same or a higher level.
    Raises KeyError when there is no such heading.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = _HEADING.match(line)
        if match and match.group(2).startswith(heading_prefix):
            level = len(match.group(1))
            body = []
            for following in lines[i + 1 :]:
                next_heading = _HEADING.match(following)
                if next_heading and len(next_heading.group(1)) <= level:
                    break
                body.append(following)
            return "\n".join(body)
    raise KeyError(f"no section heading starts with {heading_prefix!r}")

"""The web pages load their scripts into one global scope (specification section 7): a top-level
name declared in two of a page's scripts stops the page with "Identifier ... has already been
declared". No browser is needed to find that."""

import re
from collections import Counter
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
DECLARATION = re.compile(r"^(?:const|let|var|function|class|async function)\s+([A-Za-z_$][\w$]*)", re.MULTILINE)


def _scripts(page: str) -> list[Path]:
    html = (WEB / page).read_text(encoding="utf-8")
    return [WEB / src.removeprefix("/web/") for src in re.findall(r'<script src="([^"]+)"', html)]


@pytest.mark.parametrize("page", sorted(p.name for p in WEB.glob("*.html")))
def test_no_top_level_name_is_declared_twice_on_a_page(page):
    names = Counter()  # every top-level declaration of every script of the page
    for script in _scripts(page):
        names.update(DECLARATION.findall(script.read_text(encoding="utf-8")))
    assert [n for n, c in names.items() if c > 1] == []

"""Specification 7.6: translations of the screens.

The tests guard only what could break a page: a language file must be readable, and every
translation must keep the {placeholders} of its English text. A missing or outdated translation
is not an error (the English text shows instead); run this file directly for a report of them:

    .venv/Scripts/python tests/test_translations.py
"""

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
LANGUAGE_FILES = sorted((WEB / "i18n").glob("*.js"))
PLACEHOLDER = re.compile(r"\{(\w+)\}")
REGISTER = re.compile(r'I18N\.add\(\s*"([a-z]{2,3})"\s*,\s*"([^"]+)"\s*,')
CALL = re.compile(r'''\bt\(\s*"((?:[^"\\]|\\.)*)"''')


def read_language(path: Path) -> tuple[str, str, dict[str, str]]:
    """(code, name, catalog) of a language file: I18N.add("hu", "Magyar", {...strict JSON...});"""
    text = path.read_text(encoding="utf-8")
    match = REGISTER.search(text)
    if not match:
        raise ValueError(f'{path.name}: no I18N.add("<code>", "<name>", {{...}}) call')
    body = text[match.end():].strip()
    if not body.endswith(");"):
        raise ValueError(f"{path.name}: the file must end with the closing );")
    return match.group(1), match.group(2), json.loads(body[:-2])


def used_texts() -> list[str]:
    """The English texts the client translates: t("...") calls and the pages' static texts."""
    texts: list[str] = []
    for path in sorted(WEB.glob("*.js")):
        texts += [json.loads(f'"{m.group(1)}"') for m in CALL.finditer(path.read_text(encoding="utf-8"))]

    class Texts(HTMLParser):
        skip = 0

        def handle_starttag(self, tag, attrs):
            self.skip += tag in ("script", "style", "title")
            texts.extend(v for k, v in attrs if k in ("placeholder", "title", "data-subtitle") and v)

        def handle_endtag(self, tag):
            self.skip -= tag in ("script", "style", "title")

        def handle_data(self, data):
            if not self.skip and data.strip():
                texts.append(data.strip())

    for page in ("index.html", "game.html"):
        Texts().feed((WEB / page).read_text(encoding="utf-8"))
    return list(dict.fromkeys(texts))


def test_there_is_a_hungarian_translation():
    assert "hu" in [read_language(p)[0] for p in LANGUAGE_FILES]


@pytest.mark.parametrize("path", LANGUAGE_FILES, ids=lambda p: p.name)
def test_language_file_is_readable(path):
    code, name, catalog = read_language(path)
    assert path.stem == code and name
    assert all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in catalog.items())


@pytest.mark.parametrize("path", LANGUAGE_FILES, ids=lambda p: p.name)
def test_translations_keep_the_placeholders(path):
    _, _, catalog = read_language(path)
    wrong = {k: v for k, v in catalog.items() if set(PLACEHOLDER.findall(k)) != set(PLACEHOLDER.findall(v))}
    assert not wrong, f"{path.name}: these translations lose or add a {{placeholder}}: {wrong}"


@pytest.mark.parametrize("page", ["index.html", "game.html"])
def test_pages_load_the_translations_and_offer_a_language_menu(page):
    html = (WEB / page).read_text(encoding="utf-8")
    assert '<script src="/web/i18n.js">' in html and 'id="lang-choice"' in html
    for path in LANGUAGE_FILES:
        assert f'<script src="/web/i18n/{path.name}">' in html


def test_scenario_names_reach_the_view():
    from nv_core.engine import new_game
    from nv_core.settings import load_settings
    from nv_core.views import player_view
    from nv_world.game import load_game_world

    world, _, warnings = load_game_world(ROOT / "scenarios/venus_expedition/worlds/world_seed1.json")
    assert not warnings  # translations do not make a world file outdated
    state = new_game(world, load_settings(), 1, ["A", "B"])
    translations = player_view(state, 0)["scenario"]["translations"]
    assert translations["hu"]["acid rain"]


def test_a_translated_name_must_be_a_name_of_the_scenario(tmp_path):
    from nv_world.scenario import ScenarioError, load_scenario

    text = (ROOT / "scenarios/venus_expedition/scenario.md").read_text(encoding="utf-8")
    bad = tmp_path / "scenario.md"
    bad.write_text(text.replace("    acid rain: savas eső", "    acid rian: savas eső"), encoding="utf-8")
    with pytest.raises(ScenarioError, match="acid rian"):
        load_scenario(bad)


def report() -> None:
    """Which texts each language lacks, and which of its entries no longer match an English text."""
    used = used_texts()
    sources = "\n".join(p.read_text(encoding="utf-8") for p in [*WEB.glob("*.js"), *WEB.glob("*.html"),
                                                                 *(ROOT / "nv_core").glob("*.py"), *(ROOT / "nv_server").glob("*.py"),
                                                                 *(ROOT / "nv_sim").glob("*.py"), *(ROOT / "nv_ai").glob("*.py")])
    for path in LANGUAGE_FILES:
        code, name, catalog = read_language(path)
        missing = [t for t in used if t not in catalog]
        def found(k: str) -> bool:  # also as a value the code passes to t(): a phase, a task, a seat type
            k = k.removeprefix("ai:")  # the AI seat types are made from the personas
            return any(f"{q}{x}{q}" in sources for q in "\"'" for x in (k, k.replace(" ", "_")))

        stale = [k for k in catalog if k not in used and not found(k)]
        print(f"{name} ({path.name}): {len(catalog)} translations")
        print(f"  not translated ({len(missing)}; shown in English):")
        for text in missing:
            print(f"    {text!r}")
        print(f"  possibly outdated ({len(stale)}; no longer found in the code):")
        for text in stale:
            print(f"    {text!r}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    report()

"""Specification 6.1: both storage backends keep the same data, and the deployed server needs no
disk. 6.3: on a public server only the organiser creates games and sees the list of games."""

import pytest
from fastapi.testclient import TestClient

from nv_ai.costs import Ledger, Usage
from nv_core.paths import REPO_ROOT
from nv_server.app import create_app, main
from nv_server.storage import SQLiteStorage
from tests.server.fake_firestore import FakeClient, FakeFirestoreStorage
from tests.server.test_server import WORLD, _finished_game


@pytest.fixture(params=["sqlite", "firestore"])
def storage(request, tmp_path):
    return SQLiteStorage(tmp_path / "games.sqlite") if request.param == "sqlite" else FakeFirestoreStorage(FakeClient())


def test_games_are_stored_listed_and_updated(storage):
    assert storage.get_meta("a") is None
    storage.create_game("a", {"title": "first", "numbers": [[1, 2], [3]]})
    storage.create_game("b", {"title": "second"})
    storage.update_meta("a", {"title": "changed", "numbers": [[1, 2], [3]]})
    assert storage.get_meta("a") == {"title": "changed", "numbers": [[1, 2], [3]]}
    listed = {g["id"]: g for g in storage.list_games()}
    assert set(listed) == {"a", "b"} and listed["a"]["actions"] == 0 and listed["b"]["meta"] == {"title": "second"}


def test_an_action_is_stored_only_under_the_next_sequence_number(storage):
    storage.create_game("a", {})
    assert storage.append_action("a", 1, {"n": 1}, []) is False
    assert storage.append_action("a", 0, {"n": 0}, [{"text": "x"}]) is True
    assert storage.append_action("a", 0, {"n": "again"}, []) is False
    assert storage.actions("a") == [({"n": 0}, [{"text": "x"}])]  # read once, and then...
    assert storage.append_action("a", 1, {"n": 1}, []) is True
    assert [a["n"] for a, _ in storage.actions("a")] == [0, 1]  # ...new actions still appear
    assert storage.list_games()[0]["actions"] == 2


def test_snapshots_give_the_latest_and_the_latest_before_an_action(storage):
    storage.create_game("a", {})
    assert storage.latest_snapshot("a") is None
    for seq in (0, 12, 30):
        storage.save_snapshot("a", seq, f"state{seq}")
    assert tuple(storage.latest_snapshot("a")) == (30, "state30")
    assert tuple(storage.snapshot_before("a", 29)) == (12, "state12")
    assert tuple(storage.snapshot_before("a", 30)) == (30, "state30")


def test_ai_decisions_keep_their_order(storage):
    storage.create_game("a", {})
    for n in range(12):
        storage.add_ai_decision("a", {"n": n})
    assert [d["n"] for d in storage.ai_decisions("a")] == list(range(12))


def test_a_whole_game_is_played_and_debriefed_on_firestore_and_survives_a_restart():
    storage = FakeFirestoreStorage(FakeClient())
    with TestClient(create_app(storage=storage)) as client:
        game, host, token = _finished_game(client)
        debrief = client.post(f"/api/games/{game}/debrief", json={"host_token": host}).json()
    assert debrief["bookkeeping_recorded"]
    restarted = FakeFirestoreStorage(storage.client)  # a new instance: nothing in memory
    with TestClient(create_app(storage=restarted)) as client:
        assert client.post(f"/api/games/{game}/debrief", json={"seat_token": token}).json() == debrief


# The AI budget (specification 8.4) ---------------------------------------------------------------
def test_the_ai_budget_survives_a_restart_of_a_server_without_a_disk():
    storage = FakeFirestoreStorage(FakeClient())
    ledger = Ledger(None, budget=1.0, store=storage)
    ledger.add("g", "0", "model", Usage(input_tokens=5), 0.25)
    ledger.add("g", "1", "model", Usage(output_tokens=5), 0.5)
    again = Ledger(None, budget=1.0, store=FakeFirestoreStorage(storage.client))
    assert again.total == pytest.approx(0.75) and again.remaining == pytest.approx(0.25)
    entries = [v for k, v in storage.client.store.items() if "/entries/" in k]
    assert len(entries) == 2 and {e["seat"] for e in entries} == {"0", "1"}


# The organiser password -----------------------------------------------------------------------------
def _body():
    return {"world": WORLD, "seats": [{"kind": "human"}, {"kind": "selfish"}], "seed": 5}


def test_with_an_organiser_password_only_the_organiser_creates_and_lists_games(tmp_path):
    with TestClient(create_app(db=tmp_path / "g.sqlite", organiser_password="sesame")) as client:
        assert client.get("/api/options").json()["organiser_required"] is True
        assert client.post("/api/games", json=_body()).status_code == 403
        assert client.post("/api/games", json=_body(), headers={"X-Organiser-Password": "wrong"}).status_code == 403
        assert client.get("/api/games").status_code == 403
        made = client.post("/api/games", json=_body(), headers={"X-Organiser-Password": "sesame"})
        assert made.status_code == 200
        assert len(client.get("/api/games", headers={"X-Organiser-Password": "sesame"}).json()) == 1
        # Players need only the link.
        game = made.json()["game"]
        assert client.get(f"/api/games/{game}").status_code == 200
        assert client.post(f"/api/games/{game}/join", json={"seat": 0, "nickname": "Ann"}).status_code == 200


def test_without_an_organiser_password_the_local_server_stays_open(tmp_path):
    with TestClient(create_app(db=tmp_path / "g.sqlite")) as client:
        assert client.get("/api/options").json()["organiser_required"] is False
        assert client.post("/api/games", json=_body()).status_code == 200
        assert client.get("/api/games").status_code == 200


def test_the_deployed_server_refuses_to_start_without_an_organiser_password(monkeypatch):
    monkeypatch.delenv("NV_ORGANISER_PASSWORD", raising=False)
    with pytest.raises(SystemExit):
        main(["--storage", "firestore"])


# The credits page (specification 7.2) ----------------------------------------------------------------
def test_the_credits_page_shows_the_credits_document_and_every_page_links_to_it(tmp_path):
    with TestClient(create_app(db=tmp_path / "g.sqlite")) as client:
        assert client.get("/credits").status_code == 200
        assert client.get("/api/credits").text == (REPO_ROOT / "docs" / "credits.md").read_text(encoding="utf-8")
    for page in ("index.html", "game.html", "debrief.html"):
        assert 'href="/credits"' in (REPO_ROOT / "web" / page).read_text(encoding="utf-8"), page


# The board (specification 7.4) -------------------------------------------------------------------
def test_the_game_page_can_load_the_board_scripts_and_the_tile_colours(tmp_path):
    page = (REPO_ROOT / "web" / "game.html").read_text(encoding="utf-8")
    with TestClient(create_app(db=tmp_path / "g.sqlite")) as client:
        for script in ("strips.js", "tasks.js", "game.js"):
            assert f'src="/web/{script}"' in page, script
            assert client.get(f"/web/{script}").status_code == 200, script
        assert client.get("/web/icons/venus_expedition/colours.json").status_code == 200


def test_every_page_loads_the_themes_and_everything_they_refer_to(tmp_path):
    """Specification 7.4, Look: both themes on every page; their fonts and images are served."""
    import re

    web = REPO_ROOT / "web"
    css = (web / "themes.css").read_text(encoding="utf-8")
    assert "html.theme-light" in css and "html.theme-dark" in css
    referred = set(re.findall(r'url\("(/web/[^"]+)"\)', css))
    assert any(r.endswith(".woff2") for r in referred) and any(r.endswith(".png") for r in referred)
    with TestClient(create_app(db=tmp_path / "g.sqlite")) as client:
        for page in ("game.html", "index.html", "debrief.html", "credits.html"):
            text = (web / page).read_text(encoding="utf-8")
            assert 'class="theme-light"' in text, page  # the default look, even before a script runs
            assert 'href="/web/themes.css"' in text and 'src="/web/theme.js"' in text, page
        for address in ("/web/themes.css", "/web/theme.js", *sorted(referred)):
            assert client.get(address).status_code == 200, address


def test_the_phase_bar_names_every_step_of_the_engine_in_order():
    """Specification 7.4, Phase bar: a step the client does not know would leave the bar unmarked."""
    import re

    from nv_core.engine import ORDER

    script = (REPO_ROOT / "web" / "game.js").read_text(encoding="utf-8")
    block = script[script.index("const ROUND_PHASES = [") : script.index("const STEP_ORDER")]
    lists = re.findall(r'\["[^"]+",\s*\[(.*?)\]\]', block, flags=re.S)  # the steps of each phase
    named = [text for steps in lists for text in re.findall(r'"([^"]+)"', steps)]
    assert named == [phase.value for phase in ORDER]


# Deployment: the API key never leaves this computer in the upload or the container -----------------
def test_the_deployment_files_keep_local_secrets_out():
    for name in (".dockerignore", ".gcloudignore"):
        lines = (REPO_ROOT / name).read_text(encoding="utf-8").splitlines()
        assert "settings/api_keys.env" in lines and "settings/ai_spending.csv" in lines and "games/" in lines, name
    copies = [line.split()[1] for line in (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines() if line.startswith("COPY")]
    assert "." not in copies and "settings" not in copies and "settings/" not in copies

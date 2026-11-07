"""Specification 5.3 (legal_actions) and 9 (random bot, simulator, CSV outputs), section 13
(milestone 3: games finish without errors or broken invariants)."""

import csv
import json

import pytest

from nv_core import actions as a
from nv_core.engine import apply, legal_actions, new_game, validate
from nv_sim import invariants
from nv_sim.bots import RandomBot
from nv_sim.game import play_game, theory_truth
from nv_sim.run import main, wilson
from nv_world.game import load_game_world
from tests.core.engine_helpers import settings, tiny_world

WORLD_FILE = "scenarios/venus_expedition/worlds/world_seed1.json"


@pytest.fixture(scope="module")
def venus():
    world, game_settings, _ = load_game_world(WORLD_FILE)
    return world, game_settings


@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_random_bot_games_finish_without_errors(venus, n):
    world, game_settings = venus
    for seed in range(3):
        report = play_game(world, game_settings, seed, ["random"] * n)
        assert report.errors == [], report.errors
        assert report.game["ending"] in ("nobel", "crisis_crash", "credit")
        assert report.rounds and report.rounds[-1]["round"] == report.game["rounds"]


def test_same_seed_same_game(venus):
    world, game_settings = venus
    first = play_game(world, game_settings, 9, ["random"] * 3, keep_record=True)
    second = play_game(world, game_settings, 9, ["random"] * 3, keep_record=True)
    assert first.game == second.game
    assert first.record.actions == second.record.actions
    # and the record replays to the same end
    assert first.record.replay().result == first.record.replay().result
    assert first.record.replay().result.ending == first.game["ending"]


def test_same_seed_same_game_in_processes_with_different_string_hashing():
    """Specification 9.2: any game can be replayed from its seed, also in another process.
    Python orders sets of strings differently per process (PYTHONHASHSEED), so a game must
    never depend on such an order."""
    import os
    import subprocess
    import sys

    script = (
        "from nv_world.game import load_game_world\n"
        "from nv_sim.game import play_game\n"
        f"world, s, _ = load_game_world({WORLD_FILE!r})\n"
        # seed 1460604636 with 3 players showed a set-order bug in the random bot
        "rows = [play_game(world, s, seed, ['random'] * 3).game for seed in (1460604636, *range(8))]\n"
        "print(repr([(r['rounds'], r['actions'], r['ending'], r['credit_1'], r['credit_3']) for r in rows]))\n"
    )
    outputs = set()
    for hash_seed in ("1", "2", "3"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, check=True)
        outputs.add(result.stdout.strip())
    assert len(outputs) == 1, outputs


def _states_of_a_game(world, game_settings, seed, n=3, every=5):
    """States along one random-bot game, sampled every few actions."""
    bots = [RandomBot(f"{seed}/{i}") for i in range(n)]
    state = new_game(world, game_settings, seed, [f"p{i}" for i in range(n)])
    states = []
    while state.result is None and len(states) < 400:
        seat = state.current if state.current is not None else state.waiting[0]
        options = legal_actions(state, seat)
        action = bots[seat].choose({"round": state.round, "phase": state.phase.value, "seat": seat}, options)
        state, _ = apply(state, action)
        states.append(state)
    return states[::every]


def test_every_complete_legal_action_is_legal_and_listing_does_not_change_the_state(venus):
    """Specification 5.3: legal_actions lists what a player may do now."""
    world, game_settings = venus
    checked = 0
    for state in _states_of_a_game(world, game_settings, seed=4):
        before = state.model_dump()
        for seat in range(state.n_players):
            for option in legal_actions(state, seat):
                for action in option.actions[:15]:
                    assert validate(state, action) is None, (state.phase, option.type, action)
                    checked += 1
        assert state.model_dump() == before
    assert checked > 100


def test_commit_listed_exactly_when_it_is_legal(venus):
    world, game_settings = venus
    for state in _states_of_a_game(world, game_settings, seed=6):
        for seat in state.waiting:
            listed = any(o.type == "commit" for o in legal_actions(state, seat))
            assert listed == (validate(state, a.CommitPhase(seat=seat)) is None)


def test_invariants_catch_broken_states():
    state = new_game(tiny_world(), settings(), 1, ["a", "b"])
    assert invariants.check(state, {}) == []
    broken = state.clone()
    broken.researchers[0].money = -1
    broken.input_decks["IP1"].pop()
    problems = invariants.check(broken, {})
    assert any("negative money" in p for p in problems)
    assert any("Input Parameter Deck IP1" in p for p in problems)
    stuck = state.clone()
    stuck.waiting, stuck.current = [], None
    assert any("nobody to act" in p for p in invariants.check(stuck, {}))


def test_theory_truth_on_the_tiny_world():
    """Specification 4.3 coverage and accuracy; in the tiny world WO1 = up exactly when IP1 = a."""
    world = tiny_world()
    assert theory_truth(world, {"IP1": "a"}, {"WO1": "up"}) == (1.0, 0.5)
    assert theory_truth(world, {"IP2": "x"}, {"WO1": "up"}) == (0.5, 0.5)


def test_wilson_interval():
    low, high = wilson(50, 100)
    assert low == pytest.approx(0.4038, abs=1e-3) and high == pytest.approx(0.5962, abs=1e-3)
    assert wilson(0, 10)[0] == 0.0


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_nv_sim_run_writes_csvs_and_record_rebuilds_a_game(tmp_path, capsys):
    """Specification 9.2 and 9.3: CSV outputs; any game can be replayed from its seed."""
    out = tmp_path / "run"
    code = main(["run", "--players", "3", "--games", "3", "--seed", "5", "--world", WORLD_FILE,
                 "--sweep", "nobel_condition=4,6", "--jobs", "2", "--out", str(out)])
    assert code == 0
    for name in ("games.csv", "rounds.csv", "theories.csv", "predictions.csv", "worlds.csv"):
        assert (out / name).exists()
    games = _read(out / "games.csv")
    assert len(games) == 6 and {g["nobel_condition"] for g in games} == {"4", "6"}
    assert all(g["error"] == "" for g in games)
    assert len(_read(out / "worlds.csv")) == 1
    assert "median game length" in capsys.readouterr().out

    # The same run in one process gives the same games (determinism across processes).
    again = tmp_path / "again"
    main(["run", "--players", "3", "--games", "3", "--seed", "5", "--world", WORLD_FILE,
          "--sweep", "nobel_condition=4,6", "--jobs", "1", "--out", str(again)])
    assert _read(again / "games.csv") == games

    save = tmp_path / "game2.json"
    assert main(["record", str(out), "2", "--save", str(save)]) == 0
    record = json.loads(save.read_text(encoding="utf-8"))
    assert record["seed"] == int(games[1]["seed"])
    from nv_core.record import GameRecord

    state = GameRecord.load(save).replay()
    assert state.result.ending == games[1]["ending"] and str(state.round) == games[1]["rounds"]


def test_nv_sim_rejects_unknown_seat_types(tmp_path, capsys):
    assert main(["run", "--players", "2", "--seats", "random,wizard", "--games", "1", "--out", str(tmp_path)]) == 2
    assert "unknown seat type" in capsys.readouterr().err


def test_fresh_world_per_game(tmp_path):
    out = tmp_path / "fresh"
    assert main(["run", "--players", "2", "--games", "2", "--seed", "1", "--jobs", "1", "--out", str(out)]) == 0
    games = _read(out / "games.csv")
    worlds = _read(out / "worlds.csv")
    assert len({g["world"] for g in games}) == 2 and len(worlds) == 2
    assert all(g["world"].startswith("generated_seed") for g in games)


def test_game_rows_have_the_specified_columns(venus):
    """Specification 9.3, key columns."""
    world, game_settings = venus
    report = play_game(world, game_settings, 3, ["random"] * 2)
    for column in ("seed", "world", "seats", "rounds", "crisis_start_round", "ending", "winners", "credit_1", "ai_cost"):
        assert column in report.game
    for column in ("staff_1", "money_1", "credit_1", "papers_published", "predictions_made", "predictions_revealed"):
        assert column in report.rounds[0]
    if report.predictions:
        assert {"theory", "probe", "preregistered", "revealed", "success", "experiment_knowledge_of_failure"} <= set(report.predictions[0])
    if report.theories:
        assert {"author", "tier", "true_accuracy", "coverage", "successes", "failures", "highest_nobel", "retracted"} <= set(report.theories[0])


def test_nv_sim_import_opens_a_simulated_game_in_the_server(tmp_path, capsys):
    """Specification 9.2 and 7.3: a simulated game can be imported into the server's database and
    opened like any finished game (spectator replay, debrief)."""
    from fastapi.testclient import TestClient

    from nv_server.app import create_app

    out, db = tmp_path / "run", tmp_path / "games.sqlite"
    assert main(["run", "--players", "3", "--seats", "selfish,cooperative,random", "--games", "1", "--seed", "8",
                 "--world", WORLD_FILE, "--jobs", "1", "--out", str(out)]) == 0
    game = _read(out / "games.csv")[0]
    capsys.readouterr()
    assert main(["import", str(out), "1", "--db", str(db)]) == 0
    printed = capsys.readouterr().out
    link = next(line.strip() for line in printed.splitlines() if "#host=" in line)
    game_id, host = link.split("/game/")[1].split("#host=")
    with TestClient(create_app(db=db)) as client:
        info = client.get(f"/api/games/{game_id}").json()
        assert info["status"] == "finished" and [s["kind"] for s in info["seats"]] == ["selfish", "cooperative", "random"]
        debrief = client.post(f"/api/games/{game_id}/debrief", json={}).json()
        assert debrief["ending"]["ending"] == game["ending"] and debrief["ending"]["round"] == int(game["rounds"])
        assert debrief["real_world"]["main_effects"]
        replay = client.post(f"/api/games/{game_id}/replay", json={"host_token": host, "at": 10**6}).json()
        assert replay["at"] == replay["total"] and replay["problem"] == "" and replay["view"]["result"]["ending"] == game["ending"]

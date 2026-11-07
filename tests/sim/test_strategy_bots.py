"""Specification 9.4 (scripted strategy bots) and section 13 (milestone 4: every bot type finishes
games without errors or broken invariants)."""

import pytest

from nv_core import actions as a
from nv_sim.game import check_seat_types, play_game
from nv_sim.run import main
from nv_sim.strategy import SEAT_TYPES, BotSettings, StrategyBot
from nv_world.game import load_game_world

WORLD_FILE = "scenarios/venus_expedition/worlds/world_seed1.json"


@pytest.fixture(scope="module")
def venus():
    world, settings, _ = load_game_world(WORLD_FILE)
    return world, settings


def _watch(venus, seats, seed):
    """Play a game and collect (state after, seat, action) for every action."""
    world, settings = venus
    seen = []
    report = play_game(world, settings, seed, seats, on_action=lambda st, seat, act, ev: seen.append((st, seat, act)))
    return report, seen


def test_bot_settings_come_from_the_software_settings():
    bot = BotSettings.load()
    assert 0 < bot.confidence_threshold < 1 and bot.kill_counter >= 0 and bot.max_wait_rounds > 0


@pytest.mark.parametrize("kind", SEAT_TYPES)
def test_every_bot_type_finishes_games_without_errors(venus, kind):
    world, settings = venus
    for seed, n in ((1, 2), (2, 3), (3, 4)):
        report = play_game(world, settings, seed, [kind] * n)
        assert report.errors == [], report.errors
        assert report.game["ending"] in ("nobel", "crisis_crash", "credit")


def test_mixed_tables_with_random_bots_finish(venus):
    world, settings = venus
    report = play_game(world, settings, 5, ["selfish", "cooperative", "patient-selfish", "random"])
    assert report.errors == [], report.errors


def test_same_seed_same_game(venus):
    world, settings = venus
    seats = ["selfish", "cooperative", "patient-cooperative"]
    first = play_game(world, settings, 8, seats, keep_record=True)
    second = play_game(world, settings, 8, seats, keep_record=True)
    assert first.record.actions == second.record.actions


def test_same_game_in_processes_with_different_string_hashing():
    import os
    import subprocess
    import sys

    script = (
        "from nv_world.game import load_game_world\n"
        "from nv_sim.game import play_game\n"
        f"world, s, _ = load_game_world({WORLD_FILE!r})\n"
        "rows = [play_game(world, s, seed, ['selfish', 'cooperative', 'patient-selfish']).game for seed in range(3)]\n"
        "print(repr([(r['rounds'], r['actions'], r['ending'], r['credit_1'], r['credit_2']) for r in rows]))\n"
    )
    outputs = set()
    for hash_seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, check=True)
        outputs.add(result.stdout.strip())
    assert len(outputs) == 1, outputs


def test_bots_remember_every_probe_they_saw(venus):
    """A bot watches the board through the events, whether or not it has to decide: a waiting
    patient bot remembers every Probe of every round."""
    from nv_core.views import visible_events

    world, settings = venus
    watcher = StrategyBot(4, "patient-selfish", world, settings, BotSettings.load())
    report = play_game(
        world, settings, 4, ["patient-selfish", "selfish"],
        on_action=lambda st, seat, act, events: watcher.observe(visible_events(events, 0)),
    )
    probes = 2 + 1
    assert len(watcher.memory) >= (report.game["rounds"] - 1) * probes
    assert all(set(outcomes) == set(watcher.outcomes) for _, outcomes in watcher.memory)


def test_selfish_bots_never_install_sensors_and_vote_revise_except_on_their_own(venus):
    for seed in (1, 2):
        report, seen = _watch(venus, ["selfish"] * 3, seed)
        assert not any(isinstance(act, a.InstallSensor) for _, _, act in seen)
        for state, seat, act in seen:
            if isinstance(act, a.ReviewVote):
                position = state.review_cards[seat][act.card]
                manuscript = next(m for m in state.manuscripts if m.position == position and m.area == "review")
                assert act.vote == ("accept" if manuscript.author == seat else "revise")


def test_cooperative_bots_always_preregister_and_never_reveal_hidden_predictions(venus):
    for seed in (1, 2):
        report, seen = _watch(venus, ["cooperative"] * 3, seed)
        makes = [act for _, _, act in seen if isinstance(act, a.MakePrediction)]
        assert makes and all(m.preregister for m in makes)
        assert not any(isinstance(act, a.RevealPrediction) for _, _, act in seen)


def test_selfish_bots_reveal_only_successes_or_failures_of_rival_nobel_candidates(venus):
    kill = BotSettings.load().kill_counter
    for seed in (1, 2, 3):
        report, seen = _watch(venus, ["selfish"] * 3, seed)
        for state, seat, act in seen:
            if isinstance(act, a.RevealPrediction) and act.reveal:
                p = next(x for x in state.predictions if x.id == act.prediction)
                paper = state.paper(p.cited)
                assert p.success or (paper.author != seat and paper.nobel >= kill)


def test_patient_bots_hire_nobody_while_they_wait(venus):
    report, seen = _watch(venus, ["patient-cooperative"] * 3, 2)
    first = [act for state, _, act in seen if isinstance(act, a.AllocateStaff) and state.round == 1]
    assert first and all(act.hire_postdocs == 0 and act.hire_students == 0 and not act.allocation for act in first)


def test_patient_bots_wake_up_at_the_latest_after_the_wait_limit(venus):
    world, settings = venus
    bot = StrategyBot(1, "patient-selfish", world, settings, BotSettings.load())
    limit = bot.bot.max_wait_rounds
    assert not bot._wakes({"round": limit, "warning_revealed": False})  # nothing seen: not confident
    assert bot._wakes({"round": limit, "warning_revealed": True})
    assert bot._wakes({"round": limit + 1, "warning_revealed": False})


def test_memory_corruption_changes_remembered_readings(venus):
    world, settings = venus
    sharp = StrategyBot(1, "selfish", world, settings, BotSettings.load())
    fuzzy = StrategyBot(1, "selfish", world, settings, BotSettings(**{**BotSettings.load().__dict__, "memory_corruption": 1.0}))
    readings = {v: states[0] for v, states in sharp.inputs.items()}
    outcomes = {v: states[0] for v, states in sharp.outcomes.items()}
    for bot in (sharp, fuzzy):
        for _ in range(20):
            bot.memory.append((dict(readings), dict(outcomes)))
        for _ in range(3):
            bot._forget()
    assert all(r == readings for r, _ in sharp.memory)
    assert any(r != readings for r, _ in fuzzy.memory)


def test_seat_types_are_accepted_by_nv_sim(tmp_path):
    check_seat_types(list(SEAT_TYPES))
    out = tmp_path / "bots"
    assert main(["run", "--players", "3", "--seats", "selfish,cooperative,patient-selfish", "--games", "2",
                 "--world", WORLD_FILE, "--jobs", "1", "--out", str(out)]) == 0

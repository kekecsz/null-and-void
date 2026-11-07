"""Specification section 10 (end-of-game debrief) and 5.1 (hidden bookkeeping for the debrief),
on complete games played by the scripted bots."""

import json

import pytest

from nv_core.debrief import build_debrief, csv_tables
from nv_sim.game import play_game
from nv_world.game import load_game_world

WORLD_FILE = "scenarios/venus_expedition/worlds/world_seed1.json"


def _play(seats, seed, **settings_changes):
    world, settings, _ = load_game_world(WORLD_FILE)
    settings = settings.model_copy(update=settings_changes)
    final, events = {}, []

    def watch(state, seat, action, new_events):
        final["state"] = state
        events.extend(new_events)

    report = play_game(world, settings, seed, seats, on_action=watch)
    assert report.errors == [], report.errors
    return final["state"], events


@pytest.fixture(scope="module")
def crash_game():
    return _play(["selfish", "selfish", "cooperative"], 3)


def test_bookkeeping_keeps_every_publication_and_round(crash_game):
    """Specification 5.1: the hidden bookkeeping keeps every published paper (retracted ones too),
    every peer review decision and the standings after every round."""
    state, events = crash_game
    logged = {entry.paper for entry in state.paper_log}
    assert {p.id for p in state.published} <= logged
    assert {e.data["paper"] for e in events if e.kind == "published"} == logged
    assert len(state.review_log) == sum(1 for e in events if e.kind == "review_decision")
    assert [log.round for log in state.round_log] == list(range(1, len(state.round_log) + 1))
    assert all(p.readings for p in state.prediction_log)


def test_debrief_literature_against_the_truth(crash_game):
    """Specification 10, The literature vs. the truth: every published theory with its author,
    tier, observed success rate and true accuracy (World Table)."""
    state, events = crash_game
    debrief = build_debrief(state, events, low_chance=0.5)
    theories = [e for e in state.paper_log if e.idea.kind == "theory"]
    assert [t["theory"] for t in debrief["literature"]] == [e.paper for e in theories]
    for row, entry in zip(debrief["literature"], theories):
        assert row["author"] == state.players[entry.author]
        assert row["true_accuracy"] == state.world.theory_truth(entry.idea.inputs, entry.idea.outcomes)[0]
        assert row["successes"] + row["failures"] == sum(
            1 for p in [*state.prediction_log, *state.predictions] if p.status == "scored" and p.cited == entry.paper
        )  # the round the game ended in is not in the log yet


def test_debrief_crisis_crash_lists_every_unsuccessful_prediction(crash_game):
    """Specification 10, How it ended: a Crisis Crash with the failures that caused it."""
    state, events = crash_game
    debrief = build_debrief(state, events, low_chance=0.5)
    assert debrief["ending"]["ending"] == "crisis_crash"
    assert len(debrief["ending"]["crisis"]["unsuccessful"]) == state.unsuccessful_predictions
    ranking = [r["credit"] for r in debrief["ending"]["ranking"]]
    assert ranking == sorted(ranking, reverse=True)


def test_debrief_totals_panels_name_nobody(crash_game):
    """Specification 10: fabrication, file drawer and peer review show totals only."""
    state, events = crash_game
    debrief = build_debrief(state, events, low_chance=0.5)
    for panel in ("fabrication", "file_drawer", "peer_review"):
        text = json.dumps(debrief[panel])
        assert not any(name in text for name in state.players), panel
    drawer = debrief["file_drawer"]
    assert drawer["never_revealed"] == sum(1 for p in state.prediction_log if p.status == "discarded")
    assert set(csv_tables(debrief)) >= {"literature", "credit_by_round", "totals"}


@pytest.mark.parametrize("threshold", [0.5, 0.3])
def test_debrief_luck_uses_the_threshold(crash_game, threshold):
    """Specification 10, Luck: successes with a true chance below debrief_low_chance, and
    failures of theories with a true chance above 1 - debrief_low_chance."""
    state, events = crash_game
    luck = build_debrief(state, events, low_chance=threshold)["luck"]
    assert all(x["true_accuracy"] < threshold for x in luck["lucky_successes"])
    assert all(x["true_accuracy"] > 1 - threshold for x in luck["unlucky_failures"])


def test_debrief_over_time_ends_with_the_final_credit(crash_game):
    """Specification 10, Over time: academic credit per researcher by round."""
    state, events = crash_game
    over = build_debrief(state, events, low_chance=0.5)["over_time"]
    assert over["rounds"][-1] == state.round
    assert [c["values"][-1] for c in over["credit"]] == [r.credit for r in state.researchers]


def test_debrief_nobel_prize_with_its_streak():
    """Specification 10, How it ended: the Nobel Prize theory, its streak and the chance of it."""
    for seed in range(1, 15):
        state, events = _play(["selfish", "selfish", "selfish"], seed, nobel_condition=2)
        if state.result.ending == "nobel":
            break
    else:
        pytest.skip("no Nobel Prize in these games")
    nobel = build_debrief(state, events, low_chance=0.5)["ending"]["nobel"]
    assert nobel["theory"] == state.result.theory
    assert len(nobel["streak"]) >= 2
    assert nobel["chance"] == pytest.approx(nobel["true_accuracy"] ** len(nobel["streak"]))


def test_debrief_of_a_game_begun_before_the_bookkeeping(crash_game):
    """A game resumed partway with the bookkeeping: still-published papers are listed, and the
    debrief says that its history is incomplete."""
    state, events = crash_game
    older = state.model_copy(deep=True)
    older.paper_log = older.paper_log[len(older.paper_log) // 2:]
    older.round_log = older.round_log[3:]
    debrief = build_debrief(older, events, low_chance=0.5)
    assert {p.id for p in older.published if p.kind == "theory"} <= {t["theory"] for t in debrief["literature"]}
    assert not debrief["bookkeeping_recorded"]
    assert build_debrief(state, events, low_chance=0.5)["bookkeeping_recorded"]

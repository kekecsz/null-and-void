"""Phase reports (specification 7.4): the engine collects each part of the round's events into a
report for the web client, with their visibility, and the academic credit before and after."""

import pytest

from nv_core import actions as a
from nv_core.state import GameState, Phase, StaffCount, Task
from nv_core.views import player_view, spectator_view
from nv_sim.game import play_game
from nv_world.game import load_game_world
from tests.core.engine_helpers import do, game, settings

S = settings()
WORLD_FILE = "scenarios/venus_expedition/worlds/world_seed1.json"


@pytest.fixture(scope="module")
def mid_game() -> GameState:
    """A state of a bot game once every part of the round has made a report at least once."""
    world, game_settings, _ = load_game_world(WORLD_FILE)
    seen: dict = {}

    def watch(state, seat, action, events):
        if "state" not in seen and state.round >= 4 and all(
            state.reports.get(name) for name in ("hiring", "experimentation", "publication", "cleanup")
        ):
            seen["state"] = state

    report = play_game(world, game_settings, 4, ["cooperative", "selfish", "cooperative"], on_action=watch)
    assert not report.errors
    return seen["state"]


def test_hiring_report_after_the_student_task_check_with_staff_and_credit():
    state = game()
    for r in state.researchers:
        r.postdocs, r.money = 2, 10 * S.cost_of_postdoc
    state = do(
        state,
        a.AllocateStaff(seat=0, fire_postdocs=1, allocation={Task.GRANTS: StaffCount(postdocs=1)}),
        a.CommitPhase(seat=0),
        a.AllocateStaff(seat=1, allocation={Task.GRANTS: StaffCount(postdocs=2)}),
        a.CommitPhase(seat=1),
    )
    assert state.phase not in (Phase.HIRING, Phase.LAST_CHANCE, Phase.STUDENT_CHECK)
    report = player_view(state, 1)["reports"]["hiring"]
    allocations = {i["seat"]: i["data"] for i in report["items"] if i["kind"] == "allocation"}
    assert allocations[0]["fired_postdocs"] == 1 and allocations[1]["staff"] == {"grants": [2, 0]}
    assert any(i["kind"] == "period_deck" and i["seat"] is None for i in report["items"])
    fired = [c for c in report["credits"] if c["seat"] == 0]
    assert [c["amount"] for c in fired] == [S.fired_postdoc_penalty]
    assert report["after"][0] == report["before"][0] + S.fired_postdoc_penalty


def test_every_part_of_the_round_reports_and_the_prediction_events_are_left_out(mid_game):
    reports = player_view(mid_game, 0)["reports"]
    assert set(reports) == {"hiring", "experimentation", "publication", "cleanup"}
    kinds = {name: {i["kind"] for i in report["items"]} for name, report in reports.items()}
    assert "allocation" in kinds["hiring"]
    assert "funding" in kinds["cleanup"]
    for name in kinds:
        assert not kinds[name] & {"scored", "revealed", "preregistered", "commit", "credit"}, name


def test_a_researcher_sees_only_their_own_private_lines(mid_game):
    everything = spectator_view(mid_game)["reports"]
    private = [(name, i["seat"]) for name, report in everything.items() for i in report["items"]
               if i["kind"] in ("experiment_result", "development_private", "archive_private")]
    assert private, "the bot game should have run an experiment or developed something"
    for seat in range(mid_game.n_players):
        mine = player_view(mid_game, seat)["reports"]
        for name, report in mine.items():
            for item in report["items"]:
                assert "visible_to" not in item
                if item["kind"] in ("experiment_result", "development_private", "archive_private"):
                    assert item["seat"] == seat, (name, item)


def test_a_game_saved_before_the_reports_still_loads():
    state = game()
    data = state.model_dump(mode="json")
    for name in ("reports", "report_events", "report_credit"):
        del data[name]
    loaded = GameState.model_validate(data)
    assert loaded.reports == {} and loaded.report_events == []

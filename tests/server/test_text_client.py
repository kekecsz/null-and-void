"""Text client (specification section 7.1): commands parse into actions; a local game runs."""

import pytest

from nv_core import actions as a
from nv_core.record import GameRecord
from nv_core.state import StaffCount, Task
from nv_server.commands import CommandError, parse
from nv_server.text_client import TextClient, main
from tests.core.engine_helpers import game, settings, tiny_world


@pytest.fixture
def state():
    return game()


def test_parse_commands(state):
    assert parse(state, 0, "allocate hire=2 students=1 dev=1p exp=1p1s") == a.AllocateStaff(
        seat=0,
        hire_postdocs=2,
        hire_students=1,
        allocation={Task.DEVELOPMENT: StaffCount(postdocs=1), Task.EXPERIMENTATION: StaffCount(postdocs=1, students=1)},
    )
    assert parse(state, 1, "experiment ip1=A IP2=x cite M3 M5") == a.RunExperiment(
        seat=1, specified={"IP1": "a", "IP2": "x"}, cited_methods=[3, 5]
    )
    assert parse(state, 0, "sensor P2 IP3 cite M4") == a.InstallSensor(seat=0, probe=1, parameter="IP3", cited_methods=[4])
    assert parse(state, 0, "predict T7 P3 prereg") == a.MakePrediction(seat=0, theory=7, probe=2, preregister=True)
    assert parse(state, 0, "theory IP1=a -> WO1=u") == a.FormulateTheory(seat=0, inputs={"IP1": "a"}, outcomes={"WO1": "up"})
    submit = parse(state, 0, "submit D5 tier 2 records O12 E9 E10:IP1,IP2/E11:IP3,WO1 apc")
    assert submit.pay_apc and submit.tier == 2 and submit.manuscript == 5
    assert submit.records[0] == a.ObservationRecord(observation=12)
    assert submit.records[1] == a.ExperimentRecord(cards=[(9, "IP1"), (9, "IP2"), (9, "IP3"), (9, "WO1")])
    assert submit.records[2] == a.ExperimentRecord(cards=[(10, "IP1"), (10, "IP2"), (11, "IP3"), (11, "WO1")])
    assert parse(state, 0, "vote 2 revise") == a.ReviewVote(seat=0, card=1, vote="revise")
    assert parse(state, 0, "ally r1") == a.ProposeAlliance(seat=0, partner=1)
    assert parse(state, 0, "done") == a.CommitPhase(seat=0)


@pytest.mark.parametrize("line", ["experiment IP1=zzz", "allocate dev=3x", "frobnicate", "predict T7"])
def test_parse_errors_explain(state, line):
    with pytest.raises(CommandError):
        parse(state, 0, line)


def test_client_plays_and_saves(tmp_path):
    out: list[str] = []
    record = GameRecord(world=tiny_world(), settings=settings(), seed=4, players=["Ann", "Bob"])
    save = tmp_path / "g.json"
    client = TextClient(record, save, out.append)
    client.run(
        [
            "as Ann",
            "allocate hire=1 exp=1p",
            "commit",
            "as Bob",
            "allocate hire=1 exp=1p",
            "commit",
            "nonsense",
        ]
    )
    text = "\n".join(out)
    assert "unknown command" in text
    assert client.state.phase.value == "Experimentation and equipment phase"
    assert len(GameRecord.load(save).actions) == 4
    resumed = TextClient(GameRecord.load(save), None, out.append)
    assert resumed.state.model_dump() == client.state.model_dump()


def test_nv_play_new_and_load(tmp_path, monkeypatch, capsys):
    save = tmp_path / "g.json"
    script = tmp_path / "s.txt"
    script.write_text("allocate exp=1p hire=1\ncommit\nquit\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": "quit")
    world = "scenarios/venus_expedition/worlds/world_seed1.json"
    assert main(["new", world, "--players", "Ann,Bob", "--seed", "2", "--save", str(save), "--script", str(script)]) == 0
    assert "WORLD GRID" in capsys.readouterr().out
    assert main(["load", str(save)]) == 0
    assert len(GameRecord.load(save).actions) == 2

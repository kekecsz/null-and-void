"""Specification 6 (server: persistence, live updates, joining, host controls, security) and
section 13 (milestone 5: games finish in the browser against bots and AI seats, a refreshed
browser rejoins its seat, a paused game resumes after a restart)."""

import pytest
from fastapi.testclient import TestClient

from nv_core.engine import Option
from nv_core.state import GameState
from nv_server.app import create_app
from nv_server.storage import SQLiteStorage
from nv_sim.bots import RandomBot

WORLD = "venus_expedition/worlds/world_seed1.json"


@pytest.fixture
def db(tmp_path):
    return tmp_path / "games.sqlite"


def _create(client, seats, **extra):
    body = {"world": WORLD, "seats": seats, "seed": 5, **extra}
    response = client.post("/api/games", json=body)
    assert response.status_code == 200, response.text
    return response.json()["game"], response.json()["host_token"]


def _join(client, game, seat, nickname, password=""):
    response = client.post(f"/api/games/{game}/join", json={"seat": seat, "nickname": nickname, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["seat_token"]


def _host(client, game, host, command, **extra):
    return client.post(f"/api/games/{game}/host/{command}", json={"host_token": host, **extra})


def _must_act(msg):
    v = msg["view"]
    return msg["status"] == "running" and v and v["result"] is None and (v["current"] == msg["you"] or msg["you"] in v["waiting"])


def _play(ws, seed=1, max_messages=60000, stop=None):
    """Play the seat of this socket with the random bot, the way a browser would, until the game
    ends (or ``stop(msg)``). After sending an action it waits for the server's answer, and then
    acts only on views at least as new as that answer."""
    bot = RandomBot(seed)
    last, pending, newest = None, False, 0
    for _ in range(max_messages):
        msg = ws.receive_json()
        if msg["type"] == "state":
            last = msg
            if msg["view"] and msg["view"]["result"] is not None:
                return msg
            if stop and stop(msg):
                return msg
        elif msg["type"] == "accepted":
            pending, newest = False, msg["seq"]
        elif msg["type"] == "error":
            pending = False
        if last is None or pending or last["seq"] < newest or not _must_act(last):
            continue
        options = [Option.model_validate(o) for o in last["options"]]
        view = {"round": last["view"]["round"], "phase": last["view"]["phase"], "seat": last["you"]}
        action = bot.choose(view, options)
        ws.send_json({"type": "action", "action": action.model_dump(mode="json")})
        pending = True
    raise AssertionError("the game did not end")


# Storage -------------------------------------------------------------------------------------------
def test_actions_are_stored_only_under_the_next_number(tmp_path):
    storage = SQLiteStorage(tmp_path / "s.sqlite")
    storage.create_game("g", {"status": "lobby"})
    assert storage.append_action("g", 0, {"type": "commit", "seat": 0}, [])
    assert not storage.append_action("g", 0, {"type": "commit", "seat": 1}, [])  # someone else was first
    assert not storage.append_action("g", 2, {"type": "commit", "seat": 1}, [])
    assert storage.append_action("g", 1, {"type": "commit", "seat": 1}, [{"text": "x"}])
    assert [a["seat"] for a, _ in storage.actions("g")] == [0, 1]
    storage.save_snapshot("g", 1, "{}")
    assert storage.latest_snapshot("g") == (1, "{}")


# Lobby -------------------------------------------------------------------------------------------
def test_lobby_lists_worlds_and_seat_kinds(db):
    with TestClient(create_app(db=db)) as client:
        options = client.get("/api/options").json()
        assert any(w["file"] == WORLD for w in options["worlds"])
        assert {"human", "selfish", "cooperative", "random", "ai"} <= set(options["seat_kinds"])
        assert client.get("/").status_code == 200 and client.get("/game/x").status_code == 200


@pytest.mark.parametrize(
    "seats, extra, message",
    [
        ([{"kind": "human"}], {}, "seats"),
        ([{"kind": "human"}, {"kind": "wizard"}], {}, "unknown seat type"),
        ([{"kind": "human"}, {"kind": "selfish"}], {"overrides": "no_such_setting: 3"}, "unknown setting"),
        ([{"kind": "human"}, {"kind": "selfish"}], {"overrides": "nobel_condition: four"}, "nobel_condition"),
    ],
)
def test_bad_games_are_refused_with_a_reason(db, seats, extra, message):
    with TestClient(create_app(db=db)) as client:
        response = client.post("/api/games", json={"world": WORLD, "seats": seats, **extra})
        assert response.status_code == 400 and message in response.json()["detail"]


def test_settings_overrides_apply(db):
    with TestClient(create_app(db=db)) as client:
        game, _ = _create(client, [{"kind": "human"}, {"kind": "selfish"}], overrides="nobel_condition: 4")
        assert client.app.state.manager.storage.get_meta(game)["settings"]["nobel_condition"] == 4


def test_joining_needs_the_password_a_free_seat_and_a_nickname(db):
    with TestClient(create_app(db=db)) as client:
        game, host = _create(client, [{"kind": "human"}, {"kind": "human"}, {"kind": "selfish"}], join_password="secret")
        assert client.post(f"/api/games/{game}/join", json={"seat": 0, "nickname": "Ann", "password": "nope"}).status_code == 400
        _join(client, game, 0, "Ann", "secret")
        assert client.post(f"/api/games/{game}/join", json={"seat": 0, "nickname": "Bob", "password": "secret"}).status_code == 400
        assert client.post(f"/api/games/{game}/join", json={"seat": 2, "nickname": "Bob", "password": "secret"}).status_code == 400
        assert _host(client, game, host, "start").status_code == 400  # seat 2 (human) is still free
        assert _host(client, game, "wrong", "start").status_code == 403
        _join(client, game, 1, "Bob", "secret")
        assert _host(client, game, host, "start").status_code == 200
        meta = client.app.state.manager.storage.get_meta(game)
        assert meta["players"][:2] == ["Ann", "Bob"]
        assert "secret" not in str(meta) and all(len(h) == 64 for h in meta["seat_tokens"].values())


# Playing -------------------------------------------------------------------------------------------
def test_a_human_finishes_a_game_against_scripted_bots(db):
    with TestClient(create_app(db=db)) as client:
        game, host = _create(client, [{"kind": "human"}, {"kind": "selfish"}, {"kind": "cooperative"}])
        token = _join(client, game, 0, "Ann")
        assert _host(client, game, host, "start").status_code == 200
        with client.websocket_connect(f"/ws/{game}?seat_token={token}") as ws:
            final = _play(ws)
        assert final["view"]["result"]["ending"] in ("nobel", "crisis_crash", "credit")
        assert final["status"] == "finished"


def test_a_player_sees_only_their_own_lab(db):
    with TestClient(create_app(db=db)) as client:
        game, host = _create(client, [{"kind": "human"}, {"kind": "selfish"}])
        token = _join(client, game, 0, "Ann")
        _host(client, game, host, "start")
        with client.websocket_connect(f"/ws/{game}?seat_token={token}") as ws:
            msg = ws.receive_json()
        view = msg["view"]
        assert msg["you"] == 0 and view["lab"]["seat"] == 0
        assert "labs" not in view and "world_table" not in view and "probe_truth" not in view
        import json

        text = json.dumps(msg)  # the World Table and true Probe states never leave the server
        assert "world_table" not in text and "probe_truth" not in text and "main_effects" not in text
        assert all(p["outcomes"] is None for p in view["probes"])  # not revealed yet in the Hiring phase
        with client.websocket_connect(f"/ws/{game}?host_token={host}") as ws:
            hosted = ws.receive_json()  # specification 7.3: the host link spectates
        assert hosted["host"] and hosted["spectator"] and hosted["you"] is None and "world_table" in hosted["view"]


def test_a_refreshed_browser_rejoins_its_seat_and_strangers_are_turned_away(db):
    with TestClient(create_app(db=db)) as client:
        game, host = _create(client, [{"kind": "human"}, {"kind": "human"}])
        ann = _join(client, game, 0, "Ann")
        _join(client, game, 1, "Bob")
        _host(client, game, host, "start")
        with client.websocket_connect(f"/ws/{game}?seat_token={ann}") as ws:
            assert ws.receive_json()["you"] == 0
        with client.websocket_connect(f"/ws/{game}?seat_token={ann}") as ws:  # the same browser again
            assert ws.receive_json()["you"] == 0
        with client.websocket_connect(f"/ws/{game}?seat_token=made-up") as ws:
            assert ws.receive_json()["type"] == "error"


def test_actions_of_another_seat_are_refused(db):
    with TestClient(create_app(db=db)) as client:
        game, host = _create(client, [{"kind": "human"}, {"kind": "human"}])
        ann = _join(client, game, 0, "Ann")
        _join(client, game, 1, "Bob")
        _host(client, game, host, "start")
        with client.websocket_connect(f"/ws/{game}?seat_token={ann}") as ws:
            ws.receive_json()
            # the seat in the message is ignored: Ann's socket always acts for seat 0
            ws.send_json({"type": "action", "action": {"type": "commit", "seat": 1}})
            while (reply := ws.receive_json())["type"] == "state":
                pass
            assert reply["type"] == "accepted"
        assert [a["seat"] for a, _ in client.app.state.manager.storage.actions(game)] == [0]


def test_a_paused_game_resumes_after_a_server_restart(db):
    with TestClient(create_app(db=db)) as client:
        game, host = _create(client, [{"kind": "human"}, {"kind": "selfish"}, {"kind": "random"}])
        token = _join(client, game, 0, "Ann")
        _host(client, game, host, "start")
        with client.websocket_connect(f"/ws/{game}?seat_token={token}") as ws:
            mid = _play(ws, stop=lambda m: m["view"]["round"] >= 3)
        assert _host(client, game, host, "pause").status_code == 200
        with client.websocket_connect(f"/ws/{game}?seat_token={token}") as ws:
            paused = ws.receive_json()
            ws.send_json({"type": "action", "action": {"type": "commit"}})
            assert "paused" in ws.receive_json()["message"]
        stored = len(client.app.state.manager.storage.actions(game))

    # a new server process on the same file
    with TestClient(create_app(db=db)) as client:
        with client.websocket_connect(f"/ws/{game}?seat_token={token}") as ws:
            again = ws.receive_json()
        assert again["status"] == "paused" and again["seq"] == stored == paused["seq"]
        assert again["view"] == paused["view"] and again["events"] == paused["events"]
        assert _host(client, game, host, "resume").status_code == 200
        with client.websocket_connect(f"/ws/{game}?seat_token={token}") as ws:
            final = _play(ws, seed=2)
        assert final["view"]["result"] is not None and mid["view"]["round"] >= 3


def test_the_host_can_hand_a_seat_to_a_bot_and_back(db):
    with TestClient(create_app(db=db)) as client:
        game, host = _create(client, [{"kind": "human"}, {"kind": "human"}])
        ann = _join(client, game, 0, "Ann")
        _join(client, game, 1, "Bob")
        _host(client, game, host, "start")
        assert _host(client, game, host, "automate", seat=1, kind="cooperative").status_code == 200
        with client.websocket_connect(f"/ws/{game}?seat_token={ann}") as ws:
            mid = _play(ws, stop=lambda m: m["view"]["round"] >= 2)  # Bob's seat plays itself
            assert mid["seats"][1]["kind"] == "cooperative"
        assert _host(client, game, host, "release", seat=1).status_code == 200
        assert client.app.state.manager.storage.get_meta(game)["seats"][1] == "human"
        assert _host(client, game, host, "automate", seat=1, kind="wizard").status_code == 400


def test_a_human_finishes_a_game_against_an_ai_seat(db):
    """With a fake model (no API calls): the AI seat thinks in a background thread."""
    from nv_ai.config import Prices, load_software_settings
    from nv_ai.costs import Ledger
    from nv_sim.game import AIContext
    from tests.ai.test_ai_player import FakeProvider

    base = load_software_settings()
    software = base.model_copy(update={"ai_price_table": {**base.ai_price_table, "fake-model": Prices(
        input=0.1, cached_input=0.01, cache_write=0.125, output=0.5)}})
    context = AIContext(software, Ledger(None, software.ai_total_budget), FakeProvider)
    with TestClient(create_app(db=db, ai_context=lambda: context)) as client:
        game, host = _create(client, [{"kind": "human"}, {"kind": "ai"}])
        token = _join(client, game, 0, "Ann")
        _host(client, game, host, "start")
        with client.websocket_connect(f"/ws/{game}?seat_token={token}") as ws:
            final = _play(ws)
        assert final["view"]["result"] is not None
        meta = client.app.state.manager.storage.get_meta(game)
        assert meta["ai_cost"]["1"] > 0
        assert client.app.state.manager.storage.ai_decisions(game)


# Spectator mode, replay and debrief (specification 7.3 and 10; milestone 6) ------------------------
def _finished_game(client, **extra):
    """A finished game: a human seat played by the random bot, against two scripted bots."""
    game, host = _create(client, [{"kind": "human"}, {"kind": "selfish"}, {"kind": "cooperative"}], **extra)
    token = _join(client, game, 0, "Ann", extra.get("join_password", ""))
    _host(client, game, host, "start")
    with client.websocket_connect(f"/ws/{game}?seat_token={token}") as ws:
        _play(ws)
    return game, host, token


def test_spectators_see_the_hidden_world_only_with_the_password_or_the_host_link(db):
    with TestClient(create_app(db=db)) as client:
        game, host = _create(client, [{"kind": "human"}, {"kind": "selfish"}], spectator_password="watch")
        token = _join(client, game, 0, "Ann")
        _host(client, game, host, "start")
        with client.websocket_connect(f"/ws/{game}?spectate=1&spectator_password=watch") as ws:
            watched = ws.receive_json()
        assert watched["spectator"] and watched["view"]["world_table"] and len(watched["view"]["labs"]) == 2
        with client.websocket_connect(f"/ws/{game}?spectate=1&spectator_password=wrong") as ws:
            assert ws.receive_json()["type"] == "error"
        # A player may not spectate without the password; a host who also plays may switch.
        with client.websocket_connect(f"/ws/{game}?seat_token={token}&spectate=1") as ws:
            assert not ws.receive_json()["spectator"]
        with client.websocket_connect(f"/ws/{game}?seat_token={token}&host_token={host}&spectate=1") as ws:
            switched = ws.receive_json()
            assert switched["spectator"] and switched["you"] is None
            ws.send_json({"type": "action", "action": {"type": "commit"}})
            assert ws.receive_json()["type"] == "error"  # spectators do not play


def test_without_a_spectator_password_only_the_host_spectates(db):
    with TestClient(create_app(db=db)) as client:
        game, host = _create(client, [{"kind": "human"}, {"kind": "selfish"}])
        with client.websocket_connect(f"/ws/{game}?spectate=1&spectator_password=") as ws:
            assert ws.receive_json()["type"] == "error"
        assert client.post(f"/api/games/{game}/replay", json={"at": 0}).status_code == 403


def test_replay_steps_to_any_action_and_lists_the_rounds(db):
    with TestClient(create_app(db=db)) as client:
        game, host, _ = _finished_game(client)
        first = client.post(f"/api/games/{game}/replay", json={"host_token": host, "at": 0}).json()
        assert first["at"] == 0 and first["view"]["round"] == 1 and first["total"] > 0
        rounds = first["rounds"]
        assert rounds[0] == {"round": 1, "seq": 0} and [r["round"] for r in rounds] == list(range(1, len(rounds) + 1))
        second = rounds[1]
        at_round = client.post(f"/api/games/{game}/replay", json={"host_token": host, "at": second["seq"]}).json()
        assert at_round["view"]["round"] == 2 and at_round["problem"] == ""
        last = client.post(f"/api/games/{game}/replay", json={"host_token": host, "at": 10**6}).json()
        assert last["at"] == first["total"] and last["view"]["result"] is not None
        middle = client.post(f"/api/games/{game}/replay", json={"host_token": host, "at": second["seq"] + 3}).json()
        assert middle["at"] == second["seq"] + 3 and len(middle["events"]) >= len(at_round["events"])


def test_the_debrief_opens_for_players_when_the_game_is_over_and_again_later(db):
    with TestClient(create_app(db=db)) as client:
        game, host = _create(client, [{"kind": "human"}, {"kind": "selfish"}], join_password="pw")
        token = _join(client, game, 0, "Ann", "pw")
        _host(client, game, host, "start")
        assert client.post(f"/api/games/{game}/debrief", json={"seat_token": token}).status_code == 403  # not over yet
        assert client.post(f"/api/games/{game}/debrief", json={"host_token": host}).status_code == 200  # spectators may
        with client.websocket_connect(f"/ws/{game}?seat_token={token}") as ws:
            _play(ws)
        debrief = client.post(f"/api/games/{game}/debrief", json={"seat_token": token}).json()
        assert debrief["ending"]["ending"] in ("nobel", "crisis_crash", "credit")
        assert debrief["real_world"]["main_effects"]  # the world file's effects, kept with the game
        assert client.post(f"/api/games/{game}/debrief", json={}).status_code == 403  # the join password
        assert client.post(f"/api/games/{game}/debrief", json={"password": "pw"}).status_code == 200
        csv_text = client.post(f"/api/games/{game}/debrief.csv", json={"seat_token": token, "table": "literature"}).text
        assert csv_text.splitlines()[0].startswith("theory,author,tier")
    with TestClient(create_app(db=db)) as client:  # reopened after a server restart
        assert client.post(f"/api/games/{game}/debrief", json={"seat_token": token}).json() == debrief


def test_a_game_begun_before_the_bookkeeping_gets_a_complete_debrief_by_replaying_it(db):
    # A game begun before milestone 6 was loaded from a snapshot without the hidden bookkeeping:
    # it has it only from that round on. The debrief replays the game from its first action.
    with TestClient(create_app(db=db)) as client:
        game, host, _ = _finished_game(client)
        complete = client.post(f"/api/games/{game}/debrief", json={"host_token": host}).json()
    assert complete["bookkeeping_recorded"]
    storage = SQLiteStorage(db)
    seq, state = storage.latest_snapshot(game)
    old = GameState.model_validate_json(state)
    old.prediction_log, old.paper_log, old.review_log, old.round_log = [], [], [], []
    storage.save_snapshot(game, seq, old.model_dump_json())
    storage.close()
    with TestClient(create_app(db=db)) as client:
        assert client.post(f"/api/games/{game}/debrief", json={"host_token": host}).json() == complete


def test_a_game_that_does_not_replay_the_same_keeps_its_incomplete_debrief(db):
    with TestClient(create_app(db=db)) as client:
        game, host, _ = _finished_game(client)
    storage = SQLiteStorage(db)
    seq, state = storage.latest_snapshot(game)
    old = GameState.model_validate_json(state)
    old.prediction_log, old.paper_log, old.review_log, old.round_log = [], [], [], []
    storage.save_snapshot(game, seq, old.model_dump_json())
    # As if the rules had changed since: a stored action gave other events than it gives now.
    storage._db.execute("UPDATE actions SET events = '[]' WHERE game_id = ? AND seq = "
                        "(SELECT MIN(seq) FROM actions WHERE game_id = ? AND events != '[]')", (game, game))
    storage.close()
    with TestClient(create_app(db=db)) as client:
        assert not client.post(f"/api/games/{game}/debrief", json={"host_token": host}).json()["bookkeeping_recorded"]

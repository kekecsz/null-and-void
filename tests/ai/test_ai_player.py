"""Specification section 8 (AI opponents) and 11 (software settings), with a fake model: these
tests never call a real API."""

import csv
import json
import re

import pytest

from nv_ai.config import Prices, load_api_keys, load_software_settings, require_api_key
from nv_ai.costs import Ledger, Usage, cost
from nv_ai.player import MAX_ACTIONS_PER_STEP, AIPlayer
from nv_ai.prompt import (
    CACHED_ROUNDS, LEFT_OUT_SECTIONS, PERSONAS, instructions, log_blocks, options_text, rules_text, tool_definitions,
)
from nv_ai.provider import OpenAIProvider, Reply, ToolCall
from nv_core import actions as a
from nv_core.engine import Option, apply, legal_actions, new_game
from nv_core.text import render_text
from nv_core.views import player_view, visible_events
from nv_sim.game import AIContext, ai_models, ai_seat, check_seat_types, game_log, make_player, play_game
from nv_world.game import load_game_world

WORLD_FILE = "scenarios/venus_expedition/worlds/world_seed1.json"


class FakeProvider:
    """Answers like a model would, without any network call.

    ``script`` is a list of replies (dicts: name/arguments, a list of them for several tool calls in
    one reply, or "raise", or "nothing"); when it
    runs out, the fake picks the first complete action listed in the decision message.
    """

    model = "fake-model"

    def __init__(self, script=None, usage=Usage(1000, 800, 0, 50, 20)):
        self.script = list(script or [])
        self.usage = usage
        self.calls = []

    def respond(self, instructions, tools, items, max_output_tokens):
        self.calls.append({"items": list(items), "max_output_tokens": max_output_tokens, "tools": tools})
        step = self.script.pop(0) if self.script else None
        if step == "raise":
            raise ConnectionError("network down")
        if step == "nothing":
            return Reply(None, "I am not sure.", [], self.usage)
        if step is None:
            step = self._first_listed(items)
        steps = step if isinstance(step, list) else [step]  # a list: several tool calls in one reply
        calls = [ToolCall(x["name"], x["arguments"], f"call{len(self.calls)}.{i}") for i, x in enumerate(steps)]
        return Reply(calls[0], "", [{"type": "function_call", "call_id": c.call_id} for c in calls], self.usage, calls=calls)

    @staticmethod
    def _first_listed(items):
        text = next(i["content"] for i in items if isinstance(i, dict) and i.get("role") == "user")
        if "WHAT YOU CAN DO NOW" not in text:
            return {"name": "commit", "arguments": {"reason": "nothing listed"}}
        listed = text.split("WHAT YOU CAN DO NOW", 1)[1]
        for line in listed.splitlines():
            line = line.strip()
            if line.startswith("{"):
                data = json.loads(line)
                if "type" not in data:
                    continue
                if data["type"] not in (
                    "propose_alliance", "leave_alliance", "cancel_prediction", "cancel_development", "withdraw_submission"
                ):
                    return {"name": data.pop("type"), "arguments": {**data, "reason": "first listed"}}
        return {"name": "commit", "arguments": {"reason": "nothing else listed"}}

    @staticmethod
    def user_item(content):
        """Blocks are joined into one text, so the tests can read the message as the model does."""
        if not isinstance(content, str):
            content = "".join(text for text, _ in content)
        return {"role": "user", "content": content}

    @staticmethod
    def tool_result_item(call, text):
        return {"type": "function_call_output", "call_id": call.call_id, "output": text}


@pytest.fixture(scope="module")
def venus():
    world, settings, _ = load_game_world(WORLD_FILE)
    return world, settings


@pytest.fixture
def software():
    base = load_software_settings()
    table = dict(base.ai_price_table)
    table["fake-model"] = Prices(input=0.10, cached_input=0.01, cache_write=0.125, output=0.50)
    return base.model_copy(update={"ai_price_table": table})


def _player(provider, software, ledger=None, persona="neutral"):
    return AIPlayer(provider, software, ledger or Ledger(None, software.ai_total_budget), "A story.", persona)


def _first_decision(venus, player, seat=0):
    world, settings = venus
    state = new_game(world, settings, 1, ["a", "b"])
    view = player_view(state, seat)
    return state, view, legal_actions(state, seat)


# Settings and keys -------------------------------------------------------------------------
def test_software_settings_load_and_have_prices_for_the_default_model():
    software = load_software_settings()
    assert software.prices(software.ai_default_model).output > 0
    assert software.ai_max_cost_per_decision > 0 and software.ai_total_budget > 0


def test_api_key_file_is_read_without_overriding_the_environment(tmp_path, monkeypatch):
    keys = tmp_path / "keys.env"
    keys.write_text("# comment\nOPENAI_API_KEY=from-file\nOTHER_KEY=\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    load_api_keys(keys)
    import os

    assert os.environ["OPENAI_API_KEY"] == "from-file"
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    load_api_keys(keys)
    assert os.environ["OPENAI_API_KEY"] == "from-env"


def test_missing_key_gives_a_clear_error_without_the_key(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("nv_ai.config.API_KEYS", tmp_path / "none.env")
    monkeypatch.setattr("nv_ai.config.load_api_keys", lambda path=None: None)
    with pytest.raises(ValueError, match="OPENAI_API_KEY is not set"):
        require_api_key("openai")


# What the model is sent ----------------------------------------------------------------------
def test_one_fixed_tool_per_action_type_without_references():
    tools = tool_definitions(2000)
    names = [t["name"] for t in tools]
    assert len(names) == len(set(names)) and "commit" in names and "submit" in names
    assert tool_definitions(2000) == tools  # the same list every time (cache-friendly)
    text = json.dumps(tools)
    assert "$ref" not in text and "$defs" not in text
    for tool in tools:
        assert "reason" in tool["parameters"]["required"] and "seat" not in tool["parameters"]["properties"]


def test_rules_text_leaves_out_sections_a_player_does_not_need():
    text = rules_text()
    headings = re.findall(r"^# (.+)$", text, re.MULTILINE)
    assert "Victory" in [h.strip() for h in headings]
    assert not set(LEFT_OUT_SECTIONS) & {h.strip() for h in headings}
    assert "\\_" not in text  # Markdown escapes removed


def test_instructions_share_one_prefix_across_personas():
    texts = [instructions("Story.", persona, 2000) for persona in PERSONAS]
    prefix = texts[0][: texts[0].index("# Your persona")]
    assert all(t.startswith(prefix) for t in texts)
    assert texts[0].index("# Victory") < texts[0].index("# How you play") < texts[0].index("# The scenario")


# Costs ------------------------------------------------------------------------------------
def test_cost_bills_each_input_token_once():
    prices = Prices(input=0.10, cached_input=0.01, cache_write=0.125, output=0.50)
    # 1,000,000 input: 600,000 cached, 100,000 written, 300,000 uncached; 200,000 output
    usage = Usage(input_tokens=1_000_000, cached_tokens=600_000, cache_write_tokens=100_000, output_tokens=200_000)
    expected = 0.3 * 0.10 + 0.6 * 0.01 + 0.1 * 0.125 + 0.2 * 0.50
    assert cost(usage, prices) == pytest.approx(expected)


def test_ledger_keeps_the_total_across_runs(tmp_path):
    path = tmp_path / "spending.csv"
    ledger = Ledger(path, budget=1.0)
    ledger.add("g1", "seat", "m", Usage(10, 0, 0, 5, 0), 0.25)
    ledger.add("g1", "seat", "m", Usage(10, 0, 0, 5, 0), 0.5)
    again = Ledger(path, budget=1.0)
    assert again.total == pytest.approx(0.75) and again.remaining == pytest.approx(0.25)
    with open(path, encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == 2


# The decision loop -----------------------------------------------------------------------------
def test_decision_uses_the_tool_call_and_records_tokens_cost_reason_and_notes(venus, software):
    provider = FakeProvider([{"name": "allocate_staff", "arguments": {"hire_students": 1, "allocation": {"grants": {"students": 1}}, "reason": "cheap", "notes": "x" * 5000}}])
    player = _player(provider, software)
    state, view, options = _first_decision(venus, player)
    action = player.choose(view, options)
    assert isinstance(action, a.AllocateStaff) and action.seat == 0 and action.hire_students == 1
    d = player.decisions[-1]
    assert d["reason"] == "cheap" and d["attempts"] == 1 and d["fallback"] == ""
    assert d["input_tokens"] == 1000 and d["cached_tokens"] == 800 and d["cost"] > 0
    assert len(player.notes) == software.ai_notes_max_chars
    message = provider.calls[0]["items"][0]["content"]
    assert "WHAT YOU CAN DO NOW" in message and "WORLD GRID" in message


def test_invalid_arguments_are_sent_back_and_retried(venus, software):
    provider = FakeProvider([{"name": "allocate_staff", "arguments": {"hire_students": "many", "reason": "?"}}, None])
    player = _player(provider, software)
    _, view, options = _first_decision(venus, player)
    player.choose(view, options)
    retry_items = provider.calls[1]["items"]
    assert any(i.get("type") == "function_call_output" and "Refused" in i["output"] for i in retry_items if isinstance(i, dict))
    assert player.decisions[-1]["attempts"] == 2


def test_engine_refusal_reaches_the_model(venus, software):
    provider = FakeProvider([{"name": "pass", "arguments": {"reason": "nothing to do"}}, None])
    player = _player(provider, software)
    state, view, options = _first_decision(venus, player)
    first = player.choose(view, options)
    player.refused(first, "this action belongs to another phase")
    player.choose(view, options)
    last_items = provider.calls[1]["items"]
    assert any("another phase" in i.get("output", "") for i in last_items if isinstance(i, dict))
    assert player.decisions[0]["refusals"] == ["this action belongs to another phase"]


def test_next_decision_shows_the_choices_already_made_in_this_step(venus, software):
    """Each decision is a fresh conversation; without its earlier choices a model repeats them
    instead of committing (seen in the first real game: 90% of the calls)."""
    provider = FakeProvider()
    player = _player(provider, software)
    state, view, options = _first_decision(venus, player)
    first = player.choose(view, options)
    assert "YOUR CHOICES SO FAR" not in provider.calls[0]["items"][0]["content"]
    player.choose(view, options)
    text = provider.calls[1]["items"][0]["content"]
    assert "YOUR CHOICES SO FAR IN THIS STEP" in text and first.type in text
    assert "call `commit` now" in text

    # a refused action is not listed as a choice
    provider = FakeProvider([{"name": "pass", "arguments": {"reason": "x"}}, None, None])
    player = _player(provider, software)
    refused = player.choose(view, options)
    player.refused(refused, "this action belongs to another phase")
    player.choose(view, options)  # the retry, inside the same conversation
    player.choose(view, options)
    assert '"pass"' not in provider.calls[-1]["items"][0]["content"].split("WHAT YOU CAN DO NOW")[0]


@pytest.mark.parametrize(
    "script, why",
    [
        (["nothing", "nothing", "nothing", "nothing"], "attempts refused"),
        (["raise"], "API error"),
    ],
)
def test_safe_fallback(venus, software, script, why):
    provider = FakeProvider(script)
    player = _player(provider, software)
    state, view, options = _first_decision(venus, player)
    action = player.choose(view, options)
    assert why in player.decisions[-1]["fallback"]
    assert any(action in o.actions for o in options) or isinstance(action, a.AllocateStaff)
    assert len(provider.calls) <= software.ai_retry_limit + 1


def test_repeated_api_errors_stop_further_calls(venus, software):
    """E.g. an expired API key: after MAX_API_ERRORS failures in a row the game goes on without calls."""
    from nv_ai.player import MAX_API_ERRORS

    provider = FakeProvider(["raise"] * 100)
    player = _player(provider, software)
    _, view, options = _first_decision(venus, player)
    for _ in range(MAX_API_ERRORS + 5):
        player.choose(view, options)
    assert len(provider.calls) == MAX_API_ERRORS
    assert "no more AI calls" in player.decisions[-1]["fallback"]


def test_budget_and_per_decision_limit_stop_calls(venus, software):
    spent = Ledger(None, budget=1.0)
    spent.add("g", "s", "m", Usage(), 1.0)
    provider = FakeProvider()
    player = _player(provider, software, ledger=spent)
    _, view, options = _first_decision(venus, player)
    player.choose(view, options)
    assert provider.calls == [] and "budget" in player.decisions[-1]["fallback"]

    tiny = software.model_copy(update={"ai_max_cost_per_decision": 0.000001})
    provider = FakeProvider()
    player = _player(provider, tiny)
    player.choose(view, options)
    assert provider.calls == [] and "per-decision" in player.decisions[-1]["fallback"]


def test_output_limit_follows_the_per_decision_cost(venus, software):
    provider = FakeProvider()
    player = _player(provider, software)
    _, view, options = _first_decision(venus, player)
    player.choose(view, options)
    limit = provider.calls[0]["max_output_tokens"]
    prices = software.prices("fake-model")
    assert 0 < limit <= software.ai_max_cost_per_decision / prices.output * 1_000_000


def test_a_step_cannot_be_stalled(venus, software):
    provider = FakeProvider()
    player = _player(provider, software)
    _, view, options = _first_decision(venus, player)
    for _ in range(MAX_ACTIONS_PER_STEP):
        player.choose(view, options)
    calls = len(provider.calls)
    player.choose(view, options)
    assert len(provider.calls) == calls and "actions in one step" in player.decisions[-1]["fallback"]


# Whole games ----------------------------------------------------------------------------------
def _context(software, provider_factory=None):
    return AIContext(software, Ledger(None, software.ai_total_budget), provider_factory or FakeProvider)


def test_ai_seats_finish_whole_games_and_report_cost(venus, software):
    """Milestone 4: an AI seat finishes complete games; token use and cost are reported."""
    world, settings = venus
    report = play_game(world, settings, 3, ["ai", "random", "ai:selfish"], ai=_context(software))
    assert report.errors == [] and report.game["ending"] in ("nobel", "crisis_crash", "credit")
    assert report.game["ai_cost"] > 0
    assert report.ai_decisions and {"input_tokens", "output_tokens", "cost", "reason"} <= set(report.ai_decisions[0])


def test_failing_model_still_finishes_the_game(venus, software):
    """Specification 8.1: invalid moves and API errors fall back safely."""
    world, settings = venus

    class Broken(FakeProvider):
        def __init__(self):
            super().__init__(["raise", "nothing"] * 100000)

    report = play_game(world, settings, 4, ["ai", "random"], ai=_context(software, Broken))
    assert report.errors == [] and report.game["ending"] != "error"
    assert all(d["fallback"] for d in report.ai_decisions)


def test_text_client_plays_a_game_with_an_ai_seat(venus, software, monkeypatch, tmp_path):
    from nv_core.record import GameRecord
    from nv_server.text_client import TextClient

    world, settings = venus
    record = GameRecord(world=world, settings=settings, seed=6, players=["Ann", "Bot"], seats=["ai", "random"])
    out: list[str] = []
    client = TextClient(record, tmp_path / "g.json", out.append, ai=_context(software))
    client.play_automated()
    assert client.state.result is not None
    assert any("AI:" in line and "USD" in line for line in out)
    assert GameRecord.load(tmp_path / "g.json").seats == ["ai", "random"]


def test_nv_sim_with_ai_seats_writes_decisions_and_records(software, monkeypatch, tmp_path, capsys):
    from nv_sim import run

    monkeypatch.setattr(run, "ai_context", lambda: _context(software))
    out = tmp_path / "ai_run"
    code = run.main(["run", "--players", "2", "--seats", "ai,random", "--games", "2", "--world", WORLD_FILE,
                     "--yes", "--out", str(out)])
    assert code == 0
    with open(out / "ai_decisions.csv", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows and float(rows[0]["cost"]) >= 0
    assert (out / "records" / "game1.json").exists()
    assert "AI cost of this run" in capsys.readouterr().out
    save = tmp_path / "copy.json"
    assert run.main(["record", str(out), "1", "--save", str(save)]) == 0 and save.exists()


def test_nv_sim_max_cost_holds_within_a_game(software, monkeypatch, tmp_path):
    """With a run limit below one decision's cost, every AI decision falls back on the budget."""
    from nv_sim import run

    expensive = Usage(1_000_000, 0, 0, 0, 0)  # 0.10 USD per call at the fake model's prices
    monkeypatch.setattr(run, "ai_context", lambda: _context(software, lambda: FakeProvider(usage=expensive)))
    out = tmp_path / "capped"
    assert run.main(["run", "--players", "2", "--seats", "ai,random", "--games", "1", "--world", WORLD_FILE,
                     "--yes", "--max-cost", "0.25", "--out", str(out)]) == 0
    with open(out / "ai_decisions.csv", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert sum(float(r["cost"]) for r in rows) <= 0.25 + 0.10 + 1e-9  # at most one call past the limit
    assert any("budget" in r["fallback"] for r in rows)


# Models, the game log and the game mode (specification 8 and 8.1) ------------------------------------
def test_an_ai_seat_type_names_its_persona_and_model():
    assert ai_seat("ai") == ("neutral", None, None)
    assert ai_seat("ai:selfish") == ("selfish", None, None)
    assert ai_seat("ai@gpt-6-luna") == ("neutral", "gpt-6-luna", None)
    assert ai_seat("ai:cooperative@gpt-6.1-terra") == ("cooperative", "gpt-6.1-terra", None)
    assert ai_seat("ai@gpt-6.1-terra/medium") == ("neutral", "gpt-6.1-terra", "medium")
    assert ai_seat("cooperative") is None
    check_seat_types(["ai:cooperative@gpt-6.1-terra", "ai"])
    with pytest.raises(ValueError, match="unknown AI model"):
        check_seat_types(["ai@no-such-model"])


def test_gpt_6_1_terra_can_be_chosen_and_has_prices():
    software = load_software_settings()
    assert ai_models()[0] == software.ai_default_model and "gpt-6.1-terra" in ai_models()
    assert software.prices("gpt-6.1-terra").output > 0


def test_an_ai_seat_plays_with_the_model_its_type_names(venus, software):
    world, settings = venus
    asked = []

    def factory(model=None, effort=None):
        asked.append((model, effort))
        return FakeProvider()

    make_player("ai:selfish@gpt-6.1-terra", 0, 1, world, _context(software, factory), settings)
    make_player("ai@gpt-6-luna/medium", 1, 1, world, _context(software, factory), settings)
    make_player("ai", 2, 1, world, _context(software, factory), settings)
    assert asked == [("gpt-6.1-terra", None), ("gpt-6-luna", "medium"), (None, None)]  # None: the default


@pytest.mark.parametrize("mode", ["normal", "simplified"])
def test_the_model_is_told_which_game_it_plays(venus, software, mode):
    world, settings = venus
    settings = settings.model_copy(update={"mode": mode})
    player = make_player("ai", 0, 1, world, _context(software), settings)
    assert f"This is the {mode} game." in player.instructions
    assert player.instructions.startswith(rules_text(settings.model_dump()))  # the shared, cached prefix stays first
    state = new_game(world, settings, 1, ["a", "b"])
    assert f"{mode.upper()} GAME" in render_text(player_view(state, 0))  # the view's header, in every decision


def test_each_decision_starts_with_the_whole_game_log(venus, software):
    world, settings = venus
    provider = FakeProvider()
    report = play_game(world, settings, 3, ["ai", "cooperative"], ai=_context(software, lambda model=None: provider))
    assert report.errors == []
    late = provider.calls[-1]["items"][0]["content"]
    assert late.startswith("GAME LOG")
    log = late.split("\n\n", 1)[0]
    assert "Round 2 begins" in log and "left out" not in log  # the whole game, from its start
    assert " is ready" not in log


def test_world_states_are_only_in_the_view_never_in_the_game_log(venus):
    """Specification 8.2: Probe rows and experiment results are seen in the view (World Grid,
    Records area), so they are remembered only through records; the log keeps everything else."""
    world, settings = venus
    seen = {}

    def watch(state, seat, action, events):
        seen.setdefault("events", []).extend(events)
        seen["state"] = state

    play_game(world, settings, 4, ["selfish", "cooperative"], on_action=watch)
    events, state = seen["events"], seen["state"]
    for seat in range(state.n_players):
        log = game_log(events, seat)
        lines = {line for _, line in log}
        visible = visible_events(events, seat)
        world_states = [e for e in visible if e.kind in ("probe", "outcomes", "experiment_result")]
        assert world_states and not lines & {e.text for e in world_states}
        assert {e.text for e in visible if e.kind not in ("probe", "outcomes", "experiment_result", "commit")} <= lines
        assert [r for r, _ in log] == sorted(r for r, _ in log)  # rounds in order, for the log's blocks
        view = render_text(player_view(state, seat))
        for o in state.researcher(seat).records.observations:  # held records are in the view
            assert f"O{o.id} (P{o.probe + 1}, round {o.round})" in view
        for experiment in {c.experiment for c in state.researcher(seat).records.cards}:
            assert f"E{experiment}:" in view


def test_the_model_is_told_to_keep_world_states_out_of_its_notes(venus, software):
    world, settings = venus
    player = make_player("ai", 0, 1, world, _context(software), settings)
    assert "Your notes must not hold exact world states" in player.instructions
    assert "archive the records you want" in player.instructions


def test_the_oldest_log_lines_are_left_out_to_keep_within_the_input_limit(venus, software):
    provider = FakeProvider()
    small = software.model_copy(update={"ai_max_input_tokens": 40_000})
    player = _player(provider, small)
    state, view, options = _first_decision(venus, player)
    view["game_log"] = [(i // 100, f"event number {i}") for i in range(20_000)]
    player.choose(view, options)
    message = provider.calls[0]["items"][0]["content"]
    assert "earlier lines left out" in message and "event number 19999" in message and "event number 0\n" not in message
    assert len(message) + player._fixed_chars <= small.ai_max_input_tokens * 3
    kept = re.findall(r"event number (\d+)\n", message)
    assert int(kept[0]) % 100 == 0  # whole rounds are left out, so the rounds kept stay cached


def test_the_game_log_is_sent_in_round_blocks_and_the_latest_finished_rounds_are_cached():
    log = [(r, f"line {r}.{i}") for r in range(1, 7) for i in range(3)]
    blocks = log_blocks(log, current_round=6)
    assert blocks[0][0].startswith("GAME LOG") and not blocks[0][1]
    assert [b[0] for b in blocks[1:]] == ["".join(f"  line {r}.{i}\n" for i in range(3)) for r in range(1, 7)]
    assert [b[1] for b in blocks[1:]] == [False, False, True, True, True, False]  # rounds 3-5; 6 is still going
    assert sum(b for _, b in blocks) == CACHED_ROUNDS  # with the instructions' one: OpenAI's limit of 4 writes


def test_the_openai_request_marks_cache_breakpoints_after_the_instructions_and_finished_rounds(monkeypatch):
    """The real request (the HTTP body the SDK sends), without a network call."""
    httpx = pytest.importorskip("httpx")
    pytest.importorskip("openai")
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "r1", "object": "response", "created_at": 0, "model": "m", "status": "completed", "output": [],
            "tool_choice": "required", "tools": [], "parallel_tool_calls": False,
            "usage": {"input_tokens": 10, "output_tokens": 1, "total_tokens": 11,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
        })

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    provider = OpenAIProvider("gpt-6.1-terra")
    from openai import OpenAI
    provider.client = OpenAI(http_client=httpx.Client(transport=httpx.MockTransport(handler)), max_retries=0)
    blocks = log_blocks([(1, "a"), (2, "b")], current_round=2) + [("view", False)]
    provider.respond("THE RULES", [], [provider.user_item(blocks)], 100)
    body = sent[0]
    assert body["prompt_cache_options"] == {"mode": "explicit"} and "instructions" not in body
    developer, user = body["input"]
    assert developer["role"] == "developer" and developer["content"][0]["text"] == "THE RULES"
    assert developer["content"][0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    marked = [c["text"] for c in user["content"] if "prompt_cache_breakpoint" in c]
    assert marked == ["  a\n"]  # round 1 is finished; round 2 and the view are not cached


def test_no_model_call_when_commit_or_pass_is_the_only_legal_action(venus, software):
    provider = FakeProvider()
    player = _player(provider, software)
    state, view, _ = _first_decision(venus, player)
    only = [Option(type="commit", actions=[a.CommitPhase(seat=0)])]
    assert player.choose(view, only) == a.CommitPhase(seat=0)
    assert provider.calls == [] and player.decisions[-1]["reason"].startswith("automatic")


def test_a_choice_with_commit_true_is_followed_by_a_commit_without_a_model_call(venus, software):
    world, settings = venus
    state = new_game(world, settings, 1, ["a", "b"])
    view, options = player_view(state, 0), legal_actions(state, 0)  # Hiring: secret choices, then commit
    provider = FakeProvider([{"name": "propose_alliance", "arguments": {"partner": 1, "reason": "x", "commit": True}}])
    player = _player(provider, software)
    action = player.choose(view, options)
    assert action.type == "propose_alliance"
    state, _ = apply(state, action)
    assert player.choose(player_view(state, 0), legal_actions(state, 0)) == a.CommitPhase(seat=0)
    assert len(provider.calls) == 1
    tools = {t["name"]: t["parameters"]["properties"] for t in provider.calls[0]["tools"]}
    assert "commit" in tools["propose_alliance"] and "commit" not in tools["commit"]


def test_a_refused_automatic_commit_goes_back_to_the_model_with_the_reason(venus, software):
    provider = FakeProvider()
    player = _player(provider, software)
    state, view, options = _first_decision(venus, player)
    player._step, player._commit_next = (view["round"], view["phase"]), True  # as after a choice with commit: true
    action = player.choose(view, options)
    assert action == a.CommitPhase(seat=0) and provider.calls == []
    player.refused(action, "staff must be allocated first")
    player.choose(view, options)
    items = provider.calls[0]["items"]
    assert items[-1]["content"] == "Your automatic commit was refused: staff must be allocated first."


# Several tool calls in one reply (specification 8.1) ----------------------------------------------
def _propose(partner, commit=False):
    return {"name": "propose_alliance", "arguments": {"partner": partner, "reason": f"ally {partner}", "commit": commit}}


def _three_player_hiring(venus):
    world, settings = venus
    state = new_game(world, settings, 1, ["a", "b", "c"])
    return state, player_view(state, 0), legal_actions(state, 0)


def test_several_tool_calls_in_one_reply_are_carried_out_in_order_with_one_model_call(venus, software):
    state, view, options = _three_player_hiring(venus)
    provider = FakeProvider([[_propose(1), _propose(2, commit=True)]])
    player = _player(provider, software)
    done = []
    for _ in range(3):
        action = player.choose(player_view(state, 0), legal_actions(state, 0))
        done.append(action)
        state, _ = apply(state, action)
    assert [x.type for x in done] == ["propose_alliance", "propose_alliance", "commit"]
    assert [x.partner for x in done[:2]] == [1, 2]
    assert len(provider.calls) == 1
    assert player.decisions[0]["cost"] > 0 and player.decisions[1]["cost"] == 0  # the call's cost is on the first


def test_when_the_first_action_of_a_reply_is_refused_every_call_gets_its_answer(venus, software):
    _, view, options = _three_player_hiring(venus)
    provider = FakeProvider([[_propose(1), _propose(2)], None])
    player = _player(provider, software)
    first = player.choose(view, options)
    player.refused(first, "not now")
    player.choose(view, options)
    outputs = [i["output"] for i in provider.calls[1]["items"] if isinstance(i, dict) and i.get("type") == "function_call_output"]
    assert outputs[0].startswith("Refused: not now") and outputs[1].startswith("Not carried out")


def test_when_a_later_action_of_a_reply_is_refused_the_model_decides_again_on_the_board_as_it_is(venus, software):
    _, view, options = _three_player_hiring(venus)
    provider = FakeProvider([[_propose(1), _propose(2)], None])
    player = _player(provider, software)
    player.choose(view, options)
    second = player.choose(view, options)
    assert len(provider.calls) == 1
    player.refused(second, "not now")
    player.choose(view, options)
    last = provider.calls[1]["items"][-1]["content"]
    assert "propose_alliance (called in your last message) was refused: not now" in last


def test_the_openai_provider_asks_for_and_reads_several_tool_calls(monkeypatch):
    httpx = pytest.importorskip("httpx")
    pytest.importorskip("openai")
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        call = lambda i, name: {"type": "function_call", "id": f"fc{i}", "call_id": f"c{i}", "name": name,
                                "arguments": json.dumps({"reason": "r"}), "status": "completed"}
        return httpx.Response(200, json={
            "id": "r1", "object": "response", "created_at": 0, "model": "m", "status": "completed",
            "output": [call(1, "pass"), call(2, "commit")],
            "tool_choice": "required", "tools": [], "parallel_tool_calls": True,
            "usage": {"input_tokens": 10, "output_tokens": 1, "total_tokens": 11,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
        })

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    provider = OpenAIProvider("gpt-6.1-terra")
    from openai import OpenAI
    provider.client = OpenAI(http_client=httpx.Client(transport=httpx.MockTransport(handler)), max_retries=0)
    reply = provider.respond("THE RULES", [], [provider.user_item("view")], 100)
    assert sent[0]["parallel_tool_calls"] is True
    assert [c.name for c in reply.calls] == ["pass", "commit"] and reply.call.name == "pass"


def test_the_model_reads_the_rulebook_with_this_games_values_and_tables(venus, software):
    """Specification 8.1: the rulebook in the system prompt is filled in with the game's settings."""
    import re

    world, settings = venus
    settings = settings.model_copy(update={"unused_staff_penalty": -7})
    player = make_player("ai", 0, 1, world, _context(software), settings)
    rules = player.instructions.split("# How you play")[0]
    assert not re.findall(r"\[[a-z_]+\]", rules)  # no [parameter] left
    assert "suffers 7 academic credit penalty" in rules  # this game's value ("penalty" carries the sign)
    assert "| Position | Funding | Admin" in rules  # the Grant funding track as a table


def test_the_view_tells_the_grant_positions_admin_need_and_the_publications_due(venus):
    world, settings = venus
    state = new_game(world, settings, 1, ["a", "b"])
    position = state.researcher(0).grant_position
    text = render_text(player_view(state, 0))
    needed = settings.grant_track[position - 1].admin
    assert f"Grant funding: position {position} needs {needed} staff member(s) on Grants" in text
    assert "publications due this round: 0" in text


def test_an_action_dropped_by_the_server_is_decided_again_with_a_note(venus, software):
    """Specification 8.1: an action the server could not carry out because the game changed while
    the model decided (or was paused) is decided again, on the board as it is now."""
    _, view, options = _three_player_hiring(venus)
    provider = FakeProvider([_propose(1), None])
    player = _player(provider, software)
    first = player.choose(view, options)
    player.dropped(first, "the game is paused")
    player.choose(view, options)
    assert len(provider.calls) == 2
    note = provider.calls[1]["items"][-1]["content"]
    assert note == "Your propose_alliance was not carried out: the game is paused. Decide again on the board as it is now."
    assert player.decisions[0]["refusals"] == ["not carried out: the game is paused"]


def test_a_skipped_call_gives_the_safe_default(venus, software):
    _, view, options = _three_player_hiring(venus)
    provider = FakeProvider()
    player = _player(provider, software)
    action = player.skip(view, options)
    assert action.type == "commit" and provider.calls == []
    assert player.decisions[-1]["fallback"] == "skipped by the host"


def test_the_decision_message_invites_several_tool_calls(venus, software):
    """Specification 8.1: nothing in the message tells the model to call only one tool."""
    provider = FakeProvider()
    player = _player(provider, software)
    _, view, options = _first_decision(venus, player)
    player.choose(view, options)
    message = provider.calls[0]["items"][0]["content"]
    assert "call one or more tools" in message and "call one tool)" not in message
    assert "calling exactly one tool" not in player.instructions


# Predictions as one list (specification 8.1) --------------------------------------------------------
def test_predictions_are_one_tool_taking_a_list(software):
    tools = {t["name"]: t for t in _player(FakeProvider(), software).tools}
    assert "make_prediction" not in tools
    item = tools["make_predictions"]["parameters"]["properties"]["predictions"]
    assert item["type"] == "array" and {"theory", "probe", "preregister"} <= set(item["items"]["properties"])


def _prediction_step():
    from tests.core.test_rules_predictions import _at_prediction, _theory

    state = _at_prediction()
    t1 = _theory(state, 1, {"IP1": "a"}, {"WO1": "up"})
    t2 = _theory(state, 1, {"IP2": "x"}, {"WO1": "up"})
    return state, t1, t2


def test_the_prediction_options_are_one_line_per_theory():
    state, t1, t2 = _prediction_step()
    text = options_text(legal_actions(state, 0))
    assert f"theory {t1.id} on probe 0, 1, 2" in text and f"theory {t2.id} on probe 0, 1, 2" in text
    assert "preregister: true or false" in text and '"make_prediction"' not in text


def test_a_list_of_predictions_is_made_in_order_with_one_model_call(software):
    state, t1, t2 = _prediction_step()
    provider = FakeProvider([{"name": "make_predictions", "arguments": {"reason": "all at once", "commit": True, "predictions": [
        {"theory": t1.id, "probe": 0, "preregister": True}, {"theory": t2.id, "probe": 1}]}}])
    player = _player(provider, software)
    made = []
    for _ in range(3):
        action = player.choose(player_view(state, 0), legal_actions(state, 0))
        made.append(action)
        state, _ = apply(state, action)
    assert [(x.type, getattr(x, "theory", None), getattr(x, "probe", None)) for x in made] == [
        ("make_prediction", t1.id, 0), ("make_prediction", t2.id, 1), ("commit", None, None)]
    assert made[0].preregister and not made[1].preregister
    assert len(provider.calls) == 1


def test_an_empty_prediction_list_is_sent_back(software):
    state, _, _ = _prediction_step()
    provider = FakeProvider([{"name": "make_predictions", "arguments": {"reason": "?", "predictions": []}}, None])
    player = _player(provider, software)
    player.choose(player_view(state, 0), legal_actions(state, 0))
    outputs = [i["output"] for i in provider.calls[1]["items"] if isinstance(i, dict) and i.get("type") == "function_call_output"]
    assert outputs and "non-empty list" in outputs[0]

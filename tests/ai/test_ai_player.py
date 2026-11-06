"""Specification section 8 (AI opponents) and 11 (software settings), with a fake model: these
tests never call a real API."""

import csv
import json
import re

import pytest

from nv_ai.config import Prices, load_api_keys, load_software_settings, require_api_key
from nv_ai.costs import Ledger, Usage, cost
from nv_ai.player import MAX_ACTIONS_PER_STEP, AIPlayer
from nv_ai.prompt import LEFT_OUT_SECTIONS, PERSONAS, instructions, rules_text, tool_definitions
from nv_ai.provider import Reply, ToolCall
from nv_core import actions as a
from nv_core.engine import legal_actions, new_game
from nv_core.views import player_view
from nv_sim.game import AIContext, play_game
from nv_world.game import load_game_world

WORLD_FILE = "scenarios/venus_expedition/worlds/world_seed1.json"


class FakeProvider:
    """Answers like a model would, without any network call.

    ``script`` is a list of replies (dicts: name/arguments, or "raise", or "nothing"); when it
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
        call = ToolCall(step["name"], step["arguments"], f"call{len(self.calls)}")
        return Reply(call, "", [{"type": "function_call", "call_id": call.call_id}], self.usage)

    @staticmethod
    def _first_listed(items):
        text = next(i["content"] for i in items if isinstance(i, dict) and i.get("role") == "user")
        listed = text.split("WHAT YOU CAN DO NOW", 1)[1]
        for line in listed.splitlines():
            line = line.strip()
            if line.startswith("{"):
                data = json.loads(line)
                if data["type"] not in ("propose_alliance", "leave_alliance", "cancel_prediction", "cancel_development"):
                    return {"name": data.pop("type"), "arguments": {**data, "reason": "first listed"}}
        return {"name": "commit", "arguments": {"reason": "nothing else listed"}}

    @staticmethod
    def user_item(text):
        return {"role": "user", "content": text}

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

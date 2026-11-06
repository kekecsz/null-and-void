"""The AI player (specification section 8): one tool call per decision, refusals fed back,
a safe fallback, and every call's tokens and cost recorded."""

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from nv_ai.config import SoftwareSettings
from nv_ai.costs import Ledger, Usage, cost
from nv_ai.prompt import decision_message, instructions, tool_definitions
from nv_ai.provider import Provider, Reply
from nv_core.actions import ACTION_ADAPTER
from nv_core.engine import Option
from nv_sim.bots import RandomBot

MIN_OUTPUT_TOKENS = 2_000  # below this a reply (with reasoning) is pointless: fall back instead
MAX_ACTIONS_PER_STEP = 30  # then commit or pass, so a model cannot stall a step
MAX_API_ERRORS = 3  # in a row: then no more calls in this game (e.g. an expired API key)
CHARS_PER_TOKEN = 3.0  # a cautious estimate, for the per-decision cost limit only


class AIPlayer:
    """Implements the automated player interface ``choose(view, options)`` (specification 9.1).

    The caller tells it about refused actions with ``refused(action, reason)`` before asking again.
    """

    needs_view = True

    def __init__(
        self,
        provider: Provider,
        software: SoftwareSettings,
        ledger: Ledger,
        story: str,
        persona: str = "neutral",
        game: str = "",
        name: str = "",
        fallback_seed: str = "fallback",
    ):
        self.provider = provider
        self.software = software
        self.ledger = ledger
        self.prices = software.prices(provider.model)
        self.instructions = instructions(story, persona, software.ai_notes_max_chars)
        self.tools = tool_definitions(software.ai_notes_max_chars)
        self.persona = persona
        self.game = game
        self.name = name
        self.notes = ""
        self.usage = Usage()
        self.cost = 0.0
        self.decisions: list[dict[str, Any]] = []
        self._fallback = RandomBot(fallback_seed)
        self._items: list[Any] = []
        self._last_call = None
        self._refusal: str | None = None
        self._attempts = 0
        self._decision_cost = 0.0  # since the last recorded action (for the decision log)
        self._decision_usage = Usage()
        self._spent = 0.0  # on this decision, retries included (for ai_max_cost_per_decision)
        self._current: dict[str, Any] = {"round": None, "phase": None}
        self._reason = ""
        self._step: tuple | None = None
        self._step_actions = 0
        self._fixed_chars = len(self.instructions) + len(json.dumps(self.tools))
        self._api_errors = 0
        self._disabled = ""

    # ------------------------------------------------------------------------------------
    def refused(self, action: BaseModel, reason: str) -> None:
        self._refusal = reason
        if self.decisions:
            self.decisions[-1]["refusals"].append(reason)

    def choose(self, view: dict[str, Any], options: list[Option]) -> BaseModel:
        step = (view["round"], view["phase"])
        if step != self._step:
            self._step, self._step_actions = step, 0
        self._step_actions += 1
        if self._refusal is None:
            self._new_decision(view, options)
        elif self._last_call is not None:
            self._items.append(
                self.provider.tool_result_item(self._last_call, f"Refused: {self._refusal}. Call one tool again.")
            )
        self._refusal = None

        if self._step_actions > MAX_ACTIONS_PER_STEP:
            return self._fall_back(view, options, f"more than {MAX_ACTIONS_PER_STEP} actions in one step")
        while True:
            if self._attempts > self.software.ai_retry_limit:
                return self._fall_back(view, options, f"{self._attempts} attempts refused")
            if self._disabled:
                return self._fall_back(view, options, self._disabled)
            if self.ledger.remaining <= 0:
                return self._fall_back(view, options, "the AI budget is used up (ai_total_budget)")
            max_output = self._output_limit()
            if max_output < MIN_OUTPUT_TOKENS:
                return self._fall_back(view, options, "the per-decision cost limit is reached")
            try:
                reply = self.provider.respond(self.instructions, self.tools, self._items, max_output)
            except Exception as exc:  # any API failure: the seat takes the safe default
                self._api_errors += 1
                why = f"API error: {type(exc).__name__}: {exc}"[:300]
                if self._api_errors >= MAX_API_ERRORS:
                    self._disabled = f"no more AI calls after {MAX_API_ERRORS} API errors in a row ({why})"
                return self._fall_back(view, options, why)
            self._api_errors = 0
            self._attempts += 1
            self._account(reply)
            action, problem = self._action(reply, view["seat"])
            self._items += reply.output_items
            if action is not None:
                self._last_call = reply.call
                self._record(action=action, reply=reply)
                return action
            if reply.call is not None:
                self._items.append(self.provider.tool_result_item(reply.call, f"Refused: {problem}. Call one tool again."))
            else:
                self._items.append(self.provider.user_item(f"{problem} Call exactly one tool."))

    # ------------------------------------------------------------------------------------
    def _new_decision(self, view: dict[str, Any], options: list[Option]) -> None:
        text = decision_message(view, options, view.get("recent_events", []), self.notes)
        self._items = [self.provider.user_item(text)]
        self._last_call = None
        self._attempts = 0
        self._spent = 0.0
        self._current = {"round": view["round"], "phase": view["phase"]}

    def _output_limit(self) -> int:
        chars = self._fixed_chars + sum(len(json.dumps(i, default=str)) if isinstance(i, dict) else 2000 for i in self._items)
        input_cost = chars / CHARS_PER_TOKEN * self.prices.input / 1_000_000
        left = self.software.ai_max_cost_per_decision - self._spent - input_cost
        return int(max(0.0, left) / self.prices.output * 1_000_000) if self.prices.output else 10**9

    def _account(self, reply: Reply) -> None:
        amount = cost(reply.usage, self.prices)
        self.cost += amount
        self.usage = self.usage + reply.usage
        self._decision_cost += amount
        self._spent += amount
        self._decision_usage = self._decision_usage + reply.usage
        self.ledger.add(self.game, self.name, self.provider.model, reply.usage, amount)

    def _action(self, reply: Reply, seat: int) -> tuple[BaseModel | None, str]:
        if reply.call is None:
            why = f" (the reply stopped early: {reply.incomplete})" if reply.incomplete else ""
            return None, f"No tool was called{why}."
        if reply.call.arguments is None:
            return None, "The tool arguments were not valid JSON"
        data = dict(reply.call.arguments)
        self._reason = str(data.pop("reason", ""))[:300]
        notes = data.pop("notes", None)
        data.update(type=reply.call.name, seat=seat)
        try:
            action = ACTION_ADAPTER.validate_python(data)
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
            return None, f"The tool arguments do not fit {reply.call.name}: {problems}"
        if isinstance(notes, str):
            self.notes = notes[: self.software.ai_notes_max_chars]
        return action, ""

    def _fall_back(self, view: dict[str, Any], options: list[Option], why: str) -> BaseModel:
        """The safe default (specification 8.1): commit or pass; a required choice is made at random."""
        by_type = {o.type: o for o in options}
        if "commit" in by_type:
            action = by_type["commit"].actions[0]
        elif "pass" in by_type:
            action = by_type["pass"].actions[0]
        else:
            action = self._fallback.choose(view, options)
        self._items, self._last_call, self._attempts, self._spent = [], None, 0, 0.0
        self._reason = ""
        self._record(action=action, reply=None, fallback=why)
        return action

    def _record(self, action: BaseModel, reply: Reply | None, fallback: str = "") -> None:
        usage = self._decision_usage
        self.decisions.append(
            {
                "player": self.name,
                "round": self._current["round"],
                "phase": self._current["phase"],
                "action": action.model_dump_json(exclude={"seat"}),
                "reason": self._reason,
                "attempts": self._attempts,
                "fallback": fallback,
                "refusals": [],
                "input_tokens": usage.input_tokens,
                "cached_tokens": usage.cached_tokens,
                "cache_write_tokens": usage.cache_write_tokens,
                "output_tokens": usage.output_tokens,
                "reasoning_tokens": usage.reasoning_tokens,
                "cost": round(self._decision_cost, 6),
            }
        )
        self._decision_usage = Usage()
        self._decision_cost = 0.0

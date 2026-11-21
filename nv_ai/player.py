"""The AI player (specification section 8): one model call per decision, whose tool calls (one or
several) are carried out in order; refusals fed back, a safe fallback, and every call's tokens and
cost recorded."""

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from nv_ai.config import SoftwareSettings
from nv_ai.costs import Ledger, Usage, cost
from nv_ai.prompt import decision_message, fit_log, instructions, message_text, tool_definitions
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
        mode: str = "normal",
        settings: dict[str, Any] | None = None,  # the game's settings: the rulebook is filled in with them
    ):
        self.provider = provider
        self.software = software
        self.ledger = ledger
        self.prices = software.prices(provider.model)
        self.instructions = instructions(story, persona, software.ai_notes_max_chars, mode, settings)
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
        self._calls: list = []  # the tool calls of the reply being carried out
        self._done = 0  # how many of them were handed to the engine so far
        self._queue: list[tuple[BaseModel, bool, str]] = []  # the rest: (action, commit after it, reason)
        self._refusal: str | None = None
        self._attempts = 0
        self._decision_cost = 0.0  # since the last recorded action (for the decision log)
        self._decision_usage = Usage()
        self._spent = 0.0  # on this decision, retries included (for ai_max_cost_per_decision)
        self._current: dict[str, Any] = {"round": None, "phase": None}
        self._reason = ""
        self._step: tuple | None = None
        self._step_actions = 0
        self._step_choices: list[str] = []  # accepted actions in this step, shown to the model
        self._fixed_chars = len(self.instructions) + len(json.dumps(self.tools))
        self._api_errors = 0
        self._disabled = ""
        self._commit_next = False  # the model's last choice asked to commit right after it
        self._automatic = False  # the last action was taken without a model call
        self._automatic_refused = ""  # why it was refused, told to the model at its next decision

    # ------------------------------------------------------------------------------------
    def refused(self, action: BaseModel, reason: str) -> None:
        if self._step_choices:
            self._step_choices.pop()  # the engine did not accept it
        if self.decisions:
            self.decisions[-1]["refusals"].append(reason)
        self._commit_next = False
        if self._automatic:  # the model decides instead, told why
            self._automatic = False
            self._automatic_refused = f"Your automatic {action.type} was refused: {reason}."
            return
        self._queue = []  # the actions after a refused one are not carried out
        if self._done > 1:  # a later action of the reply: the model decides again, with the board as it is now
            self._automatic_refused = (f"Your {action.type} (called in your last message) was refused: {reason}. "
                                       "The actions after it were not carried out.")
            return
        self._refusal = reason

    def choose(self, view: dict[str, Any], options: list[Option]) -> BaseModel:
        step = (view["round"], view["phase"])
        if step != self._step:
            self._step, self._step_actions, self._step_choices = step, 0, []
            self._commit_next = False
            self._queue = []  # a new step: what was left of the last reply no longer applies
        self._step_actions += 1
        self._automatic = False
        if self._refusal is None and not self._automatic_refused:
            if self._queue and self._step_actions <= MAX_ACTIONS_PER_STEP:
                return self._next_queued(view)
            action = self._without_a_call(view, options)
            if action is not None:
                return action
        if self._refusal is None:
            self._new_decision(view, options)
        else:  # the reply's first action was refused: every tool call of the reply gets its answer
            for i, call in enumerate(self._calls):
                text = (f"Refused: {self._refusal}. Call the tools again." if i == 0
                        else "Not carried out: an action before it was refused.")
                self._items.append(self.provider.tool_result_item(call, text))
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
            actions, problem = self._actions(reply, view["seat"])
            self._items += reply.output_items
            if actions:
                self._calls, self._done, self._queue = reply.calls, 0, actions
                return self._next_queued(view)
            for call in reply.calls:  # nothing is carried out when one of them does not fit
                self._items.append(self.provider.tool_result_item(call, f"Refused: {problem}. Nothing of this reply was carried out; call the tools again."))
            if not reply.calls:
                self._items.append(self.provider.user_item(f"{problem} Call at least one tool."))

    # ------------------------------------------------------------------------------------
    def _next_queued(self, view: dict[str, Any]) -> BaseModel:
        """The next action of the model's reply (specification 8.1: several tool calls in one reply
        are carried out in order, one per decision; the first one carries the call's cost)."""
        action, commit, reason = self._queue.pop(0)
        self._done += 1
        self._commit_next = self._commit_next or commit
        self._current = {"round": view["round"], "phase": view["phase"]}
        self._reason = reason if self._done == 1 else f"(same reply) {reason}".strip()
        self._record(action=action, reply=None)
        return action

    def _without_a_call(self, view: dict[str, Any], options: list[Option]) -> BaseModel | None:
        """Actions that need no model call (specification 8.1): the only legal action is commit or
        pass, or the model's last choice asked to commit right after it."""
        by_type = {o.type: o for o in options}
        action, why = None, ""
        if len(options) == 1 and options[0].type in ("commit", "pass") and len(options[0].actions) == 1:
            action, why = options[0].actions[0], "the only legal action"
        elif self._commit_next and "commit" in by_type:
            action, why = by_type["commit"].actions[0], "asked for with its last choice"
        self._commit_next = False
        if action is None:
            return None
        self._automatic = True
        self._current = {"round": view["round"], "phase": view["phase"]}
        self._reason = f"automatic: {why}"
        self._record(action=action, reply=None)
        return action

    def _new_decision(self, view: dict[str, Any], options: list[Option]) -> None:
        # ai_max_input_tokens (specification 8.4): the oldest rounds of the log are left out first
        log = view.get("game_log", [])
        rest = len(message_text(decision_message(view, options, [], self.notes, self._step_choices, len(log))))
        room = int(self.software.ai_max_input_tokens * CHARS_PER_TOKEN) - self._fixed_chars - rest
        log, left_out = fit_log(log, room)
        blocks = decision_message(view, options, log, self.notes, self._step_choices, left_out)
        self._items = [self.provider.user_item(blocks)]
        if self._automatic_refused:
            self._items.append(self.provider.user_item(self._automatic_refused))
            self._automatic_refused = ""
        self._calls, self._done, self._queue = [], 0, []
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

    def _actions(self, reply: Reply, seat: int) -> tuple[list[tuple[BaseModel, bool, str]], str]:
        """The reply's tool calls as actions, in order, each with its commit flag and reason; none
        when one of them does not fit (then nothing is carried out)."""
        if not reply.calls:
            why = f" (the reply stopped early: {reply.incomplete})" if reply.incomplete else ""
            return [], f"No tool was called{why}."
        actions, notes = [], None
        for call in reply.calls:
            if call.arguments is None:
                return [], f"The arguments of {call.name} were not valid JSON"
            data = dict(call.arguments)
            reason = str(data.pop("reason", ""))[:300]
            if isinstance(given := data.pop("notes", None), str):
                notes = given
            commit = data.pop("commit", None) is True
            data.update(type=call.name, seat=seat)
            try:
                action = ACTION_ADAPTER.validate_python(data)
            except ValidationError as exc:
                problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
                return [], f"The tool arguments do not fit {call.name}: {problems}"
            actions.append((action, commit, reason))
        if notes is not None:
            self.notes = notes[: self.software.ai_notes_max_chars]
        return actions, ""

    def _fall_back(self, view: dict[str, Any], options: list[Option], why: str) -> BaseModel:
        """The safe default (specification 8.1): commit or pass; a required choice is made at random."""
        by_type = {o.type: o for o in options}
        if "commit" in by_type:
            action = by_type["commit"].actions[0]
        elif "pass" in by_type:
            action = by_type["pass"].actions[0]
        else:
            action = self._fallback.choose(view, options)
        self._items, self._calls, self._done, self._queue, self._attempts, self._spent = [], [], 0, [], 0, 0.0
        self._reason = ""
        self._record(action=action, reply=None, fallback=why)
        return action

    def _record(self, action: BaseModel, reply: Reply | None, fallback: str = "") -> None:
        self._step_choices.append(action.model_dump_json(exclude={"seat"}))
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

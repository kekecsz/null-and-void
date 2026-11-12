"""Scripted strategy bots (specification section 9.4).

Seat types: ``selfish``, ``cooperative``, ``patient-selfish``, ``patient-cooperative``. A bot sees
only its player view and the events visible to it (``observe``), like a human player; it keeps
an evidence tally (``nv_core.evidence``) over everything it has seen. Game values come from the
game settings, bot settings from ``settings/software.yaml``.

Each step is planned once, as a queue of actions, then committed. Ties are broken with the
bot's own seeded generator, and nothing is drawn in the iteration order of a set, so a game can
be replayed from its seed.
"""

import math
import random
from dataclasses import dataclass
from functools import cache
from itertools import combinations, product
from typing import Any

from pydantic import BaseModel

from nv_core import actions as a
from nv_core.engine import Option
from nv_core.engine.experimentation import MAX_SENSOR_LEVEL
from nv_core.evidence import Case, Tally, theory_key, wilson_lower
from nv_core.settings import Settings
from nv_core.state import StaffCount, Task
from nv_core.world_data import WorldData

MOTIVES = ("selfish", "cooperative")
SEAT_TYPES = ("selfish", "cooperative", "patient-selfish", "patient-cooperative")

# Students leave from the least needed tasks first (specification 9.4, Student task check).
LEAVE_ORDER = [Task.EXPERIMENTATION, Task.PEER_REVIEW, Task.DATA_COLLECTION, Task.WRITE_UP, Task.GRANTS]
# Spare postdocs and students are given tasks in this order once the planned needs are met.
FILL_ORDER = [Task.GRANTS, Task.WRITE_UP, Task.DATA_COLLECTION, Task.PEER_REVIEW, Task.EXPERIMENTATION]
TOP_THEORIES = 30  # theories compared when choosing a discriminating experiment
MAX_UNPUBLISHED_THEORIES = 2  # a bot formulates no new theory while this many wait in its lab
NEAR_BEST = 0.9  # theories scoring at least this share of the best are all candidates to formulate
UNDO_TYPES =("withdraw_submission", "cancel_prediction", "cancel_development")  # take back a choice


@dataclass(frozen=True)
class BotSettings:
    """The scripted bots' settings (specification 11; values in settings/software.yaml)."""

    confidence_threshold: float
    formulate_threshold: float
    rival_citation_factor: float
    kill_counter: int
    memory_corruption: float
    max_wait_rounds: int

    @classmethod
    @cache
    def load(cls) -> "BotSettings":
        from nv_ai.config import load_software_settings

        s = load_software_settings()
        return cls(
            confidence_threshold=s.bot_confidence_threshold,
            formulate_threshold=s.bot_formulate_threshold,
            rival_citation_factor=s.bot_rival_citation_factor,
            kill_counter=s.bot_kill_counter,
            memory_corruption=s.bot_memory_corruption,
            max_wait_rounds=s.bot_max_wait_rounds,
        )


class StrategyBot:
    needs_view = True

    def __init__(self, seed: int | str, kind: str, world: WorldData, settings: Settings, bot: BotSettings):
        if kind not in SEAT_TYPES:
            raise ValueError(f"unknown scripted bot {kind!r}")
        self.kind = kind
        self.motive = kind.rsplit("-", 1)[-1]
        self.patient = kind.startswith("patient-")
        self.awake = not self.patient
        self.rng = random.Random(f"{seed}/strategy")
        self.settings = settings
        self.bot = bot
        self.inputs = {v.id: list(v.states) for v in world.input_parameters}
        self.outcomes = {v.id: list(v.states) for v in world.world_outcomes}
        self.memory: list[tuple[dict[str, str | None], dict[str, str]]] = []  # Probe readings, outcomes
        self.experiments: list[Case] = []
        self._dealt: dict[int, dict[str, str | None]] = {}
        self._tally: Tally | None = None
        self._step: tuple | None = None
        self._queue: list[BaseModel] = []
        self._done: list[str] = []
        self._cash_in: list[int] = []  # rival theories the selfish bot predicts with for credit
        self.refusals = 0

    # Seeing the game ------------------------------------------------------------------------
    def observe(self, events) -> None:
        """Events visible to this seat, after every action (what a human sees on the board)."""
        for e in events:
            if e.kind == "round":
                self._forget()
            elif e.kind == "probe" and "readings" in e.data:
                self._dealt[e.data["probe"]] = dict(e.data["readings"])
            elif e.kind == "outcomes" and "outcomes" in e.data:
                readings = self._dealt.pop(e.data["probe"], None)
                if readings is not None:
                    self.memory.append((readings, dict(e.data["outcomes"])))
                    if self._tally is not None:
                        self._tally.add(Case(readings, dict(e.data["outcomes"])))
            elif e.kind == "experiment_result":
                case = Case(dict(e.data["inputs"]), dict(e.data["outcomes"]), exact=True)
                self.experiments.append(case)
                if self._tally is not None:
                    self._tally.add(case)

    def _forget(self) -> None:
        """Memory corruption: each remembered reading may change to a random state of its row."""
        rate = self.bot.memory_corruption
        if rate <= 0 or not self.memory:
            return
        states = {**self.inputs, **self.outcomes}
        changed = []
        for readings, outcomes in self.memory:
            readings = {v: (self.rng.choice(states[v]) if x is not None and self.rng.random() < rate else x) for v, x in readings.items()}
            outcomes = {v: (self.rng.choice(states[v]) if self.rng.random() < rate else x) for v, x in outcomes.items()}
            changed.append((readings, outcomes))
        self.memory = changed
        self._tally = None

    @property
    def tally(self) -> Tally:
        if self._tally is None:
            cases = [Case(r, o) for r, o in self.memory] + self.experiments
            self._tally = Tally.build(self.inputs, self.outcomes, cases)
        return self._tally

    def refused(self, action: BaseModel, reason: str) -> None:
        self.refusals += 1

    # Deciding -------------------------------------------------------------------------------
    def choose(self, view: dict[str, Any], options: list[Option]) -> BaseModel:
        options = [o for o in options if o.type != "withdraw_submission"]  # a bot never takes back a submission
        seat = view["seat"]
        step = (view["round"], view["phase"])
        if step != self._step:
            self._step, self._queue, self._done = step, [], []
        if self.patient and not self.awake:
            self.awake = self._wakes(view)
        by_type = {o.type: o for o in options}

        if "alliance" in by_type and "alliance" not in self._done:
            self._done.append("alliance")
            action = self._alliance(view, by_type["alliance"])
            if action is not None:
                return action
        if self._queue:
            return self._queue.pop(0)

        planners = [
            ("allocate_staff", self._hire),
            ("choose_leaving_students", self._leaving),
            ("leave_alliance", self._last_chance),
            ("make_prediction", self._predictions),
            ("reveal_prediction", self._reveals),
            ("order_predictions", self._order),
            ("formulate_theory", self._development),
            ("develop_method", self._development),
            ("submit", self._submissions),
            ("revise", self._submissions),
            ("review_vote", self._votes),
        ]
        for kind, planner in planners:
            if kind in by_type and planner.__name__ not in self._done:
                self._done.append(planner.__name__)
                self._queue = list(planner(view, by_type))
                if self._queue:
                    return self._queue.pop(0)

        if "claim_probe_time" in by_type:
            return self._probe_time(view, by_type["claim_probe_time"].actions)
        if "run_experiment" in by_type:
            if "expand_lab" in by_type and self._expand_lab(view):
                return by_type["expand_lab"].actions[0]
            return self._experiment(view, by_type)
        if "commit" in by_type:
            return by_type["commit"].actions[0]
        if "pass" in by_type:
            return by_type["pass"].actions[0]
        for option in options:  # never an undo: it would make room for the same choice again, forever
            if option.actions and option.type not in UNDO_TYPES:
                return option.actions[0]
        raise ValueError("no complete action among the options")

    def _expand_lab(self, view) -> bool:
        """Experimentation and equipment phase: buy lab capacity when the lab is full this round and
        the money left still pays the postdocs."""
        me = self._me(view)
        staff = me["staff"].get(Task.EXPERIMENTATION.value)
        cost = me["lab_capacity_cost"]
        if cost is None or me["lab_capacity"] is None or not staff:
            return False
        full = staff["postdocs"] + staff["students"] >= me["lab_capacity"]
        payroll = me["postdocs"] * self.settings.cost_of_postdoc
        return full and me["money"] - cost >= payroll

    def _wakes(self, view) -> bool:
        """Patient modifier: confident in some theory, or the Warning shot is revealed; at the
        latest after ``max_wait_rounds`` (a table of patient bots would never move the clock)."""
        return bool(
            view["warning_revealed"]
            or view["round"] > self.bot.max_wait_rounds
            or self.tally.confident(self.bot.confidence_threshold)
        )

    # Helpers --------------------------------------------------------------------------------
    def _me(self, view) -> dict[str, Any]:
        return view["researchers"][view["seat"]]

    def _staff(self, view, task: Task) -> int:
        count = self._me(view)["staff"].get(task.value)
        return count["postdocs"] + count["students"] if count else 0

    def _theories(self, view) -> list[dict[str, Any]]:
        return [p for p in view["published"] if p["kind"] == "theory"]

    def _known_keys(self, view) -> list:
        """Theories already published, in the bot's lab, or in its manuscripts."""
        keys = [theory_key(p["inputs"], p["outcomes"]) for p in self._theories(view)]
        keys += [theory_key(i["inputs"], i["outcomes"]) for i in view["lab"]["ideas"] if i["kind"] == "theory"]
        for m in view["manuscripts"]:
            if m["author"] == view["seat"] and m["content"] and m["content"]["kind"] == "theory":
                keys.append(theory_key(m["content"]["inputs"], m["content"]["outcomes"]))
        return keys

    def _state_shares(self) -> dict[str, dict[str, float]]:
        """How often each input state shows among the visible readings seen so far (an unseen row:
        every state equally often)."""
        shares = {}
        for v, states in self.inputs.items():
            seen = [readings[v] for readings, _ in self.memory if readings.get(v) is not None]
            shares[v] = {x: (seen.count(x) / len(seen) if seen else 1 / len(states)) for x in states}
        return shares

    def _reach(self, inputs: dict[str, str], shares: dict[str, dict[str, float]]) -> float:
        """The share of Probes a theory fits once its rows are visible: the product of how often
        each of its input states occurs. (Blank rows fit any theory, but sensors fill them in, so
        a specific theory that fits today's blanks would rarely be usable later.)"""
        value = 1.0
        for v, x in inputs.items():
            value *= shares[v].get(x, 0.0)
        return value

    def _theory_to_formulate(self, view, exclude: list | None = None) -> tuple[dict, dict] | None:
        """The promising theory (Wilson lower bound at least ``formulate_threshold``) worth the most
        per Probe, counting on the lower bound as its success rate. Selfish: reach x rate x (credit
        for a success + its citation). Each input a theory specifies cuts its reach, so broad
        theories of one or two inputs usually win: they can be used often, which brings citations
        and Nobel Prize progress. Cooperative: rate x the new ground it covers (combinations of input
        states weighted by how often they occur, divided by 1 + the theories that fit them already)."""
        known = self._known_keys(view) + (exclude or [])
        citation = self.settings.citation_reward
        shares = self._state_shares()
        if self.motive == "cooperative":
            # Each combination of input states, by how often it occurs, and how many theories of the
            # field (published, or in its lab and manuscripts) already fit it.
            field = [
                *self._theories(view), *[i for i in view["lab"]["ideas"] if i["kind"] == "theory"],
                *[m["content"] for m in view["manuscripts"]
                  if m["author"] == view["seat"] and m["content"] and m["content"]["kind"] == "theory"],
            ]
            distinct = list({theory_key(t["inputs"], t["outcomes"]): t["inputs"] for t in field}.values())
            combos = []
            for states in product(*self.inputs.values()):
                combo = dict(zip(self.inputs, states))
                weight = math.prod(shares[v][x] for v, x in combo.items())
                covered = sum(all(combo[v] == x for v, x in t.items()) for t in distinct)
                combos.append((combo, weight / (1 + covered)))
        scored = []
        for inputs, outcomes, wins, n in self.tally.theories():
            rate = wilson_lower(wins, n)  # the success rate it can count on, so thin evidence loses
            if rate < self.bot.formulate_threshold or theory_key(inputs, outcomes) in known:
                continue
            if self.motive == "selfish":
                score = self._reach(inputs, shares) * rate * (len(inputs) * len(outcomes) + citation)
            else:  # new ground first: Probes that no theory of the field fits yet
                score = rate * sum(w for combo, w in combos if all(combo[v] == x for v, x in inputs.items()))
            if score > 0:
                scored.append((score, inputs, outcomes))
        if scored:
            # Any near-best theory, so bots seeing the same evidence do not all pick the same one.
            top = max(s for s, _, _ in scored)
            inputs, outcomes = self.rng.choice([(i, o) for s, i, o in scored if s >= NEAR_BEST * top])
            return inputs, outcomes
        if self.motive == "cooperative" and view["warning_revealed"]:
            return self._coverage_theory(view, known)
        return None

    def _coverage_theory(self, view, known: list) -> tuple[dict, dict] | None:
        """Cooperative, from the Warning shot on: in the Crisis a Probe without a prediction counts
        as unsuccessful, so a reasonable prediction is better than none. The best-supported theory
        (success rate above one half) for the input combinations that no published or planned
        theory covers yet, preferring the theory that covers the most of them."""
        theories = self._theories(view) + [i for i in view["lab"]["ideas"] if i["kind"] == "theory"]
        combos = [dict(zip(self.inputs, states)) for states in product(*self.inputs.values())]

        def covers(inputs, combo):
            return all(combo[v] == x for v, x in inputs.items())

        # A theory backs only one revealed prediction a round, so Probes with the same input states
        # need different theories: each combination wants as many theories as there are Probes.
        wanted = len(view["probes"])
        distinct = {theory_key(t["inputs"], t["outcomes"]): t for t in theories}
        missing = [(c, wanted - sum(covers(t["inputs"], c) for t in distinct.values())) for c in combos]
        missing = [(c, m) for c, m in missing if m > 0]
        if not missing:
            return None
        best, best_score = [], 0.0
        for inputs, outcomes, s, n in self.tally.theories():
            if theory_key(inputs, outcomes) in known or n < 2:
                continue
            rate = (s + 1) / (n + 2)
            if rate <= 0.5:
                continue
            score = rate * sum(m for c, m in missing if covers(inputs, c))
            if score > best_score:
                best, best_score = [(inputs, outcomes)], score
            elif score == best_score and score > 0:
                best.append((inputs, outcomes))
        return self.rng.choice(best) if best else None

    def _method_to_develop(self, view) -> str | None:
        """Cooperative: a method for the parameter most Probes do not show, while fewer than the
        highest sensor level are published or underway."""
        counts = {v: 0 for v in self.inputs}
        for p in view["published"]:
            if p["kind"] == "method":
                counts[p["parameter"]] += 1
        for i in view["lab"]["ideas"]:
            if i["kind"] == "method":
                counts[i["parameter"]] += 1
        for m in view["manuscripts"]:
            if m["author"] == view["seat"] and m["content"] and m["content"]["kind"] == "method":
                counts[m["content"]["parameter"]] += 1
        hidden = {v: sum(v not in p["specialty"] for p in view["probes"]) for v in self.inputs}
        needed = [v for v in self.inputs if hidden[v] > 0 and counts[v] < MAX_SENSOR_LEVEL]
        if not needed:
            return None
        best = max((hidden[v], -counts[v]) for v in needed)
        return self.rng.choice([v for v in needed if (hidden[v], -counts[v]) == best])

    def _development_plan(self, view) -> list[BaseModel]:
        seat, plan, made = view["seat"], [], []
        waiting = sum(1 for i in view["lab"]["ideas"] if i["kind"] == "theory")
        # No new theory while enough wait to be published: their Development postdocs would cost
        # the money that submission fees need.
        theory = self._theory_to_formulate(view) if waiting < MAX_UNPUBLISHED_THEORIES else None
        if theory:
            plan.append(a.FormulateTheory(seat=seat, inputs=theory[0], outcomes=theory[1]))
            made.append(theory_key(*theory))
        if self.motive == "cooperative":
            parameter = self._method_to_develop(view)
            if parameter:
                plan.append(a.DevelopMethod(seat=seat, parameter=parameter))
        return plan

    def _target(self, view) -> tuple[dict, dict] | None:
        """The theory the bot means to publish next: one in its lab, or one it will formulate."""
        for idea in view["lab"]["ideas"]:
            if idea["kind"] == "theory":
                return idea["inputs"], idea["outcomes"]
        return self._theory_to_formulate(view)

    def _success_value(self, paper, preregistered: bool, crisis: bool, own: bool) -> int:
        s = self.settings
        base = len(paper["inputs"]) + (s.crisis_pred_base_bonus if crisis else 0)
        value = base * len(paper["outcomes"]) * (2 if preregistered else 1)
        if own:
            value += s.citation_reward + (s.crisis_pred_citation_reward_bonus if crisis else 0)
        return value

    def _failure_cost(self, preregistered: bool, crisis: bool, own: bool) -> int:
        s = self.settings
        if crisis:
            cost = s.failed_prereg_pred_ac_crisis + (s.crisis_failed_pred_citation_penalty if own else 0)
        else:
            cost = s.failed_prereg_pred_ac if preregistered else s.failed_non_prereg_pred_ac
        return cost  # zero or negative

    def _expected(self, paper, preregistered: bool, crisis: bool, own: bool) -> float:
        p = self.tally.rate(paper["inputs"], paper["outcomes"])
        return p * self._success_value(paper, preregistered, crisis, own) + (1 - p) * self._failure_cost(
            preregistered, crisis, own
        )

    def _fails_confidently(self, paper) -> bool:
        s, n = self.tally.counts(paper["inputs"], paper["outcomes"])
        return wilson_lower(n - s, n) >= self.bot.confidence_threshold

    def _leave_chance(self, view) -> float:
        below = self.settings.student_leave_threshold(self._me(view)["talent_position"]) - 1
        return min(1.0, max(0, below) / 6)

    # Hiring and task allocation -----------------------------------------------------------------
    def _needs(self, view) -> tuple[int, dict[Task, int]]:
        """(postdocs needed for Development, other staff needed per task)."""
        s, seat, me = self.settings, view["seat"], self._me(view)
        crisis = view["period"] == "crisis"
        needs = {t: 0 for t in FILL_ORDER}
        needs[Task.GRANTS] = s.grant_track[me["grant_position"] - 1].admin
        development = len(self._development_plan(view))
        revisable = sum(1 for m in view["manuscripts"] if m["author"] == seat and m["area"] == "revise")
        needs[Task.WRITE_UP] = revisable + len(view["lab"]["ideas"]) + development
        theories = [p for p in self._theories(view) if not p["fresh"] or p["author"] == seat]
        probes = len(view["probes"])
        if self.motive == "cooperative" and self._crisis_near(view):
            needs[Task.DATA_COLLECTION] = probes
        elif self.motive == "cooperative":
            useful = [
                p for p in theories
                if self.tally.lower(p["inputs"], p["outcomes"]) >= self.bot.confidence_threshold or self._fails_confidently(p)
            ]
            needs[Task.DATA_COLLECTION] = min(probes, len(useful))
        else:
            own = [p for p in theories if p["author"] == seat and self.tally.rate(p["inputs"], p["outcomes"]) >= 0.5]
            kills = any(p["author"] != seat and p["nobel"] >= self.bot.kill_counter for p in theories)
            if crisis:
                good = [p for p in theories if self._expected(p, True, True, p["author"] == seat) > 0]
                needs[Task.DATA_COLLECTION] = min(probes, len(good))
            else:
                needs[Task.DATA_COLLECTION] = min(probes, len(own) + (1 if kills else 0))
        awaiting = [m for m in view["manuscripts"] if m["area"] == "review"]
        if self.motive == "cooperative":
            needs[Task.PEER_REVIEW] = min(2, math.ceil(len(awaiting) / 2))
        else:
            own = sum(1 for m in awaiting if m["author"] == seat)
            needs[Task.PEER_REVIEW] = 1 if awaiting and own * 2 >= len(awaiting) else 0
        if self.motive == "selfish":  # confirm its target theory, or explore
            needs[Task.EXPERIMENTATION] = 1
        else:
            needs[Task.EXPERIMENTATION] = 1 + (1 if self._sensor_methods(view) else 0)
        return development, needs

    def _crisis_near(self, view) -> bool:
        """In the Crisis, or the Crisis card can come this round: the Game Period Deck is down to
        its last part, which holds the Crisis card (Game setup). The deck count is public."""
        if view["period"] == "crisis":
            return True
        last_part = self.settings.calm_cards_per_player_crisis * len(view["players"]) + 1
        return view["warning_revealed"] and view["period_deck"] <= last_part

    def _fill_order(self, view) -> list[Task]:
        if view["period"] == "crisis" or (self.motive == "cooperative" and self._crisis_near(view)):
            return [Task.DATA_COLLECTION] + [t for t in FILL_ORDER if t != Task.DATA_COLLECTION]
        return FILL_ORDER

    def _sensor_methods(self, view) -> bool:
        """A published method that could install or upgrade a sensor somewhere."""
        methods: dict[str, int] = {}
        for p in view["published"]:
            if p["kind"] == "method" and (not p["fresh"] or p["author"] == view["seat"]):
                methods[p["parameter"]] = methods.get(p["parameter"], 0) + 1
        for probe in view["probes"]:
            for v in self.inputs:
                if v not in probe["specialty"]:
                    level = probe["sensors"].get(v, 0)
                    if level < MAX_SENSOR_LEVEL and methods.get(v, 0) >= level + 1:
                        return True
        return False

    def _hire(self, view, by_type) -> list[BaseModel]:
        t = by_type["allocate_staff"].template
        seat, s = view["seat"], self.settings
        now = t["postdocs_now"]
        low, high = t["postdocs_after"]
        if not self.awake:
            postdocs = max(low, 0)
            allocation = {Task.EXPERIMENTATION: StaffCount(postdocs=postdocs)} if postdocs else {}
            return [a.AllocateStaff(seat=seat, fire_postdocs=now - postdocs, allocation=allocation)]
        development, needs = self._needs(view)
        money = self._me(view)["money"]
        cost = s.cost_of_postdoc
        affordable = money // cost if cost else now + development
        postdocs = max(min(now, affordable), min(development, affordable))
        postdocs = max(low, postdocs if high is None else min(high, postdocs))
        if postdocs < development:  # ideas it cannot afford to develop need no write-up either
            needs[Task.WRITE_UP] -= development - postdocs
            development = postdocs
        allocation: dict[Task, StaffCount] = {}

        def put(task: Task, postdoc: bool) -> None:
            count = allocation.setdefault(task, StaffCount())
            if postdoc:
                count.postdocs += 1
            else:
                count.students += 1

        spare = postdocs
        for _ in range(min(development, spare)):
            put(Task.DEVELOPMENT, True)
            spare -= 1
        left = dict(needs)
        order = self._fill_order(view)
        for task in order:  # postdocs not needed for Development take other needs first
            while spare and left[task]:
                put(task, True)
                left[task] -= 1
                spare -= 1
        cap = t.get("task_caps", {}).get(Task.EXPERIMENTATION.value)

        def room_on(task: Task) -> bool:  # lab capacity (Hiring and task allocation phase)
            return task != Task.EXPERIMENTATION or cap is None or allocation.get(task, StaffCount()).total < cap

        for _ in range(spare):  # spare postdocs experiment, or develop a method when the lab is full
            put(Task.EXPERIMENTATION if room_on(Task.EXPERIMENTATION) else Task.DEVELOPMENT, True)
        students_needed = sum(left.values())
        chance = self._leave_chance(view)
        buffer = round(students_needed * chance / (1 - chance)) if chance < 1 else 0
        room = t["max_students"]
        for task in order:
            while left[task] and room and room_on(task):
                put(task, False)
                left[task] -= 1
                room -= 1
        for _ in range(min(buffer, room)):  # extra students leave first (from Experimentation)
            if not room_on(Task.EXPERIMENTATION):
                break
            put(Task.EXPERIMENTATION, False)
        students = sum(c.students for c in allocation.values())
        return [
            a.AllocateStaff(
                seat=seat,
                hire_postdocs=max(0, postdocs - now),
                fire_postdocs=max(0, now - postdocs),
                hire_students=students,
                allocation=allocation,
            )
        ]

    def _leaving(self, view, by_type) -> list[BaseModel]:
        t = by_type["choose_leaving_students"].template
        left, chosen = t["count"], {}
        have = {Task(k): n for k, n in t["students_by_task"].items()}
        order = LEAVE_ORDER + [x for x in Task if x not in LEAVE_ORDER]
        if view["period"] == "crisis" or (self.motive == "cooperative" and self._crisis_near(view)):
            order = [x for x in order if x != Task.DATA_COLLECTION] + [Task.DATA_COLLECTION]  # predictions decide
        for task in order:
            take = min(left, have.get(task, 0))
            if take:
                chosen[task] = take
                left -= take
        return [a.ChooseLeavingStudents(seat=view["seat"], by_task=chosen)]

    # Alliances --------------------------------------------------------------------------------
    def _alliance(self, view, option: Option) -> BaseModel | None:
        seat = view["seat"]
        credits = [r["credit"] for r in view["researchers"]]
        leader = credits.index(max(credits))
        for action in option.actions:
            if self.motive == "cooperative" and isinstance(action, (a.AcceptAlliance, a.ProposeAlliance)):
                return action
            if self.motive == "selfish" and leader != seat and action.partner == leader:
                if isinstance(action, (a.AcceptAlliance, a.ProposeAlliance)):
                    return action
        return None

    def _last_chance(self, view, by_type) -> list[BaseModel]:
        if self.motive == "cooperative":
            return []
        mine = self._me(view)["credit"]
        return [
            x for x in by_type["leave_alliance"].actions
            if isinstance(x, a.LeaveAlliance) and view["researchers"][x.partner]["credit"] < mine
        ]

    # Experimentation and equipment ---------------------------------------------------------------
    def _experiment(self, view, by_type) -> BaseModel:
        seat = view["seat"]
        if self.motive == "cooperative" and "install_sensor" in by_type:
            choices = by_type["install_sensor"].template["choices"]
            probes = {p["index"]: p for p in view["probes"]}

            def score(c):
                p = probes[c["probe"]]
                hidden = sum(1 for v in self.inputs if v not in p["specialty"] and v not in p["sensors"])
                return (p["hot_topic"], hidden, -p["sensors"].get(c["parameter"], 0))

            best = max(score(c) for c in choices)
            choice = self.rng.choice([c for c in choices if score(c) == best])
            return a.InstallSensor(
                seat=seat, probe=choice["probe"], parameter=choice["parameter"],
                cited_methods=sorted(choice["methods"])[: choice["methods_needed"]],
            )
        t = by_type["run_experiment"].template
        free = t["free_input_parameters"]
        if self.motive == "selfish":
            target = self._target(view)
        else:  # confirm a theory waiting in its lab: a fitting record lets it reach a journal tier
            target = next(((i["inputs"], i["outcomes"]) for i in view["lab"]["ideas"] if i["kind"] == "theory"), None)
        if target:
            wanted = list(target[0])
            specified = {v: target[0][v] for v in wanted[:free]}
            cited, extra = [], [v for v in wanted[free:]]
            for v in extra:
                method = next((m["id"] for m in t["methods"] if m["parameter"] == v), None)
                if method is not None:
                    cited.append(method)
                    specified[v] = target[0][v]
            return a.RunExperiment(seat=seat, specified=specified, cited_methods=cited)
        return a.RunExperiment(seat=seat, specified=self._discriminating(free))

    def _discriminating(self, free: int) -> dict[str, str]:
        """The input states where the most likely theories disagree most about the outcome; with no
        disagreement, the least observed combination."""
        tally = self.tally
        top = sorted(
            (((s + 1) / (n + 2), i, o) for i, o, s, n in tally.theories() if n >= 2),
            key=lambda x: x[0], reverse=True,
        )[:TOP_THEORIES]
        specs = []
        for variables in combinations(list(self.inputs), min(free, len(self.inputs))):
            for states in product(*[self.inputs[v] for v in variables]):
                specs.append(dict(zip(variables, states)))
        scores = []
        for spec in specs:
            votes: dict[str, dict[str, int]] = {}
            for _, inputs, outcomes in top:
                if all(spec.get(v) == x for v, x in inputs.items()):
                    for v, x in outcomes.items():
                        votes.setdefault(v, {}).setdefault(x, 0)
                        votes[v][x] += 1
            disagreement = sum(sum(c.values()) - max(c.values()) for c in votes.values())
            scores.append((disagreement, -tally.seen(spec)))
        best = max(scores)
        return self.rng.choice([spec for spec, score in zip(specs, scores) if score == best])

    # Probe time -------------------------------------------------------------------------------
    def _probe_time(self, view, actions: list[a.ClaimProbeTime]) -> BaseModel:
        probes = {p["index"]: p for p in view["probes"]}
        target = self._target(view) if self.motive == "selfish" else None

        def score(x):
            p = probes[x.probe]
            if target:  # rows the theory needs that will be blank: a record is unlikely to mismatch
                return (sum(1 for v in target[0] if v not in p["specialty"] and v not in p["sensors"]), p["hot_topic"])
            return (len(p["specialty"]) + len(p["sensors"]), p["hot_topic"])  # the most visible rows

        best = max(score(x) for x in actions)
        return self.rng.choice([x for x in actions if score(x) == best])

    # Predictions --------------------------------------------------------------------------------
    def _predictions(self, view, by_type) -> list[BaseModel]:
        """The plan, cut to the number of predictions allowed (the first ones are the most wanted)."""
        plan = self._prediction_plan(view, by_type)
        limit = self.settings.prediction_limit(self._staff(view, Task.DATA_COLLECTION))
        return plan if limit is None else plan[:limit]

    def _prediction_plan(self, view, by_type) -> list[BaseModel]:
        seat = view["seat"]
        crisis = view["period"] == "crisis"
        capacity = self._staff(view, Task.DATA_COLLECTION)
        papers = {p["id"]: p for p in self._theories(view)}
        makes = by_type["make_prediction"].actions
        prereg = [m for m in makes if m.preregister]
        hidden = [m for m in makes if not m.preregister]
        plan: list[BaseModel] = []
        # (theory content, Probe) pairs already used: one theory, identical copies included, once
        # per Probe (Formulating predictions and preregistration).
        used: list = []

        def content(m):
            return theory_key(papers[m.theory]["inputs"], papers[m.theory]["outcomes"])

        def slot(m):
            return (content(m), m.probe)

        def take(pool, key, limit):
            for m in sorted(pool, key=key, reverse=True):
                if len(plan) >= limit:
                    break
                if slot(m) not in used:
                    plan.append(m)
                    used.append(slot(m))

        if crisis:  # every prediction is preregistered
            if self.motive == "cooperative":
                mine = [slot for slot, owner in self._field_plan(view) if owner == seat]
                for probe, key in mine:
                    choice = next((m for m in prereg if m.probe == probe and content(m) == key), None)
                    if choice is not None and len(plan) < capacity and slot(choice) not in used:
                        plan.append(choice)
                        used.append(slot(choice))
            else:
                good = [m for m in prereg if self._expected(papers[m.theory], True, True, papers[m.theory]["author"] == seat) > 0]
                take(good, lambda m: self._expected(papers[m.theory], True, True, papers[m.theory]["author"] == seat), capacity)
            return plan

        if self.motive == "cooperative":
            confirm = [m for m in prereg if self.tally.lower(papers[m.theory]["inputs"], papers[m.theory]["outcomes"]) >= self.bot.confidence_threshold]
            refute = [m for m in prereg if self._fails_confidently(papers[m.theory])]
            # wrong theories on their way to a Nobel Prize first, then the best-supported ones
            pool = [(1, papers[m.theory]["nobel"], 0.0, m) for m in refute]
            pool += [(0, 0, self.tally.rate(papers[m.theory]["inputs"], papers[m.theory]["outcomes"]), m) for m in confirm]
            for *_, m in sorted(pool, key=lambda x: x[:3], reverse=True):
                if len(plan) < capacity and slot(m) not in used:
                    plan.append(m)
                    used.append(slot(m))
            return plan

        # Selfish, Calm period: confident preregistrations with its own theories that have no
        # Nobel progress to lose, then hidden predictions to reveal selectively.
        own = [m for m in prereg if papers[m.theory]["author"] == seat and papers[m.theory]["nobel"] == 0
               and self.tally.lower(papers[m.theory]["inputs"], papers[m.theory]["outcomes"]) >= self.bot.confidence_threshold]
        take(own, lambda m: self._expected(papers[m.theory], True, False, True), capacity)
        best_own = max(
            [self._expected(papers[m.theory], False, False, True) for m in hidden if papers[m.theory]["author"] == seat],
            default=0.0,
        )
        self._cash_in = []
        for m in hidden:
            paper = papers[m.theory]
            if slot(m) in used:  # a preregistered prediction already uses this theory on this Probe
                continue
            if paper["author"] == seat or paper["nobel"] >= self.bot.kill_counter:
                plan.append(m)  # own theories, and rivals' Nobel candidates to kill
                used.append(slot(m))
            elif self._expected(paper, False, False, False) > 0 and self._expected(paper, False, False, False) >= self.bot.rival_citation_factor * best_own:
                plan.append(m)
                used.append(slot(m))
                if m.theory not in self._cash_in:
                    self._cash_in.append(m.theory)
        return plan

    def _public_tally(self) -> Tally:
        """The tally from Probe readings only: what every player saw, so cooperative bots that
        plan together reach the same plan."""
        return Tally.build(self.inputs, self.outcomes, [Case(r, o) for r, o in self.memory])

    def _field_plan(self, view) -> list[tuple[tuple[int, Any], int]]:
        """Cooperative, in the Crisis: the plan the cooperative researchers would agree on at the
        table. Each Probe gets its best-supported theory (one theory may serve several Probes);
        the predictions are then shared out in turn order by Data collection staff.
        Returns ((probe, theory content), seat) pairs."""

        tally = self._public_tally()
        contents: dict[Any, dict] = {}  # theory content -> a published copy (a usable one first)
        for p in self._theories(view):
            key = theory_key(p["inputs"], p["outcomes"])
            if key not in contents or (contents[key]["fresh"] and not p["fresh"]):
                contents[key] = p
        probes = view["probes"]

        def eligible(paper, probe):
            readings = probe["readings"] or {}
            return not any(readings.get(v) is not None and readings[v] != x for v, x in paper["inputs"].items())

        options = [
            sorted(
                ((tally.rate(paper["inputs"], paper["outcomes"]), key) for key, paper in contents.items() if eligible(paper, probe)),
                key=lambda x: x[0], reverse=True,
            )
            for probe in probes
        ]
        slots = [(probe["index"], choices[0][1]) for probe, choices in zip(probes, options) if choices]
        capacity = {
            r["seat"]: sum(c["postdocs"] + c["students"] for t, c in r["staff"].items() if t == Task.DATA_COLLECTION.value)
            for r in view["researchers"]
        }
        plan, order = [], [x for x in view["turn_order"] if capacity.get(x, 0) > 0]
        for slot in [x for x in slots if contents[x[1]]["fresh"]]:  # only the author may use a fresh theory
            author = contents[slot[1]]["author"]
            if capacity.get(author, 0) > 0:
                plan.append((slot, author))
                capacity[author] -= 1
        for slot in [x for x in slots if not contents[x[1]]["fresh"]]:
            order = [x for x in order if capacity[x] > 0]
            if not order:
                break
            owner = order[0]
            plan.append((slot, owner))
            capacity[owner] -= 1
            order = order[1:] + order[:1]  # take turns
        return plan

    def _reveals(self, view, by_type) -> list[BaseModel]:
        if self.motive == "cooperative":
            return []
        seat = view["seat"]
        papers = {p["id"]: p for p in self._theories(view)}
        mine = {p["id"]: p for p in view["predictions"] if p["seat"] == seat}
        listed = [x for x in by_type["reveal_prediction"].actions if x.reveal]
        prereg = sum(1 for p in mine.values() if p["preregistered"])
        room = self._staff(view, Task.DATA_COLLECTION) - prereg
        kills, wins = [], []
        for x in listed:
            p = mine[x.prediction]
            paper = papers.get(p["theory"])
            if paper is None:
                continue
            if not p["success"] and paper["author"] != seat and paper["nobel"] >= self.bot.kill_counter:
                kills.append((paper["nobel"], x, p["theory"]))
            elif p["success"] and (paper["author"] == seat or p["theory"] in self._cash_in):
                wins.append((self._success_value(paper, False, False, paper["author"] == seat), x, p["theory"]))
        plan = []
        for _, x, theory in sorted(kills, key=lambda k: k[0], reverse=True) + sorted(wins, key=lambda k: k[0], reverse=True):
            if len(plan) < room:
                plan.append(x)
        return plan

    def _order(self, view, by_type) -> list[BaseModel]:
        return [a.OrderPredictions(seat=view["seat"], order=list(by_type["order_predictions"].template["predictions"]))]

    # Development ------------------------------------------------------------------------------
    def _development(self, view, by_type) -> list[BaseModel]:
        if "formulate_theory" not in by_type and "develop_method" not in by_type:
            return []
        staff = self._staff(view, Task.DEVELOPMENT) - len(view["lab"]["pending"]["development"])
        plan = self._development_plan(view)[:staff]
        while len(plan) < staff:  # nothing better: a method, so no staff member is left unused
            counts = {v: sum(1 for p in view["published"] if p["kind"] == "method" and p["parameter"] == v) for v in self.inputs}
            fewest = min(counts.values())
            plan.append(a.DevelopMethod(seat=view["seat"], parameter=self.rng.choice([v for v in self.inputs if counts[v] == fewest])))
        return plan

    # Submission and revisions -------------------------------------------------------------------
    def _submissions(self, view, by_type) -> list[BaseModel]:
        seat, s = view["seat"], self.settings
        me = self._me(view)
        room = self._staff(view, Task.WRITE_UP) - me["staff"].get(Task.WRITE_UP.value, {}).get("used", 0)
        plan: list[BaseModel] = list(by_type["revise"].actions[:room]) if "revise" in by_type else []
        if "submit" not in by_type:
            return plan
        option = by_type["submit"]
        t = option.template
        money = t["spendable"] - me["postdocs"] * s.cost_of_postdoc  # keep the postdocs' pay
        taken: set = set()  # record cards used by this step's submissions
        by_idea: dict[int, list[a.Submit]] = {}
        for x in option.actions:
            by_idea.setdefault(x.manuscript, []).append(x)
        for idea, choices in by_idea.items():
            if len(plan) >= room:
                break
            if self.motive == "cooperative":
                choices = [x for x in choices if not self._mixed(x.records + self._spare(t, x))]
                choices.sort(key=lambda x: (s.journal_tiers[x.tier].peer_review, s.journal_tiers[x.tier].rounds_in_processing, -x.tier))
            if not choices:
                continue
            for x in choices:  # highest tier first (selfish) or soonest published (cooperative)
                fee = s.journal_tiers[x.tier].submission_fee
                if fee > money or any(self._parts(r) & taken for r in x.records):
                    continue
                money -= fee
                apc = t["apc"][str(x.tier)]
                pay = 0 < apc <= money
                if pay:
                    money -= apc
                records = list(x.records) + [r for r in self._spare(t, x) if not self._parts(r) & taken]
                for r in records:
                    taken |= self._parts(r)
                plan.append(x.model_copy(update={"records": records, "pay_apc": pay}))
                break
        return plan

    @staticmethod
    def _spare(template, submit: a.Submit) -> list:
        spare = template["spare_records"].get(f"{submit.manuscript}/{submit.tier}", [])
        out = []
        for r in spare:
            if r["kind"] == "observation":
                out.append(a.ObservationRecord(**r))
            else:
                out.append(a.ExperimentRecord(cards=[tuple(c) for c in r["cards"]]))
        return out

    @staticmethod
    def _parts(record) -> set:
        if isinstance(record, a.ObservationRecord):
            return {("O", record.observation)}
        return {("E", e, v) for e, v in record.cards}

    @staticmethod
    def _mixed(records) -> bool:
        """An experiment record made of cards from more than one experiment."""
        return any(isinstance(r, a.ExperimentRecord) and len({e for e, _ in r.cards}) > 1 for r in records)

    # Peer review ---------------------------------------------------------------------------------
    def _votes(self, view, by_type) -> list[BaseModel]:
        seat = view["seat"]
        cards = view["review_cards"].get(str(seat), [])
        by_position = {m["position"]: m for m in view["manuscripts"] if m["area"] == "review"}
        plan = []
        for index, position in enumerate(cards):
            m = by_position.get(position)
            if not position or m is None:
                continue
            if self.motive == "selfish":
                vote = "accept" if m["author"] == seat else "revise"
            else:
                vote = "accept"
                content = m["content"]
                if content and content["kind"] == "theory":
                    s, n = self.tally.counts(content["inputs"], content["outcomes"])
                    if s < n - s:
                        vote = "revise"
            plan.append(a.ReviewVote(seat=seat, card=index, vote=vote))
        return plan

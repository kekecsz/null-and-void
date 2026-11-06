"""Automated players (specification section 9.1).

Every automated player implements ``choose(view, options) -> action``: ``view`` is its player
view (``nv_core.views.player_view``) and ``options`` the result of ``legal_actions``.
"""

import random
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from nv_core import actions as a
from nv_core.engine import Option
from nv_core.state import StaffCount, Task


class Player(Protocol):
    needs_view: bool

    def choose(self, view: dict[str, Any] | None, options: list[Option]) -> BaseModel: ...


@dataclass(frozen=True)
class RandomWeights:
    """How the random bot leans, so games keep moving (specification 9.1). Probabilities."""

    pass_turn: float = 0.15  # pass in the Experimentation phase instead of acting
    sensor: float = 0.3  # install a sensor rather than run an experiment, when possible
    another_prediction: float = 0.6  # make one more prediction before committing
    preregister: float = 0.5
    reveal: float = 0.6  # reveal a hidden prediction
    theory: float = 0.6  # formulate a theory rather than develop a method
    submit: float = 0.8  # use a write-up staff member when possible
    extra_record: float = 0.3  # add each spare record to a submission
    pay_apc: float = 0.2
    propose_alliance: float = 0.01  # per decision
    accept_alliance: float = 0.5
    leave_alliance: float = 0.02
    last_chance_leave: float = 0.3


class RandomBot:
    """Picks among the legal options at random (with the weights above) and always commits."""

    needs_view = False

    def __init__(self, seed: int | str, weights: RandomWeights | None = None):
        self.rng = random.Random(seed)
        self.w = weights or RandomWeights()
        self._step: tuple | None = None
        self._done: set[str] = set()  # choices already made in this step
        self._queue: list[BaseModel] = []  # actions planned for this step

    # ----------------------------------------------------------------------------------
    def choose(self, view: dict[str, Any] | None, options: list[Option]) -> BaseModel:
        """``view`` needs only "round", "phase" (to tell one step from the next) and "seat"."""
        by_type = {o.type: o for o in options}
        rng, w = self.rng, self.w
        step = (view["round"], view["phase"])
        if step != self._step:
            self._step, self._done, self._queue = step, set(), []

        alliance = by_type.get("alliance")
        if alliance:
            accepts = [x for x in alliance.actions if isinstance(x, a.AcceptAlliance)]
            if accepts and rng.random() < w.accept_alliance:
                return rng.choice(accepts)
            proposals = [x for x in alliance.actions if isinstance(x, a.ProposeAlliance)]
            if proposals and rng.random() < w.propose_alliance:
                return rng.choice(proposals)
            leaves = [x for x in alliance.actions if isinstance(x, a.LeaveAlliance)]
            if leaves and rng.random() < w.leave_alliance:
                return rng.choice(leaves)

        commit = by_type.get("commit")
        commit_action = commit.actions[0] if commit else None
        seat = view["seat"]

        if "allocate_staff" in by_type and "allocate_staff" not in self._done:
            self._done.add("allocate_staff")
            return self._allocate(seat, by_type["allocate_staff"].template)
        if "choose_leaving_students" in by_type and "leave" not in self._done:
            self._done.add("leave")
            return self._leaving(seat, by_type["choose_leaving_students"].template)
        if "order_predictions" in by_type and "order" not in self._done:
            self._done.add("order")
            ids = list(by_type["order_predictions"].template["predictions"])
            rng.shuffle(ids)
            return a.OrderPredictions(seat=seat, order=ids)
        if "review_vote" in by_type and "votes" not in self._done:
            self._done.add("votes")
            # One vote per card; the engine keeps the last vote for each card.
            cards = sorted({x.card for x in by_type["review_vote"].actions})
            self._queue = [a.ReviewVote(seat=seat, card=c, vote=rng.choice(["accept", "revise"])) for c in cards]
        if self._queue:
            return self._queue.pop(0)

        # Sequential steps --------------------------------------------------------------
        if "claim_probe_time" in by_type:
            return rng.choice(by_type["claim_probe_time"].actions)
        if "run_experiment" in by_type:
            if "pass" in by_type and rng.random() < w.pass_turn:
                return by_type["pass"].actions[0]
            if "install_sensor" in by_type and rng.random() < w.sensor:
                choice = rng.choice(by_type["install_sensor"].template["choices"])
                methods = rng.sample(choice["methods"], choice["methods_needed"])
                return a.InstallSensor(seat=seat, probe=choice["probe"], parameter=choice["parameter"], cited_methods=methods)
            return self._experiment(seat, by_type["run_experiment"].template)

        # Simultaneous steps: a few choices, then commit -------------------------------------
        if "last_chance" not in self._done and any(
            isinstance(x, a.LeaveAlliance) for o in options if o.type == "leave_alliance" for x in o.actions
        ):
            self._done.add("last_chance")
            leaves = by_type["leave_alliance"].actions
            if rng.random() < w.last_chance_leave:
                return rng.choice(leaves)
        if "make_prediction" in by_type and "predictions" not in self._done:
            if rng.random() < w.another_prediction:
                makes = by_type["make_prediction"].actions
                choice = rng.choice(makes)
                if not choice.preregister and rng.random() < w.preregister:
                    preregistered = [m for m in makes if m.preregister and m.theory == choice.theory and m.probe == choice.probe]
                    if preregistered:
                        choice = preregistered[0]
                return choice
            self._done.add("predictions")
        if "reveal_prediction" in by_type and "reveals" not in self._done:
            reveals = [x for x in by_type["reveal_prediction"].actions if x.reveal]
            self._done.add("reveals")
            self._queue = [x for x in reveals if rng.random() < w.reveal]
            if self._queue:
                return self._queue.pop(0)
        if "formulate_theory" in by_type or "develop_method" in by_type:
            if "formulate_theory" in by_type and rng.random() < w.theory:
                theory = self._theory(seat, by_type["formulate_theory"].template)
                if theory:
                    return theory
            if "develop_method" in by_type:
                return rng.choice(by_type["develop_method"].actions)
        if "submit" in by_type or "revise" in by_type:
            if rng.random() < w.submit:
                if "revise" in by_type:
                    return rng.choice(by_type["revise"].actions)
                return self._submission(by_type["submit"])
        if commit_action:
            return commit_action
        if "pass" in by_type:
            return by_type["pass"].actions[0]
        return self._any_action(options)

    # ----------------------------------------------------------------------------------
    @staticmethod
    def _any_action(options: list[Option]) -> BaseModel:
        for option in options:
            if option.actions:
                return option.actions[0]
        raise ValueError("no complete action among the options")

    def _allocate(self, seat: int, t: dict[str, Any]) -> a.AllocateStaff:
        rng = self.rng
        low, high = t["postdocs_after"]
        high = high if high is not None else low + 3
        postdocs = rng.randint(low, max(low, high))
        students = rng.randint(0, t["max_students"])
        tasks = [Task(x) for x in t["tasks"]]
        student_tasks = [x for x in tasks if x.value not in t["postdoc_only"]]
        allocation: dict[Task, StaffCount] = {}
        for _ in range(postdocs):
            task = rng.choice(tasks)
            if task.value in t["at_most_one"] and task in allocation:
                task = Task.DEVELOPMENT
            allocation.setdefault(task, StaffCount()).postdocs += 1
        for _ in range(students):
            allocation.setdefault(rng.choice(student_tasks), StaffCount()).students += 1
        now = t["postdocs_now"]
        return a.AllocateStaff(
            seat=seat,
            hire_postdocs=max(0, postdocs - now),
            fire_postdocs=max(0, now - postdocs),
            hire_students=students,
            allocation=allocation,
        )

    def _leaving(self, seat: int, t: dict[str, Any]) -> a.ChooseLeavingStudents:
        pool = [Task(task) for task, n in t["students_by_task"].items() for _ in range(n)]
        chosen = self.rng.sample(pool, t["count"])
        by_task: dict[Task, int] = {}
        for task in chosen:
            by_task[task] = by_task.get(task, 0) + 1
        return a.ChooseLeavingStudents(seat=seat, by_task=by_task)

    def _experiment(self, seat: int, t: dict[str, Any]) -> a.RunExperiment:
        rng = self.rng
        states = t["states"]
        parameters = list(states)
        cited: list[int] = []
        # A list, not a set: the order of a set of strings differs between Python processes,
        # and the states below are drawn in this order, so a set would break replay from the seed.
        cited_parameters: list[str] = []
        for method in rng.sample(t["methods"], len(t["methods"])):
            if method["parameter"] not in cited_parameters and rng.random() < 0.5:
                cited.append(method["id"])
                cited_parameters.append(method["parameter"])
        free = rng.randint(0, min(t["free_input_parameters"], len(parameters) - len(cited_parameters)))
        chosen = list(cited_parameters) + rng.sample([p for p in parameters if p not in cited_parameters], free)
        return a.RunExperiment(
            seat=seat, specified={p: rng.choice(states[p]) for p in chosen}, cited_methods=cited
        )

    def _theory(self, seat: int, t: dict[str, Any]) -> a.FormulateTheory | None:
        rng = self.rng
        published = [(p["inputs"], p["outcomes"]) for p in t["published"]]
        for _ in range(10):
            inputs = {v: rng.choice(t["inputs"][v]) for v in rng.sample(list(t["inputs"]), rng.randint(1, 2))}
            outcomes = {v: rng.choice(t["outcomes"][v]) for v in rng.sample(list(t["outcomes"]), rng.randint(1, len(t["outcomes"])))}
            ordered_in = {v: inputs[v] for v in t["inputs"] if v in inputs}
            ordered_out = {v: outcomes[v] for v in t["outcomes"] if v in outcomes}
            if (ordered_in, ordered_out) not in published:
                return a.FormulateTheory(seat=seat, inputs=ordered_in, outcomes=ordered_out)
        return None

    def _submission(self, option: Option) -> a.Submit:
        rng = self.rng
        submit = rng.choice(option.actions)
        spare = option.template["spare_records"].get(f"{submit.manuscript}/{submit.tier}", [])
        extra = [rec for rec in spare if rng.random() < self.w.extra_record]
        apc = option.template["apc"][str(submit.tier)]
        pay = rng.random() < self.w.pay_apc and apc <= option.template["spendable"]
        return submit.model_copy(update={"records": list(submit.records) + [_record(r) for r in extra], "pay_apc": pay})


def _record(data: dict[str, Any]) -> BaseModel:
    if data["kind"] == "observation":
        return a.ObservationRecord(**data)
    return a.ExperimentRecord(kind="experiment", cards=[tuple(c) for c in data["cards"]])


BOTS = {"random": RandomBot}

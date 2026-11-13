"""Experimentation and equipment phase (running experiments, sensors) and Probe time."""

from nv_core.actions import ClaimProbeTime, ExpandLab, InstallSensor, Pass, RunExperiment
from nv_core.engine.context import Ctx, IllegalAction
from nv_core.state import Card, Experiment, ExperimentCard, Paper, Task

MAX_SENSOR_LEVEL = 3  # the highest Sensor marker (Pieces; Sensor installation and upgrade)


# Turn handling -------------------------------------------------------------------------------
def start(ctx: Ctx) -> None:
    state = ctx.state
    state.passed = []
    state.current = None
    _next_turn(ctx, after=None)


def _can_act(ctx: Ctx, seat: int) -> bool:
    return ctx.state.researcher(seat).remaining(Task.EXPERIMENTATION) > 0


def _next_turn(ctx: Ctx, after: int | None) -> None:
    """The next researcher in turn order who has not passed; those who cannot act pass."""
    state = ctx.state
    order = state.turn_order()
    start_index = 0 if after is None else (order.index(after) + 1)
    for i in range(len(order)):
        seat = order[(start_index + i) % len(order)]
        if seat in state.passed:
            continue
        if not _can_act(ctx, seat):
            state.passed.append(seat)
            continue
        state.current = seat
        return
    state.current = None


def finish(ctx: Ctx) -> None:
    ctx.state.passed = []


# Citing methods ------------------------------------------------------------------------------
def _cited_methods(ctx: Ctx, seat: int, ids: list[int]) -> list[Paper]:
    if len(set(ids)) != len(ids):
        raise IllegalAction("a method can be cited only once")
    papers = []
    for paper_id in ids:
        try:
            paper = ctx.state.paper(paper_id)
        except KeyError:
            raise IllegalAction(f"M{paper_id} is not a published method") from None
        if paper.kind != "method":
            raise IllegalAction(f"T{paper_id} is a theory, not a method")
        if not ctx.usable_by(paper, seat):
            raise IllegalAction(f"M{paper_id} is Fresh out of print: only its author can use it")
        papers.append(paper)
    return papers


def _cite(ctx: Ctx, papers: list[Paper], citing: int) -> None:
    for paper in papers:
        ctx.credit(paper.author, ctx.settings.experiment_method_citation_AC_reward, f"M{paper.id} cited")


def _check_turn(ctx: Ctx, seat: int) -> None:
    if ctx.state.current != seat:
        raise IllegalAction("it is not your turn")
    if not _can_act(ctx, seat):
        raise IllegalAction("you have no staff member left on experimentation")


# Lab capacity ----------------------------------------------------------------------------------
def check_expand_lab(ctx: Ctx, seat: int) -> int:
    """Raise if the researcher cannot increase their lab capacity now; return the cost."""
    s = ctx.settings
    r = ctx.state.researcher(seat)
    if r.lab_capacity is None or s.starting_lab_capacity_advanced is None:
        raise IllegalAction("this game was started before lab capacity was part of the rules")
    if r.allocated(Task.EXPERIMENTATION) < 1:
        raise IllegalAction("only a researcher with staff on experimentation this round can increase their lab capacity")
    if r.lab_expanded:
        raise IllegalAction("lab capacity can be increased by only 1 per round")
    costs = s.lab_capacity_costs()
    step = r.lab_capacity - s.starting_lab_capacity_advanced
    if not 0 <= step < len(costs):
        raise IllegalAction(f"your lab is at its maximum capacity ({r.lab_capacity})")
    cost = costs[step]
    if cost > ctx.spendable(r):
        if cost <= r.money:
            raise IllegalAction("at 0 academic credit you cannot spend money you need to pay your postdocs")
        raise IllegalAction(f"increasing your lab capacity costs {cost}, you have {r.money} money")
    return cost


def expand_lab(ctx: Ctx, action: ExpandLab) -> None:
    cost = check_expand_lab(ctx, action.seat)
    r = ctx.state.researcher(action.seat)
    r.money -= cost
    r.lab_capacity += 1
    r.lab_expanded = True
    ctx.log("lab_capacity", f"{ctx.name(action.seat)} pays {cost} to increase their lab capacity to {r.lab_capacity}",
            seat=action.seat)


# Running experiments ---------------------------------------------------------------------------
def run_experiment(ctx: Ctx, action: RunExperiment) -> None:
    seat, state, world = action.seat, ctx.state, ctx.world
    _check_turn(ctx, seat)
    for parameter, value in action.specified.items():
        if parameter not in world.input_ids:
            raise IllegalAction(f"{parameter} is not an input parameter")
        if value not in world.variable(parameter).states:
            raise IllegalAction(f"{value!r} is not a state of {parameter}")
    methods = _cited_methods(ctx, seat, action.cited_methods)
    method_parameters = [m.idea.parameter for m in methods]
    if len(set(method_parameters)) != len(method_parameters):
        raise IllegalAction("methods cited for one experiment must be specific to different input parameters")
    for parameter in method_parameters:
        if parameter not in action.specified:
            raise IllegalAction(f"a cited method for {parameter} lets you specify {parameter}: specify its state")
    allowed = ctx.settings.experiment_free_input_parameters + len(methods)
    if len(action.specified) > allowed:
        raise IllegalAction(f"you can specify at most {allowed} input parameter(s) with these methods")

    _cite(ctx, methods, seat)
    experiment_id = state.new_id()
    inputs: dict[str, str] = {}
    cards: list[Card] = []
    for parameter in world.input_ids:
        if parameter in action.specified:
            value = action.specified[parameter]
            cards.append(Card(var=parameter, state=value, origin="supply"))
        else:
            value = ctx.draw_input(parameter)
            cards.append(Card(var=parameter, state=value, origin="input_deck"))
        inputs[parameter] = value
    outcomes = world.outcomes_for(inputs)
    cards += [Card(var=o, state=outcomes[o], origin="supply") for o in world.outcome_ids]
    r = state.researcher(seat)
    r.used[Task.EXPERIMENTATION] = r.used.get(Task.EXPERIMENTATION, 0) + 1
    r.experiments.append(
        Experiment(
            id=experiment_id,
            round=state.round,
            specified=dict(action.specified),
            inputs=inputs,
            outcomes=outcomes,
            cited=list(action.cited_methods),
        )
    )
    # Recording experimental findings
    r.records.cards += [ExperimentCard(experiment=experiment_id, card=c) for c in cards]  # at record position 1
    cited = f" citing {', '.join(f'M{m.id}' for m in methods)}" if methods else ""
    ctx.log("experiment", f"{ctx.name(seat)} runs an experiment{cited}", seat=seat, cited=action.cited_methods)
    shown = ", ".join(f"{k}={v}" for k, v in {**inputs, **outcomes}.items())
    ctx.log(
        "experiment_result",
        f"Experiment E{experiment_id}: {shown}",
        visible_to=[seat],
        experiment=experiment_id,
        inputs=inputs,
        outcomes=outcomes,
    )
    _next_turn(ctx, after=seat)


# Sensor installation and upgrade ----------------------------------------------------------------
def install_sensor(ctx: Ctx, action: InstallSensor) -> None:
    seat, state, s = action.seat, ctx.state, ctx.settings
    _check_turn(ctx, seat)
    if not 0 <= action.probe < len(state.probes):
        raise IllegalAction(f"there is no Probe P{action.probe + 1}")
    probe = state.probes[action.probe]
    if action.parameter not in ctx.world.input_ids:
        raise IllegalAction(f"{action.parameter} is not an input parameter")
    if action.parameter in probe.specialty:
        raise IllegalAction(f"{action.parameter} is a Specialty Input Parameter of P{action.probe + 1}")
    level = probe.sensors.get(action.parameter, 0)
    if level >= MAX_SENSOR_LEVEL:
        raise IllegalAction("this sensor is already at the highest level")
    methods = _cited_methods(ctx, seat, action.cited_methods)
    if any(m.idea.parameter != action.parameter for m in methods):
        raise IllegalAction(f"cite methods specific to {action.parameter}")
    if len(methods) != level + 1:
        raise IllegalAction(f"{'upgrading' if level else 'installing'} this sensor needs {level + 1} method(s)")

    _cite(ctx, methods, seat)
    probe.sensors[action.parameter] = level + 1
    r = state.researcher(seat)
    r.used[Task.EXPERIMENTATION] = r.used.get(Task.EXPERIMENTATION, 0) + 1
    ctx.log(
        "sensor",
        f"{ctx.name(seat)} {'upgrades' if level else 'installs'} the {action.parameter} sensor on "
        f"P{action.probe + 1} to level {level + 1}, citing {', '.join(f'M{m.id}' for m in methods)}",
        seat=seat,
        probe=action.probe,
        parameter=action.parameter,
        level=level + 1,
    )
    if probe.probe_time is None:
        probe.probe_time = seat
        probe.probe_time_from_sensor = True
        ctx.log("probe_time", f"{ctx.name(seat)} gets Probe time on P{action.probe + 1}", seat=seat)
    ctx.credit(seat, s.sensor_install_and_upgrade_AC_reward * (level + 1), "sensor installed or upgraded")
    _next_turn(ctx, after=seat)


def pass_turn(ctx: Ctx, action: Pass) -> None:
    seat = action.seat
    _check_turn(ctx, seat)
    if ctx.state.researcher(seat).credit == 0:
        # An experiment is always possible, so a staff member could still be used.
        raise IllegalAction("at 0 academic credit you must use every staff member that can still be used")
    ctx.state.passed.append(seat)
    ctx.log("pass", f"{ctx.name(seat)} passes")
    _next_turn(ctx, after=seat)


# Probe time ---------------------------------------------------------------------------------
def start_probe_time(ctx: Ctx) -> None:
    state = ctx.state
    holders = {p.probe_time for p in state.probes if p.probe_time is not None}
    order = state.turn_order()
    choosers = [seat for seat in order if seat not in holders]
    choosers.sort(key=lambda seat: (-state.researcher(seat).credit, order.index(seat)))
    state.queue = choosers
    _next_probe_time(ctx)


def _free_probes(ctx: Ctx) -> list[int]:
    return [p.index for p in ctx.state.probes if p.probe_time is None]


def _next_probe_time(ctx: Ctx) -> None:
    state = ctx.state
    state.current = None
    while state.queue:
        free = _free_probes(ctx)
        if not free:
            state.queue = []
            return
        seat = state.queue[0]
        if len(free) == 1:
            _claim(ctx, seat, free[0])
            continue
        state.current = seat
        return


def _claim(ctx: Ctx, seat: int, probe: int) -> None:
    state = ctx.state
    state.probes[probe].probe_time = seat
    state.probes[probe].probe_time_from_sensor = False
    state.queue.remove(seat)
    ctx.log("probe_time", f"{ctx.name(seat)} takes Probe time on P{probe + 1}", seat=seat, probe=probe)


def claim_probe_time(ctx: Ctx, action: ClaimProbeTime) -> None:
    state = ctx.state
    if state.current != action.seat:
        raise IllegalAction("it is not your turn to choose Probe time")
    if action.probe not in _free_probes(ctx):
        raise IllegalAction(f"P{action.probe + 1} is not free")
    _claim(ctx, action.seat, action.probe)
    _next_probe_time(ctx)


def finish_probe_time(ctx: Ctx) -> None:
    ctx.state.queue = []

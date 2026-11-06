"""Helpers for the rules-engine tests: a tiny hand-made world and ways to reach a phase.

The tiny world: IP1 (a, b), IP2 (x, y), IP3 (p, q) and one world outcome WO1 (up, down).
WO1 is "up" exactly when IP1 is "a", so expected results can be worked out by hand.
Game settings come from docs/parameter_defaults.yaml (with overrides where a test needs them).
"""

import itertools

from nv_core import actions as a
from nv_core.engine import apply, new_game
from nv_core.settings import load_settings
from nv_core.state import Card, GameState, Idea, Paper, Phase, StaffCount, Task
from nv_core.world_data import Variable, WorldData, WorldRow

INPUTS = {"IP1": ["a", "b"], "IP2": ["x", "y"], "IP3": ["p", "q"]}
OUTCOMES = {"WO1": ["up", "down"]}


def tiny_world() -> WorldData:
    rows = []
    for combo in itertools.product(*INPUTS.values()):
        inputs = dict(zip(INPUTS, combo))
        rows.append(WorldRow(inputs=inputs, outcomes={"WO1": "up" if inputs["IP1"] == "a" else "down"}))
    return WorldData(
        scenario_id="tiny",
        title="Tiny",
        story="",
        world_id="tiny_world",
        input_parameters=[Variable(id=k, name=k.lower(), states=v) for k, v in INPUTS.items()],
        world_outcomes=[Variable(id=k, name=k.lower(), states=v) for k, v in OUTCOMES.items()],
        rows=rows,
    )


def settings(**overrides):
    return load_settings(overrides)


def game(n: int = 2, seed: int = 1, world: WorldData | None = None, **overrides) -> GameState:
    return new_game(world or tiny_world(), settings(**overrides), seed, [f"R{i}" for i in range(n)])


def do(state: GameState, *actions) -> GameState:
    for action in actions:
        state, _ = apply(state, action)
    return state


def staff(**tasks: int) -> dict[Task, StaffCount]:
    """Postdocs per task, e.g. staff(data_collection=1, write_up=2)."""
    return {Task(t): StaffCount(postdocs=n) for t, n in tasks.items() if n}


def allocate(state: GameState, seat: int, **tasks: int) -> a.AllocateStaff:
    """Hire exactly the postdocs the allocation needs (the test gives the researcher the money)."""
    r = state.researcher(seat)
    total = sum(tasks.values())
    return a.AllocateStaff(
        seat=seat,
        hire_postdocs=max(0, total - r.postdocs),
        fire_postdocs=max(0, r.postdocs - total),
        allocation=staff(**tasks),
    )


def publish(state: GameState, author: int, inputs=None, outcomes=None, parameter=None, fresh=False, tier=1) -> Paper:
    """Put a paper straight into the Published Papers area (test setup)."""
    kind = "method" if parameter else "theory"
    idea = Idea(id=state.new_id(), kind=kind, inputs=inputs or {}, outcomes=outcomes or {}, parameter=parameter)
    paper = Paper(id=state.new_id(), idea=idea, author=author, tier=tier, open_access=False, round=0, fresh=fresh)
    state.published.append(paper)
    return paper


def to_phase(state: GameState, phase: Phase, allocations: dict[int, dict[str, int]] | None = None, money: int = 20) -> GameState:
    """Play the simplest legal choices until ``phase`` is reached.

    In the Hiring phase each researcher gets ``money`` and the postdoc allocation in
    ``allocations`` (no students, so no dice); experiments are passed, Probe time takes the
    first free Probe, and every other step is committed without choices.
    """
    allocations = allocations or {}
    for _ in range(500):
        if state.phase == phase or state.result:
            return state
        if state.phase == Phase.HIRING:
            for seat in list(state.waiting):
                state = state.clone()
                state.researcher(seat).money = money
                state = do(state, allocate(state, seat, **allocations.get(seat, {})), a.CommitPhase(seat=seat))
        elif state.phase == Phase.EXPERIMENTATION:
            state = do(state, a.Pass(seat=state.current))
        elif state.phase == Phase.PROBE_TIME:
            free = next(p.index for p in state.probes if p.probe_time is None)
            state = do(state, a.ClaimProbeTime(seat=state.current, probe=free))
        elif state.phase == Phase.PEER_REVIEW:
            seat = state.waiting[0]
            for i, card in enumerate(state.review_cards.get(seat, [])):
                if card:
                    state = do(state, a.ReviewVote(seat=seat, card=i, vote="accept"))
            state = do(state, a.CommitPhase(seat=seat))
        else:
            state = do(state, a.CommitPhase(seat=state.waiting[0]))
    raise AssertionError(f"did not reach {phase}")


def set_readings(state: GameState, probe: int, readings: dict[str, str | None], outcome: str | None = None) -> None:
    """Overwrite a Probe's visible readings (and WO1) for a test, in place."""
    p = state.probes[probe]
    for var, value in readings.items():
        p.readings[var] = Card(var=var, state=value, origin="supply")
    if outcome is not None:
        p.outcomes["WO1"] = Card(var="WO1", state=outcome, origin="supply")

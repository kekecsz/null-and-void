"""The rules engine (specification section 5): a pure, deterministic state machine.

    state = new_game(world, settings, seed, players)
    state, events = apply(state, action)

``apply`` never changes the state it is given. Automatic steps run until someone has to decide:
``state.waiting`` lists the seats a simultaneous step waits for, ``state.current`` is the seat
to act in a sequential step.
"""

from collections.abc import Callable, Iterable

from pydantic import BaseModel

from nv_core import actions as a
from nv_core.engine import alliances, cleanup, development, experimentation, hiring, observation, publication
from nv_core.engine.context import Ctx, Event, IllegalAction
from nv_core.engine.setup import create_game
from nv_core.settings import Settings
from nv_core.state import GameState, Phase
from nv_core.world_data import WorldData

__all__ = ["Event", "IllegalAction", "Option", "apply", "legal_actions", "new_game", "replay", "validate", "SIMULTANEOUS"]


class _Step:
    def __init__(self, start: Callable[[Ctx], None], finish: Callable[[Ctx], None], commit_check=None):
        self.start, self.finish, self.commit_check = start, finish, commit_check


def _noop(ctx: Ctx) -> None:
    ctx.state.waiting = []


def _start_prediction(ctx: Ctx) -> None:
    observation.deal_probes(ctx)
    observation.start_prediction(ctx)


def _end_of_round(ctx: Ctx) -> None:
    ctx.phase_name = "Talent development phase"
    cleanup.talent_development(ctx)
    ctx.phase_name = "Clean-up phase"
    cleanup.cleanup(ctx)
    ctx.phase_name = ""


# The steps of a round, in rulebook order. ``start`` sets who must decide (or nobody);
# ``finish`` resolves the step once every decision is in.
STEPS: dict[Phase, _Step] = {
    Phase.HIRING: _Step(hiring.start, hiring.finish, hiring.check_commit),
    Phase.LAST_CHANCE: _Step(hiring.start_last_chance, hiring.finish_last_chance),
    Phase.STUDENT_CHECK: _Step(hiring.start_student_check, hiring.finish_student_check, hiring.check_commit_students),
    Phase.EXPERIMENTATION: _Step(experimentation.start, experimentation.finish),
    Phase.PROBE_TIME: _Step(experimentation.start_probe_time, experimentation.finish_probe_time),
    Phase.PREDICTION: _Step(_start_prediction, observation.finish_prediction),
    Phase.REVEAL: _Step(observation.start_reveal, observation.finish_reveal, observation.check_commit_reveal),
    Phase.SCORING_ORDER: _Step(
        observation.start_scoring_order, observation.finish_scoring, observation.check_commit_order
    ),
    Phase.DEVELOPMENT: _Step(development.start, development.finish, development.check_commit),
    Phase.SUBMISSION: _Step(
        publication.start_submission, lambda ctx: None, publication.check_commit_submission
    ),
    Phase.PEER_REVIEW: _Step(
        publication.start_peer_review, publication.finish_peer_review, publication.check_commit_review
    ),
}
ORDER = list(STEPS)

# Steps where every waiting researcher decides in secret and commits.
SIMULTANEOUS = {
    Phase.HIRING,
    Phase.LAST_CHANCE,
    Phase.STUDENT_CHECK,
    Phase.PREDICTION,
    Phase.REVEAL,
    Phase.SCORING_ORDER,
    Phase.DEVELOPMENT,
    Phase.SUBMISSION,
    Phase.PEER_REVIEW,
}


def _advance(ctx: Ctx) -> None:
    """Run automatic steps until a decision is needed or the game is over."""
    state = ctx.state
    while state.result is None and not state.waiting and state.current is None:
        STEPS[state.phase].finish(ctx)
        if state.result:
            return
        index = ORDER.index(state.phase) + 1
        if index == len(ORDER):
            _end_of_round(ctx)
            if state.result:
                return
            state.round += 1
            index = 0
            ctx.log("round", f"Round {state.round} begins")
        state.phase = ORDER[index]
        STEPS[state.phase].start(ctx)


def new_game(world: WorldData, settings: Settings, seed: int, players: list[str]) -> GameState:
    state = create_game(world, settings, seed, players)
    ctx = Ctx(state)
    STEPS[state.phase].start(ctx)
    _advance(ctx)
    return state


def _commit(ctx: Ctx, action: a.CommitPhase) -> None:
    state = ctx.state
    if state.phase not in SIMULTANEOUS or action.seat not in state.waiting:
        raise IllegalAction("there is nothing for you to commit now")
    check = STEPS[state.phase].commit_check
    if check:
        check(ctx, action.seat)
    state.waiting.remove(action.seat)
    ctx.log("commit", f"{ctx.name(action.seat)} is ready")


# action type -> (phase it belongs to, or None for "any time"; handler)
HANDLERS: dict[type, tuple[Phase | None, Callable]] = {
    a.AllocateStaff: (Phase.HIRING, hiring.allocate),
    a.ChooseLeavingStudents: (Phase.STUDENT_CHECK, hiring.choose_leaving),
    a.RunExperiment: (Phase.EXPERIMENTATION, experimentation.run_experiment),
    a.InstallSensor: (Phase.EXPERIMENTATION, experimentation.install_sensor),
    a.Pass: (Phase.EXPERIMENTATION, experimentation.pass_turn),
    a.ExpandLab: (Phase.EXPERIMENTATION, experimentation.expand_lab),
    a.ClaimProbeTime: (Phase.PROBE_TIME, experimentation.claim_probe_time),
    a.MakePrediction: (Phase.PREDICTION, observation.make_prediction),
    a.CancelPrediction: (Phase.PREDICTION, observation.cancel_prediction),
    a.SetPreregistered: (Phase.PREDICTION, observation.set_preregistered),
    a.RevealPrediction: (Phase.REVEAL, observation.reveal_prediction),
    a.OrderPredictions: (Phase.SCORING_ORDER, observation.order_predictions),
    a.FormulateTheory: (Phase.DEVELOPMENT, development.formulate_theory),
    a.DevelopMethod: (Phase.DEVELOPMENT, development.develop_method),
    a.CancelDevelopment: (Phase.DEVELOPMENT, development.cancel_development),
    a.ArchiveRecords: (Phase.DEVELOPMENT, development.archive_records),
    a.Submit: (Phase.SUBMISSION, publication.submit),
    a.Revise: (Phase.SUBMISSION, publication.revise),
    a.WithdrawSubmission: (Phase.SUBMISSION, publication.withdraw_submission),
    a.ReviewVote: (Phase.PEER_REVIEW, publication.review_vote),
    a.ProposeAlliance: (None, alliances.propose),
    a.AcceptAlliance: (None, alliances.accept),
    a.LeaveAlliance: (None, alliances.leave),
    a.StayInAlliance: (Phase.LAST_CHANCE, alliances.stay),
    a.CommitPhase: (None, _commit),
}


def _handle(ctx: Ctx, action: BaseModel) -> None:
    state = ctx.state
    if state.result is not None:
        raise IllegalAction("the game is over")
    if not 0 <= action.seat < state.n_players:
        raise IllegalAction(f"there is no seat {action.seat}")
    phase, handler = HANDLERS[type(action)]
    if phase is not None:
        if state.phase != phase:
            raise IllegalAction(f"this action belongs to the {phase.value}; the game is in the {state.phase.value}")
        if phase in SIMULTANEOUS and action.seat not in state.waiting:
            raise IllegalAction("you have nothing to decide in this step, or you have committed already")
    handler(ctx, action)


def apply(state: GameState, action: BaseModel) -> tuple[GameState, list[Event]]:
    """Apply one action to a copy of ``state``; raise IllegalAction if it is not legal now."""
    new = state.clone()
    ctx = Ctx(new)
    _handle(ctx, action)
    _advance(ctx)
    return new, ctx.events


def validate(state: GameState, action: BaseModel) -> str | None:
    """None if the action is legal now, otherwise the reason it is refused."""
    try:
        apply(state, action)
    except IllegalAction as exc:
        return str(exc)
    return None


def replay(world: WorldData, settings: Settings, seed: int, players: list[str], actions: Iterable[BaseModel]) -> GameState:
    """Rebuild a game from its setup and action log (design principle 3)."""
    state = new_game(world, settings, seed, players)
    for action in actions:
        state, _ = apply(state, action)
    return state


from nv_core.engine.legal import Option, legal_actions  # noqa: E402  (legal imports the step modules above)

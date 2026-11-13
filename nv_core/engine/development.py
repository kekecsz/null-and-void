"""Development phase: formulating theories, developing methods and archiving records."""

from nv_core.actions import ArchiveRecords, CancelDevelopment, DevelopMethod, FormulateTheory
from nv_core.engine.context import Ctx, IllegalAction
from nv_core.engine.records import positions
from nv_core.state import Idea, Researcher, Task


def start(ctx: Ctx) -> None:
    state = ctx.state
    for pending in state.pending:
        pending.development = []
        pending.archive = []
    state.waiting = [s for s in state.turn_order() if state.researcher(s).allocated(Task.DEVELOPMENT)]


def archive_staff(ctx: Ctx, records: int) -> int:
    """Archiving records: the staff members needed for this many records."""
    per = ctx.settings.max_archive_per_staff_member
    return -(-records // per) if records and per else 0


def staff_chosen(ctx: Ctx, seat: int) -> int:
    """The development staff members this phase's choices use."""
    pending = ctx.state.pending[seat]
    return len(pending.development) + archive_staff(ctx, len(pending.archive))


def _check_room(ctx: Ctx, seat: int) -> None:
    staff = ctx.state.researcher(seat).allocated(Task.DEVELOPMENT)
    if staff_chosen(ctx, seat) >= staff:
        raise IllegalAction(f"you have {staff} staff member(s) on development")


def slip_name(r: Researcher, slip: int) -> str:
    return f"O{slip}" if any(o.id == slip for o in r.records.observations) else f"E{slip}"


def archive_records(ctx: Ctx, action: ArchiveRecords) -> None:
    per = ctx.settings.max_archive_per_staff_member
    if per is None:
        raise IllegalAction("this game was started before archiving records was part of the rules")
    r = ctx.state.researcher(action.seat)
    if len(set(action.records)) != len(action.records):
        raise IllegalAction("a record is named twice")
    available = positions(r)
    for slip in action.records:
        if slip in r.archived:
            raise IllegalAction(f"{slip_name(r, slip)} is archived already")
        if slip not in available:
            raise IllegalAction(f"you have no record {slip}")
    needed = archive_staff(ctx, len(action.records))
    free = r.allocated(Task.DEVELOPMENT) - len(ctx.state.pending[action.seat].development)
    if needed > free:
        raise IllegalAction(
            f"archiving {len(action.records)} record(s) needs {needed} development staff member(s) "
            f"(at most {per} records each); you have {free} free"
        )
    ctx.state.pending[action.seat].archive = list(action.records)


def _ordered(ctx: Ctx, values: dict[str, str], ids: list[str], what: str) -> dict[str, str]:
    for var, state in values.items():
        if var not in ids:
            raise IllegalAction(f"{var} is not {what}")
        if state not in ctx.world.variable(var).states:
            raise IllegalAction(f"{state!r} is not a state of {var}")
    return {var: values[var] for var in ids if var in values}


def formulate_theory(ctx: Ctx, action: FormulateTheory) -> None:
    _check_room(ctx, action.seat)
    inputs = _ordered(ctx, action.inputs, ctx.world.input_ids, "an input parameter")
    outcomes = _ordered(ctx, action.outcomes, ctx.world.outcome_ids, "a world outcome")
    if not inputs or not outcomes:
        raise IllegalAction("a theory specifies at least one input parameter and at least one world outcome")
    for paper in ctx.state.published:
        if paper.kind == "theory" and paper.idea.inputs == inputs and paper.idea.outcomes == outcomes:
            raise IllegalAction(f"this theory is already published as T{paper.id}")
    ctx.state.pending[action.seat].development.append(Idea(id=0, kind="theory", inputs=inputs, outcomes=outcomes))


def develop_method(ctx: Ctx, action: DevelopMethod) -> None:
    _check_room(ctx, action.seat)
    if action.parameter not in ctx.world.input_ids:
        raise IllegalAction(f"{action.parameter} is not an input parameter")
    ctx.state.pending[action.seat].development.append(Idea(id=0, kind="method", parameter=action.parameter))


def cancel_development(ctx: Ctx, action: CancelDevelopment) -> None:
    choices = ctx.state.pending[action.seat].development
    if not 0 <= action.index < len(choices):
        raise IllegalAction(f"there is no development choice number {action.index + 1}")
    choices.pop(action.index)


def check_commit(ctx: Ctx, seat: int) -> None:
    r = ctx.state.researcher(seat)
    if r.credit == 0 and staff_chosen(ctx, seat) < r.allocated(Task.DEVELOPMENT):
        # A method can always be developed, so every development staff member can be used.
        raise IllegalAction("at 0 academic credit you must use every staff member that can still be used")


def finish(ctx: Ctx) -> None:
    state = ctx.state
    for seat in state.turn_order():
        r = state.researcher(seat)
        made = state.pending[seat].development
        for idea in made:
            idea.id = state.new_id()
            r.ideas.append(idea)
        r.used[Task.DEVELOPMENT] = staff_chosen(ctx, seat)
        archive = state.pending[seat].archive
        if archive:
            r.archived += archive
            ctx.log("archive", f"{ctx.name(seat)} archives {len(archive)} record(s)", seat=seat)
            ctx.log("archive_private", "Archived: " + ", ".join(slip_name(r, s) for s in archive), visible_to=[seat])
        state.pending[seat].archive = []
        if made:
            ctx.log("development", f"{ctx.name(seat)} adds {len(made)} development stack(s)", seat=seat)
            ctx.log(
                "development_private",
                "New: " + ", ".join(f"D{i.id}" for i in made),
                visible_to=[seat],
            )
        state.pending[seat].development = []

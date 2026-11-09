"""Hiring and task allocation phase, the Game Period Deck, the alliance "last chance to leave"
stage, and the Student task check phase."""

from nv_core.actions import AllocateStaff, ChooseLeavingStudents
from nv_core.engine.context import Ctx, IllegalAction
from nv_core.state import Phase, Researcher, StaffCount, Task

POSTDOC_ONLY = (Task.DEVELOPMENT, Task.TALENT_DEVELOPMENT)


# Hiring and task allocation ------------------------------------------------------------------
def start(ctx: Ctx) -> None:
    state = ctx.state
    state.waiting = state.turn_order()
    for pending in state.pending:
        pending.allocation = None


def check_allocation(ctx: Ctx, r: Researcher, a: AllocateStaff) -> None:
    s = ctx.settings
    if min(a.hire_postdocs, a.fire_postdocs, a.hire_students) < 0:
        raise IllegalAction("staff numbers cannot be negative")
    if a.fire_postdocs > r.postdocs:
        raise IllegalAction(f"you have only {r.postdocs} postdoc(s) to fire")
    if a.fire_postdocs and r.credit == 0:
        # Academic credit rules: only the un-fundable postdocs, which they must fire.
        affordable = r.money // s.cost_of_postdoc if s.cost_of_postdoc else r.postdocs
        if a.hire_postdocs or a.fire_postdocs > max(0, r.postdocs - affordable):
            raise IllegalAction(
                "at 0 academic credit you cannot fire a postdoc, except those you cannot afford (Academic credit rules)"
            )
    postdocs = r.postdocs + a.hire_postdocs - a.fire_postdocs
    if postdocs * s.cost_of_postdoc > r.money:
        raise IllegalAction(
            f"paying {postdocs} postdoc(s) would cost {postdocs * s.cost_of_postdoc}, you have {r.money} money"
        )
    cap = s.student_hire_cap(r.talent_position)
    if a.hire_students > cap:
        raise IllegalAction(f"you can hire at most {cap} students")
    if any(c.postdocs < 0 or c.students < 0 for c in a.allocation.values()):
        raise IllegalAction("staff numbers cannot be negative")
    allocated_postdocs = sum(c.postdocs for c in a.allocation.values())
    allocated_students = sum(c.students for c in a.allocation.values())
    if allocated_postdocs != postdocs or allocated_students != a.hire_students:
        raise IllegalAction(
            f"allocate every staff member: {postdocs} postdoc(s) and {a.hire_students} student(s) "
            f"(you allocated {allocated_postdocs} and {allocated_students})"
        )
    for task in POSTDOC_ONLY:
        if a.allocation.get(task, StaffCount()).students:
            raise IllegalAction(f"{task.value} is a postdoc-only task")
    if a.allocation.get(Task.TALENT_DEVELOPMENT, StaffCount()).total > 1:
        raise IllegalAction("only one staff member can be allocated to talent development")


def allocate(ctx: Ctx, action: AllocateStaff) -> None:
    check_allocation(ctx, ctx.state.researcher(action.seat), action)
    ctx.state.pending[action.seat].allocation = action.model_dump(mode="json")


def check_commit(ctx: Ctx, seat: int) -> None:
    if ctx.state.pending[seat].allocation is None:
        r = ctx.state.researcher(seat)
        if r.postdocs:
            raise IllegalAction("allocate your staff first")


def finish(ctx: Ctx) -> None:
    state, s = ctx.state, ctx.settings
    for seat in state.turn_order():
        r = state.researcher(seat)
        data = state.pending[seat].allocation
        a = AllocateStaff.model_validate(data) if data else AllocateStaff(seat=seat)
        r.postdocs = r.postdocs + a.hire_postdocs - a.fire_postdocs
        r.students = a.hire_students
        r.staff = {task: StaffCount(**dict(count)) for task, count in a.allocation.items() if count.total}
        r.last_allocation = {task: count.model_copy() for task, count in r.staff.items()}
        r.used = {}
        r.fired = a.fire_postdocs
        r.unpaid = 0
        r.publications_this_round = 0
        mat = ", ".join(f"{t.value} {c.postdocs}p+{c.students}s" for t, c in r.staff.items()) or "none"
        ctx.log(
            "allocation",
            f"{ctx.name(seat)} hired {a.hire_postdocs} postdoc(s), fired {a.fire_postdocs}, "
            f"hired {a.hire_students} student(s); staff allocation: {mat}",
            seat=seat,
            allocation=data,
        )
        if a.fire_postdocs:
            ctx.credit(seat, s.fired_postdoc_penalty * a.fire_postdocs, "fired postdocs")
        state.pending[seat].allocation = None
    reveal_period_cards(ctx)


def reveal_period_cards(ctx: Ctx) -> None:
    """End of the Hiring and task allocation phase: reveal Game Period cards (see also Crisis).
    A lab counts for at least its minimum (specification 5.7)."""
    state = ctx.state
    minimum = ctx.settings.min_cards_burn_each_round_per_player
    total = sum(max(minimum, r.postdocs + r.students) for r in state.researchers)
    revealed, state.period_deck = state.period_deck[:total], state.period_deck[total:]
    ctx.log("period_deck", f"{len(revealed)} Game Period card(s) revealed; {len(state.period_deck)} left")
    if "w" in revealed:
        state.warning_revealed = True
        ctx.log("warning_shot", "The Warning shot card is revealed: last chance to leave alliances")
    if "x" in revealed:
        state.crisis_revealed = True
        state.period = "crisis"
        state.rounds_in_crisis = 1
        state.unsuccessful_predictions = 0
        state.proposals = []
        ctx.log("crisis", "The Crisis card is revealed: the Crisis period starts")


# Alliance: last chance to leave ---------------------------------------------------------------
def start_last_chance(ctx: Ctx) -> None:
    state = ctx.state
    if not state.warning_revealed or state.last_chance_done:
        state.waiting = []
        return
    members = sorted({seat for pair in state.alliances for seat in pair})
    state.waiting = [seat for seat in state.turn_order() if seat in members]
    for pending in state.pending:
        pending.leave_alliances = []
    if not state.waiting:
        state.last_chance_done = True


def finish_last_chance(ctx: Ctx) -> None:
    state = ctx.state
    if state.last_chance_done or not state.warning_revealed:
        return
    for seat in state.turn_order():
        for partner in state.pending[seat].leave_alliances:
            pair = sorted((seat, partner))
            if pair in state.alliances:
                state.alliances.remove(pair)
                ctx.log("alliance", f"{ctx.name(seat)} leaves the alliance with {ctx.name(partner)}")
        state.pending[seat].leave_alliances = []
    state.last_chance_done = True
    ctx.log("alliance", "Alliances are now unbreakable")


# Student task check -------------------------------------------------------------------------
def start_student_check(ctx: Ctx) -> None:
    state, s = ctx.state, ctx.settings
    state.waiting = []
    for seat in state.turn_order():
        r = state.researcher(seat)
        r.leaving_students = 0
        state.pending[seat].leaving_students = None
        students = sum(c.students for c in r.staff.values())
        if not students:
            continue
        threshold = s.student_leave_threshold(r.talent_position)
        dice = ctx.rng.dice("dice", students)
        leaving = sum(1 for d in dice if d < threshold)
        r.leaving_students = leaving
        ctx.log(
            "student_check",
            f"{ctx.name(seat)} rolls {dice} for {students} student(s): {leaving} below {threshold} leave",
            seat=seat,
            dice=dice,
            leaving=leaving,
        )
        tasks_with_students = [t for t, c in r.staff.items() if c.students]
        if leaving == 0:
            continue
        if leaving >= students or len(tasks_with_students) == 1:
            remove_students(ctx, r, {t: r.staff[t].students for t in tasks_with_students}, leaving)
            r.leaving_students = 0
        else:
            state.waiting.append(seat)


def remove_students(ctx: Ctx, r: Researcher, available: dict[Task, int], count: int) -> None:
    """Remove ``count`` students, taking them from the tasks in ``available`` in that order."""
    left = count
    for task, n in available.items():
        take = min(n, left)
        if take:
            r.staff[task].students -= take
            r.students -= take
            left -= take
            ctx.log("student_leaves", f"{take} of {ctx.name(r.seat)}'s student(s) on {task.value} leave the lab")
    r.staff = {t: c for t, c in r.staff.items() if c.total}


def choose_leaving(ctx: Ctx, action: ChooseLeavingStudents) -> None:
    r = ctx.state.researcher(action.seat)
    if sum(action.by_task.values()) != r.leaving_students:
        raise IllegalAction(f"choose exactly {r.leaving_students} student(s)")
    for task, n in action.by_task.items():
        if n < 0 or n > r.staff.get(task, StaffCount()).students:
            raise IllegalAction(f"you do not have {n} student(s) on {task.value}")
    ctx.state.pending[action.seat].leaving_students = dict(action.by_task)


def check_commit_students(ctx: Ctx, seat: int) -> None:
    if ctx.state.pending[seat].leaving_students is None:
        raise IllegalAction("choose which students leave first")


def finish_student_check(ctx: Ctx) -> None:
    state = ctx.state
    for seat in state.turn_order():
        choice = state.pending[seat].leaving_students
        r = state.researcher(seat)
        if choice is not None and r.leaving_students:
            remove_students(ctx, r, choice, r.leaving_students)
            r.leaving_students = 0
        state.pending[seat].leaving_students = None


PHASE = Phase.HIRING

"""Retirement (normal game only): early retirement as an Emeritus Professor.

A researcher whose new Tier 5 publication leaves them with at least two Tier 5 papers in the
Published Papers area decides, in the Clean-up phase, whether to retire; several researchers decide
in secret at the same time. Retirement is for the rest of the game: no staff on Data collection, no
loss in a Crisis Crash, and the [retirement_bonus] when the Crisis ends, if they then still have two
such papers and nobody won the Nobel Prize. Only possible before the Crisis.

"Tier 5" is read as the top journal tier of the parameter file (specification 5.7).
"""

from nv_core.actions import DecideRetirement
from nv_core.engine.context import Ctx, IllegalAction
from nv_core.state import GameState, Paper


def top_tier(state: GameState) -> int:
    return len(state.settings.journal_tiers) - 1


def in_play(state: GameState) -> bool:
    """The rule is in this game: the normal game, saved after the rule existed."""
    return state.settings.retirement_bonus is not None and not state.settings.simplified


def top_papers(state: GameState, seat: int) -> int:
    """The researcher's Tier 5 papers in the Published Papers area (retracted ones are gone)."""
    return sum(1 for p in state.published if p.author == seat and p.tier == top_tier(state))


def due(ctx: Ctx, published: list[Paper]) -> None:
    """Clean-up phase, publication: who now decides whether to retire."""
    state = ctx.state
    if not in_play(state) or state.crisis_revealed:
        state.retirement_due = []
        return
    new = {p.author for p in published if p.tier == top_tier(state)}
    state.retirement_due = [seat for seat in state.turn_order()
                            if seat in new and not state.researcher(seat).retired and top_papers(state, seat) >= 2]


def start(ctx: Ctx) -> None:
    state = ctx.state
    state.waiting = list(state.retirement_due)
    for pending in state.pending:
        pending.retire = None


def decide(ctx: Ctx, action: DecideRetirement) -> None:
    if action.seat not in ctx.state.waiting:
        raise IllegalAction("you have no retirement decision to make")
    ctx.state.pending[action.seat].retire = action.retire


def check_commit(ctx: Ctx, seat: int) -> None:
    if ctx.state.pending[seat].retire is None:
        raise IllegalAction("decide whether to retire first")


def finish(ctx: Ctx) -> None:
    """The decisions are revealed at the same time."""
    state = ctx.state
    for seat in state.retirement_due:
        choice = state.pending[seat].retire
        if choice:
            state.researcher(seat).retired = True
            ctx.log("retirement", f"{ctx.name(seat)} retires as an Emeritus Professor", seat=seat, retired=True)
        else:
            ctx.log("retirement", f"{ctx.name(seat)} does not retire", seat=seat, retired=False)
        state.pending[seat].retire = None
    state.retirement_due = []


def survivors(state: GameState) -> list[int]:
    """Retired researchers do not lose in a Crisis Crash."""
    return [r.seat for r in state.researchers if r.retired]


def bonus(ctx: Ctx) -> None:
    """When the Crisis ends without a Nobel Prize: [retirement_bonus] to each retired researcher who
    still has at least two Tier 5 papers in the Published Papers area."""
    state = ctx.state
    if not in_play(state):
        return
    for seat in survivors(state):
        if top_papers(state, seat) >= 2:
            ctx.credit(seat, state.settings.retirement_bonus, "retirement bonus")

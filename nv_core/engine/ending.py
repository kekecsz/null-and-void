"""Ending the game (Victory, Nobel Prize, Crisis, Academic credit rules, Alliance)."""

from nv_core.engine import retirement
from nv_core.engine.context import Ctx
from nv_core.state import GameResult, Phase


def allies(ctx: Ctx, seat: int) -> list[int]:
    """The direct allies of a researcher (Alliance)."""
    return sorted(other for pair in ctx.state.alliances if seat in pair for other in pair if other != seat)


def end_game(ctx: Ctx, ending: str, primary: list[int], theory: int | None = None) -> None:
    state = ctx.state
    winners = set(primary)
    for seat in primary:
        winners.update(allies(ctx, seat))
    state.result = GameResult(ending=ending, winners=sorted(winners), primary=sorted(primary), theory=theory)
    state.phase = Phase.GAME_OVER
    state.waiting = []
    state.current = None
    names = ", ".join(ctx.name(s) for s in sorted(winners)) or "nobody"
    ctx.log("game_over", f"Game over ({ending.replace('_', ' ')}). Winners: {names}", ending=ending)


def credit_victory(ctx: Ctx, seats: list[int] | None = None) -> list[int]:
    """The researchers who win an academic credit victory (Victory; Academic credit rules), among
    ``seats`` (the survivors of the Crisis; default everyone)."""
    state = ctx.state
    field = [r for r in state.researchers if seats is None or r.seat in seats]
    best = max(r.credit for r in field)
    leaders = [r.seat for r in field if r.credit == best]

    def theories(seat: int) -> int:
        return sum(1 for p in state.published if p.author == seat and p.kind == "theory")

    most = max(theories(seat) for seat in leaders)
    return [seat for seat in leaders if theories(seat) == most]


def nobel_at_crisis_end(ctx: Ctx, seats: list[int] | None = None) -> bool:
    """Nobel Prize: checked once more when the Crisis ends. Of the theories at or above their
    threshold, the one furthest above it wins; on a tie the authors share the prize. Only the
    theories of ``seats`` count (the survivors of a Crisis Crash; default everyone)."""
    state, s = ctx.state, ctx.settings
    above = {p.id: p.nobel - s.nobel_threshold(p.tier) for p in state.published
             if p.kind == "theory" and p.nobel >= s.nobel_threshold(p.tier) and (seats is None or p.author in seats)}
    if not above:
        return False
    best = max(above.values())
    theories = sorted(t for t, margin in above.items() if margin == best)
    for t in theories:
        ctx.log("nobel", f"T{t} is at {state.paper(t).nobel} on its Nobel Prize counter when the Crisis ends")
    # GameResult holds one theory: on a shared prize, the earliest published of them.
    end_game(ctx, "nobel", sorted({state.paper(t).author for t in theories}), theory=theories[0])
    return True


def crisis_end(ctx: Ctx, ending: str, seats: list[int] | None = None, nobel: bool = True) -> None:
    """When the Crisis ends (after its last round, or in a Crisis Crash): the Nobel Prize check (not
    after a Crisis Crash), then the retirement bonus if nobody won it, then the academic credit
    victory, among ``seats``."""
    if nobel and nobel_at_crisis_end(ctx, seats):
        return
    retirement.bonus(ctx)
    end_game(ctx, ending, credit_victory(ctx, seats))


def check_crisis_crash(ctx: Ctx) -> bool:
    """Crisis Crash: the non-retired researchers lose, and their alliances break; retired researchers
    survive, and the Crisis ends for them: no Nobel Prize, the retirement bonus, then the academic
    credit victory among them (Crisis; Retirement)."""
    state = ctx.state
    if state.period == "crisis" and state.unsuccessful_predictions >= ctx.settings.crisis_condition:
        ctx.log("crisis_crash", f"{state.unsuccessful_predictions} unsuccessful predictions: Crisis Crash")
        survivors = retirement.survivors(state)
        if not survivors:
            end_game(ctx, "crisis_crash", [])
            return True
        state.alliances = [pair for pair in state.alliances if all(seat in survivors for seat in pair)]
        crisis_end(ctx, "crisis_crash", survivors, nobel=False)
        return True
    return False

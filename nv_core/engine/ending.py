"""Ending the game (Victory, Nobel Prize, Crisis, Academic credit rules, Alliance)."""

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


def credit_victory(ctx: Ctx) -> list[int]:
    """The researchers who win an academic credit victory (Victory; Academic credit rules)."""
    state = ctx.state
    best = max(r.credit for r in state.researchers)
    leaders = [r.seat for r in state.researchers if r.credit == best]

    def theories(seat: int) -> int:
        return sum(1 for p in state.published if p.author == seat and p.kind == "theory")

    most = max(theories(seat) for seat in leaders)
    return [seat for seat in leaders if theories(seat) == most]


def nobel_at_crisis_end(ctx: Ctx) -> bool:
    """Nobel Prize: checked once more when the Crisis ends. Of the theories at or above their
    threshold, the one furthest above it wins; on a tie the authors share the prize."""
    state, s = ctx.state, ctx.settings
    above = {p.id: p.nobel - s.nobel_threshold(p.tier) for p in state.published
             if p.kind == "theory" and p.nobel >= s.nobel_threshold(p.tier)}
    if not above:
        return False
    best = max(above.values())
    theories = sorted(t for t, margin in above.items() if margin == best)
    for t in theories:
        ctx.log("nobel", f"T{t} is at {state.paper(t).nobel} on its Nobel Prize counter when the Crisis ends")
    # GameResult holds one theory: on a shared prize, the earliest published of them.
    end_game(ctx, "nobel", sorted({state.paper(t).author for t in theories}), theory=theories[0])
    return True


def check_crisis_crash(ctx: Ctx) -> bool:
    state = ctx.state
    if state.period == "crisis" and state.unsuccessful_predictions >= ctx.settings.crisis_condition:
        ctx.log("crisis_crash", f"{state.unsuccessful_predictions} unsuccessful predictions: Crisis Crash")
        end_game(ctx, "crisis_crash", [])
        return True
    return False

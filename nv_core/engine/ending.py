"""Ending the game (Victory, Nobel Prize, Crisis, Academic credit rules, Alliance)."""

from nv_core.engine.context import Ctx
from nv_core.state import GameResult, Phase


def allies(ctx: Ctx, seat: int) -> list[int]:
    """Direct allies only: alliance victory is not transitional (Alliance)."""
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
    """Highest academic credit; ties go to the most published theories, then a tied victory."""
    state = ctx.state
    best = max(r.credit for r in state.researchers)
    leaders = [r.seat for r in state.researchers if r.credit == best]

    def theories(seat: int) -> int:
        return sum(1 for p in state.published if p.author == seat and p.kind == "theory")

    most = max(theories(seat) for seat in leaders)
    return [seat for seat in leaders if theories(seat) == most]


def check_crisis_crash(ctx: Ctx) -> bool:
    state = ctx.state
    if state.period == "crisis" and state.unsuccessful_predictions >= ctx.settings.crisis_condition:
        ctx.log("crisis_crash", f"{state.unsuccessful_predictions} unsuccessful predictions: Crisis Crash")
        end_game(ctx, "crisis_crash", [])
        return True
    return False

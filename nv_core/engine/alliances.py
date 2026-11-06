"""Alliance actions, which researchers can take at any time the rulebook allows."""

from nv_core.actions import AcceptAlliance, LeaveAlliance, ProposeAlliance, StayInAlliance
from nv_core.engine.context import Ctx, IllegalAction
from nv_core.state import Phase


def _partner(ctx: Ctx, seat: int, partner: int) -> list[int]:
    if not 0 <= partner < ctx.state.n_players or partner == seat:
        raise IllegalAction("choose another researcher")
    return sorted((seat, partner))


def propose(ctx: Ctx, action: ProposeAlliance) -> None:
    state = ctx.state
    pair = _partner(ctx, action.seat, action.partner)
    if state.crisis_revealed:
        raise IllegalAction("alliances can only be formed before the Crisis card is revealed")
    if pair in state.alliances:
        raise IllegalAction("you are already allied")
    if [action.partner, action.seat] in state.proposals:
        accept(ctx, AcceptAlliance(seat=action.seat, partner=action.partner))
        return
    if [action.seat, action.partner] not in state.proposals:
        state.proposals.append([action.seat, action.partner])
    ctx.log("alliance", f"{ctx.name(action.seat)} proposes an alliance to {ctx.name(action.partner)}")


def accept(ctx: Ctx, action: AcceptAlliance) -> None:
    state = ctx.state
    pair = _partner(ctx, action.seat, action.partner)
    if state.crisis_revealed:
        raise IllegalAction("alliances can only be formed before the Crisis card is revealed")
    if [action.partner, action.seat] not in state.proposals:
        raise IllegalAction(f"{ctx.name(action.partner)} has not proposed an alliance to you")
    state.proposals.remove([action.partner, action.seat])
    state.alliances.append(pair)
    ctx.log("alliance", f"{ctx.name(action.seat)} and {ctx.name(action.partner)} form a formal alliance")


def leave(ctx: Ctx, action: LeaveAlliance) -> None:
    state = ctx.state
    pair = _partner(ctx, action.seat, action.partner)
    if pair not in state.alliances:
        raise IllegalAction("you are not allied")
    if state.phase == Phase.LAST_CHANCE and action.seat in state.waiting:
        choices = state.pending[action.seat].leave_alliances
        if action.partner not in choices:
            choices.append(action.partner)  # revealed with everyone's choices at the end of the stage
        return
    if state.warning_revealed:
        raise IllegalAction("alliances are unbreakable after the Warning shot card")
    state.alliances.remove(pair)
    ctx.log("alliance", f"{ctx.name(action.seat)} leaves the alliance with {ctx.name(action.partner)}")


def stay(ctx: Ctx, action: StayInAlliance) -> None:
    """Withdraw a leave choice in the "last chance to leave" stage before committing."""
    state = ctx.state
    if state.phase != Phase.LAST_CHANCE or action.seat not in state.waiting:
        raise IllegalAction("there is no leave choice to withdraw now")
    choices = state.pending[action.seat].leave_alliances
    if action.partner in choices:
        choices.remove(action.partner)

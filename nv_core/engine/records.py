"""The Records area (Recording experimental findings, Recording observations, Archiving records,
Clean-up phase).

A record slip is one experiment's cards or one observation. Slips sit in numbered record
positions, the newest at position 1; archived slips have no position. Ids grow with time, so a
slip's id gives its place: a slip that leaves (used up, or archived) closes the gap behind it.
"""

from nv_core.engine.context import Ctx
from nv_core.state import Researcher


def slips(r: Researcher) -> list[int]:
    """Every record slip of the researcher, archived ones included, newest first."""
    ids = {o.id for o in r.records.observations} | {c.experiment for c in r.records.cards}
    return sorted(ids, reverse=True)


def positions(r: Researcher) -> list[int]:
    """The slips in record positions, in position order (the first is position 1)."""
    archived = set(r.archived)
    return [slip for slip in slips(r) if slip not in archived]


def valid(ctx: Ctx, r: Researcher, slip: int) -> bool:
    """A slip stays valid while it holds at least one input parameter and one world outcome card
    (open question R4: an invalid slip is discarded at Clean-up)."""
    if any(o.id == slip for o in r.records.observations):
        return True
    variables = {c.card.var for c in r.records.cards if c.experiment == slip}
    return bool(variables & set(ctx.world.input_ids)) and bool(variables & set(ctx.world.outcome_ids))


def discard(ctx: Ctx, r: Researcher, ids: set[int]) -> None:
    for observation in r.records.observations:
        if observation.id in ids:
            for card in observation.cards:
                ctx.discard_card(card)
    for item in r.records.cards:
        if item.experiment in ids:
            ctx.discard_card(item.card)
    r.records.observations = [o for o in r.records.observations if o.id not in ids]
    r.records.cards = [c for c in r.records.cards if c.experiment not in ids]


def clean_up(ctx: Ctx, r: Researcher) -> None:
    """Clean-up phase: invalid slips go, then the slips in positions beyond the Records capacity."""
    invalid = {slip for slip in slips(r) if not valid(ctx, r, slip)}
    capacity = ctx.settings.records_capacity  # None: a game saved before the Records capacity
    kept = [slip for slip in positions(r) if slip not in invalid]  # the gaps close first
    beyond = set(kept[capacity:]) if capacity is not None else set()
    discard(ctx, r, invalid | beyond)
    present = set(slips(r))
    r.archived = [slip for slip in r.archived if slip in present]
    if invalid or beyond:
        parts = [f"{len(beyond)} beyond the Records capacity"] if beyond else []
        parts += [f"{len(invalid)} no longer valid"] if invalid else []
        ctx.log("records_discarded", f"{ctx.name(r.seat)} discards record(s): {', '.join(parts)}", visible_to=[r.seat])

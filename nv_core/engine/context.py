"""Shared engine helpers: the action context, events, academic credit and card movements."""

from typing import Any

from pydantic import BaseModel, ConfigDict

from nv_core.rng import Rng
from nv_core.state import Card, GameState, Paper, Researcher, Task

# Hiring and task allocation phase: the tasks of the simplified game.
SIMPLIFIED_TASKS = (Task.EXPERIMENTATION, Task.DATA_COLLECTION, Task.DEVELOPMENT)


class IllegalAction(ValueError):
    """The action is not legal now; the message says why."""


class Event(BaseModel):
    """Something that happened. ``visible_to`` None means public; otherwise only these seats
    (and spectators) see it (specification section 5.4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    round: int
    phase: str
    kind: str
    text: str
    visible_to: list[int] | None = None
    data: dict[str, Any] = {}


def label(seat: int, state: GameState) -> str:
    return state.players[seat]


class Ctx:
    """One engine call: the state being changed, its random streams and the events produced."""

    def __init__(self, state: GameState):
        self.state = state
        self.settings = state.settings
        self.world = state.world
        self.rng = Rng(state.seed, state.rng)
        self.events: list[Event] = []
        self.phase_name = ""

    # Events ---------------------------------------------------------------------------------
    def log(self, kind: str, text: str, visible_to: list[int] | None = None, **data: Any) -> None:
        event = Event(
            round=self.state.round,
            phase=self.phase_name or self.state.phase.value,
            kind=kind,
            text=text,
            visible_to=visible_to,
            data=data,
        )
        self.events.append(event)
        self.state.report_events.append(event.model_dump(mode="json"))  # for the phase reports

    def name(self, seat: int) -> str:
        return self.state.players[seat]

    # Academic credit (Academic credit rules: never below 0) -----------------------------------
    def credit(self, seat: int, amount: int, reason: str) -> None:
        if amount == 0:
            return
        researcher = self.state.researcher(seat)
        before = researcher.credit
        researcher.credit = max(0, before + amount)
        change = researcher.credit - before
        self.log(
            "credit",
            f"{self.name(seat)} {amount:+d} academic credit ({reason}); now {researcher.credit}",
            seat=seat,
            amount=amount,
            applied=change,
            reason=reason,
        )

    # Game modes -------------------------------------------------------------------------------
    def tasks(self) -> list[Task]:
        """Hiring and task allocation phase: the tasks staff can be allocated to."""
        return list(SIMPLIFIED_TASKS) if self.settings.simplified else list(Task)

    def student_cap(self, researcher: Researcher) -> int:
        """Hiring and task allocation phase: the most students a researcher may hire (none in the
        simplified game)."""
        return 0 if self.settings.simplified else self.settings.student_hire_cap(researcher.talent_position)

    def must_use_staff(self, researcher: Researcher) -> bool:
        """Academic credit rules: at 0 credit, leaving a staff member unused would cause the unused
        staff penalty, so every staff member that can be used must be. The simplified game has no
        such penalty (Task resolution)."""
        return researcher.credit == 0 and not self.settings.simplified

    # Spending (Academic credit rules: at 0 credit, keep enough to pay the postdocs) -------------
    def spendable(self, researcher: Researcher) -> int:
        if researcher.credit == 0:
            return max(0, researcher.money - researcher.postdocs * self.settings.cost_of_postdoc)
        return researcher.money

    # Input Parameter Decks (Revealing input parameters) --------------------------------------
    def draw_input(self, parameter: str) -> str:
        deck = self.state.input_decks[parameter]
        if not deck:
            discard = self.state.input_discards[parameter]
            if not discard:
                # Every card of this deck is held in records or manuscripts (specification 5.7).
                deck.extend(build_input_deck(self, parameter))
                self.log("deck", f"Input Parameter Deck {parameter} rebuilt (all cards in use)")
            else:
                deck.extend(discard)
                discard.clear()
                self.log("deck", f"Input Parameter Deck {parameter} reshuffled from its discard pile")
            self.rng.shuffle("input_decks", deck)
        return deck.pop(0)

    def discard_card(self, card: Card) -> None:
        if card.origin == "input_deck" and card.state is not None:
            self.state.input_discards[card.var].append(card.state)
        elif card.origin == "probe":
            self.state.probe_discard.append(card)
        # State Cards go back to the general supply, which is unlimited.

    # Probe deck (Revealing input parameters; specification 5.7) --------------------------------
    def draw_probe_stack(self) -> int:
        state = self.state
        if not state.probe_deck:
            rebuild_probe_deck(self)
        return state.probe_deck.pop(0)

    # Papers ---------------------------------------------------------------------------------
    def usable_by(self, paper: Paper, seat: int) -> bool:
        """Fresh out of print papers can only be used by their authors."""
        return not paper.fresh or paper.author == seat


def build_input_deck(ctx: Ctx, parameter: str) -> list[str]:
    """A full Input Parameter Deck (Pieces; specification 4.1)."""
    states = ctx.world.variable(parameter).states
    size = ctx.settings.input_parameter_deck_size
    return [states[i % len(states)] for i in range(size)]


def build_probe_deck(ctx: Ctx) -> list[int]:
    """A full Probe deck, as new stack ids (Pieces)."""
    state = ctx.state
    ids = []
    for _ in range(ctx.settings.probe_deck_copies):
        for row in range(len(ctx.world.rows)):
            ids.append(len(state.stack_rows))
            state.stack_rows.append(row)
    return ids


def rebuild_probe_deck(ctx: Ctx) -> None:
    """Re-match complete stacks from the discard pile, or rebuild the full deck when fewer than
    [probe_deck_min_rebuild_stacks] are complete (specification 5.7)."""
    state = ctx.state
    n_vars = len(ctx.world.variables)
    by_stack: dict[int, list[Card]] = {}
    for card in state.probe_discard:
        by_stack.setdefault(card.stack, []).append(card)
    complete = sorted(s for s, cards in by_stack.items() if len({c.var for c in cards}) == n_vars)
    if len(complete) >= ctx.settings.probe_deck_min_rebuild_stacks:
        state.probe_deck = complete
        state.probe_discard = [c for c in state.probe_discard if c.stack not in set(complete)]
        ctx.log("deck", f"Probe deck re-matched from {len(complete)} complete discarded Probe stacks")
    else:
        state.probe_deck = build_probe_deck(ctx)
        state.probe_discard = []
        ctx.log("deck", "Probe deck rebuilt in full")
    ctx.rng.shuffle("probe_deck", state.probe_deck)


def stack_cards(ctx: Ctx, stack: int) -> dict[str, Card]:
    row = ctx.world.rows[ctx.state.stack_rows[stack]]
    values = {**row.inputs, **row.outcomes}
    return {v.id: Card(var=v.id, state=values[v.id], origin="probe", stack=stack) for v in ctx.world.variables}

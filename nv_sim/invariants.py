"""Invariants checked after every action in simulated games (specification section 13).

Each check returns a list of broken invariants (empty when all hold). They test consistency
the rules guarantee, not the rules themselves, so a broken invariant always means a bug.
"""

from collections import Counter

from nv_core.state import GameState, Phase

_LIVE_PROBE_PHASES = {Phase.PREDICTION, Phase.REVEAL, Phase.SCORING_ORDER}


def check(state: GameState, input_deck_builds: dict[str, int]) -> list[str]:
    s = state.settings
    problems: list[str] = []
    bad = problems.append

    if state.result is None:
        if state.current is None and not state.waiting:
            bad("nobody to act, but the game is not over")
        if len(set(state.waiting)) != len(state.waiting) or any(not 0 <= x < state.n_players for x in state.waiting):
            bad(f"waiting list {state.waiting} is not a set of seats")

    for r in state.researchers:
        who = f"researcher {r.seat}"
        for field in ("credit", "money", "postdocs", "students"):
            if getattr(r, field) < 0:
                bad(f"{who}: negative {field}")
        if not 0 <= r.talent_position <= s.talent_track_max:
            bad(f"{who}: talent position {r.talent_position} off the track")
        if not 1 <= r.grant_position <= len(s.grant_track):
            bad(f"{who}: grant position {r.grant_position} off the track")
        for task, count in r.staff.items():
            if count.postdocs < 0 or count.students < 0:
                bad(f"{who}: negative staff on {task.value}")
            if not 0 <= r.used.get(task, 0) <= count.total:
                bad(f"{who}: {r.used.get(task, 0)} used of {count.total} on {task.value}")
        if r.staff:
            if sum(c.postdocs for c in r.staff.values()) != r.postdocs:
                bad(f"{who}: allocated postdocs differ from postdocs")
            if sum(c.students for c in r.staff.values()) != r.students:
                bad(f"{who}: allocated students differ from students")

    for probe in state.probes:
        if probe.probe_time is not None and not 0 <= probe.probe_time < state.n_players:
            bad(f"P{probe.index + 1}: Probe time held by unknown seat {probe.probe_time}")
        if any(not 1 <= level <= 3 for level in probe.sensors.values()):
            bad(f"P{probe.index + 1}: sensor level out of range")
        if any(parameter in probe.specialty for parameter in probe.sensors):
            bad(f"P{probe.index + 1}: sensor on a Specialty Input Parameter")

    ids = Counter(p.id for p in state.published)
    if any(n > 1 for n in ids.values()):
        bad("a paper id appears twice")
    for paper in state.published:
        if paper.kind == "theory":
            limit = s.nobel_condition if state.result else s.nobel_condition - 1
            if not 0 <= paper.nobel <= limit:
                bad(f"T{paper.id}: Nobel counter {paper.nobel} out of range")
            if not 0 <= paper.retraction < s.retraction_threshold:
                bad(f"T{paper.id}: Retraction counter {paper.retraction} out of range")
        if any(not 0 <= owner < state.n_players for owner in paper.patents):
            bad(f"paper {paper.id}: patent owned by unknown seat")

    positions = [m.position for m in state.manuscripts if m.area == "review"]
    if len(set(positions)) != len(positions) or any(
        p is None or not 1 <= p <= s.submission_portal_positions for p in positions
    ):
        bad(f"Awaiting peer review positions {positions} are not distinct valid positions")
    for m in state.manuscripts:
        if m.area == "accept" and (m.tokens is None or m.tokens < 0):
            bad(f"D{m.id}: Accept area without a valid number of tokens")
        if m.area != "review" and m.position is not None:
            bad(f"D{m.id}: has a position outside the Awaiting peer review area")

    if not 0 <= state.unsuccessful_predictions <= s.crisis_condition:
        bad(f"unsuccessful predictions {state.unsuccessful_predictions} out of range")
    if state.period == "crisis" and not 1 <= state.rounds_in_crisis <= s.crisis_length:
        bad(f"rounds in crisis {state.rounds_in_crisis} out of range")

    if state.result is None:  # a game can end mid-scoring, before the Probes are put away
        problems += _input_cards(state, input_deck_builds)
    return problems


def _input_cards(state: GameState, builds: dict[str, int]) -> list[str]:
    """Every Input Parameter Deck card is somewhere: deck, discard pile, records, manuscripts, or
    (while the Probes are in play) on a Probe."""
    counts: Counter = Counter()
    for parameter, deck in state.input_decks.items():
        counts[parameter] += len(deck) + len(state.input_discards[parameter])
    cards = []
    for r in state.researchers:
        for area in (r.fresh, r.stale):
            cards += [c for o in area.observations for c in o.cards]
            cards += [item.card for item in area.cards]
    for m in state.manuscripts:
        cards += [c for record in m.records for c in record.cards]
    if state.phase in _LIVE_PROBE_PHASES:
        for probe in state.probes:
            cards += list(probe.readings.values())
            for parameter, noise in probe.unrevealed_noise.items():
                counts[parameter] += len(noise)
    for card in cards:
        if card.origin == "input_deck":
            counts[card.var] += 1
    size = state.settings.input_parameter_deck_size
    return [
        f"Input Parameter Deck {parameter}: {counts[parameter]} cards, expected {size * builds.get(parameter, 1)}"
        for parameter in state.input_decks
        if counts[parameter] != size * builds.get(parameter, 1)
    ]

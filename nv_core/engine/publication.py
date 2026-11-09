"""Publication: Submission, Supporting records, Revisions, Peer review and Article processing."""

from nv_core.actions import ExperimentRecord, ObservationRecord, ReviewVote, Revise, Submit, WithdrawSubmission
from nv_core.engine.context import Ctx, IllegalAction
from nv_core.engine.observation import mismatch
from nv_core.state import Card, Idea, Manuscript, RecordArea, Researcher, ReviewLog, SubmissionUndo, SupportRecord, Task


# Submission ----------------------------------------------------------------------------------
def start_submission(ctx: Ctx) -> None:
    state = ctx.state

    def has_work(seat: int) -> bool:
        r = state.researcher(seat)
        revisable = any(m.author == seat and m.area == "revise" for m in state.manuscripts)
        return r.allocated(Task.WRITE_UP) > 0 and (bool(r.ideas) or revisable)

    state.waiting = [seat for seat in state.turn_order() if has_work(seat)]
    for pending in state.pending:
        pending.submissions = []


def _check_actor(ctx: Ctx, seat: int) -> Researcher:
    if seat not in ctx.state.waiting:
        raise IllegalAction("you have finished submitting this round")
    r = ctx.state.researcher(seat)
    if r.remaining(Task.WRITE_UP) < 1:
        raise IllegalAction("you have no staff member left on write-up")
    return r


def free_position(ctx: Ctx) -> int | None:
    taken = {m.position for m in ctx.state.manuscripts if m.area == "review"}
    for position in range(1, ctx.settings.submission_portal_positions + 1):
        if position not in taken:
            return position
    return None


def _area(r: Researcher, name: str) -> RecordArea:
    return r.fresh if name == "fresh" else r.stale


def build_records(ctx: Ctx, r: Researcher, specs: list) -> list[SupportRecord]:
    """Check the supporting records and turn them into record stacks (cards are not removed yet)."""
    records: list[SupportRecord] = []
    used_observations: set[int] = set()
    used_cards: set[tuple[int, str]] = set()
    variables = [v.id for v in ctx.world.variables]
    for number, spec in enumerate(specs, start=1):
        if isinstance(spec, ObservationRecord):
            found = None
            for area_name in ("fresh", "stale"):
                for observation in _area(r, area_name).observations:
                    if observation.id == spec.observation:
                        found = (area_name, observation)
            if not found:
                raise IllegalAction(f"record {number}: you have no observation O{spec.observation}")
            if spec.observation in used_observations:
                raise IllegalAction(f"record {number}: O{spec.observation} is used twice")
            used_observations.add(spec.observation)
            area_name, observation = found
            records.append(
                SupportRecord(kind="observation", area=area_name, cards=list(observation.cards), observation=observation.id)
            )
            continue
        assert isinstance(spec, ExperimentRecord)
        if sorted(var for _, var in spec.cards) != sorted(variables):
            raise IllegalAction(f"record {number}: an experiment record has exactly one card per row")
        areas = set()
        cards: list[Card] = []
        for experiment, var in spec.cards:
            if (experiment, var) in used_cards:
                raise IllegalAction(f"record {number}: card E{experiment}:{var} is used twice")
            used_cards.add((experiment, var))
            match = None
            for area_name in ("fresh", "stale"):
                for item in _area(r, area_name).cards:
                    if item.experiment == experiment and item.card.var == var:
                        match = (area_name, item.card)
            if not match:
                raise IllegalAction(f"record {number}: you have no card E{experiment}:{var}")
            areas.add(match[0])
            cards.append(match[1])
        if len(areas) > 1:
            raise IllegalAction(f"record {number}: all cards of a record stack come from one record area")
        order = {v: i for i, v in enumerate(variables)}
        cards.sort(key=lambda c: order[c.var])
        experiments = sorted({e for e, _ in spec.cards})
        records.append(
            SupportRecord(
                kind="experiment",
                area=areas.pop(),
                cards=cards,
                experiments=experiments,
                fabricated=len(experiments) > 1,
            )
        )
    return records


def _remove_records(r: Researcher, specs: list) -> dict[str, RecordArea]:
    """Take the records' cards out of the record areas; return what was taken, by area."""
    taken = {"fresh": RecordArea(), "stale": RecordArea()}
    for spec in specs:
        for name in ("fresh", "stale"):
            area = _area(r, name)
            if isinstance(spec, ObservationRecord):
                taken[name].observations += [o for o in area.observations if o.id == spec.observation]
                area.observations = [o for o in area.observations if o.id != spec.observation]
            else:
                cards = set(spec.cards)
                taken[name].cards += [c for c in area.cards if (c.experiment, c.card.var) in cards]
                area.cards = [c for c in area.cards if (c.experiment, c.card.var) not in cards]
    return taken


def _return_records(ctx: Ctx, r: Researcher, taken: dict[str, RecordArea]) -> None:
    order = {v.id: i for i, v in enumerate(ctx.world.variables)}
    for name, records in taken.items():
        area = _area(r, name)
        area.observations = sorted(area.observations + records.observations, key=lambda o: o.id)
        area.cards = sorted(area.cards + records.cards, key=lambda c: (c.experiment, order[c.card.var]))


def _elements(idea: Idea) -> int:
    return len(idea.inputs) + len(idea.outcomes)


def check_submission(ctx: Ctx, r: Researcher, idea: Idea, tier_number: int, records: list[SupportRecord], pay_apc: bool) -> int:
    """Raise if the submission breaks a rule; return its cost."""
    tiers = ctx.settings.journal_tiers
    if not 0 <= tier_number < len(tiers):
        raise IllegalAction(f"there is no journal tier {tier_number}")
    tier = tiers[tier_number]
    if idea.kind == "method" and not tier.methods_accepted:
        raise IllegalAction(f"tier {tier_number} does not accept methods")
    if idea.kind == "theory":
        if _elements(idea) < tier.min_elements:
            raise IllegalAction(f"tier {tier_number} needs at least {tier.min_elements} elements in the theory")
        values = {**idea.inputs, **idea.outcomes}
        for number, record in enumerate(records, start=1):
            if mismatch(values, {c.var: c for c in record.cards}):
                raise IllegalAction(f"record {number} mismatches the theory")
    observations = sum(1 for rec in records if rec.kind == "observation")
    experiments = len(records) - observations
    if len(records) < tier.min_records:
        raise IllegalAction(f"tier {tier_number} needs at least {tier.min_records} supporting record(s)")
    if observations < tier.min_observations:
        raise IllegalAction(f"tier {tier_number} needs at least {tier.min_observations} observation record(s)")
    if experiments < tier.min_experiments:
        raise IllegalAction(f"tier {tier_number} needs at least {tier.min_experiments} experiment record(s)")
    # Supporting observational and experimental records: none in a journal without peer review.
    if not tier.peer_review and len(records) > max(tier.min_records, tier.min_observations + tier.min_experiments):
        raise IllegalAction(f"tier {tier_number} has no peer review, so it takes no records beyond its minimum")
    cost = tier.submission_fee + (tier.apc if pay_apc else 0)
    if cost > ctx.spendable(r):
        if cost <= r.money:
            raise IllegalAction("at 0 academic credit you cannot spend money you need to pay your postdocs")
        raise IllegalAction(f"this submission costs {cost}, you have {r.money} money")
    if tier.peer_review and free_position(ctx) is None:
        raise IllegalAction("every Awaiting peer review position is occupied")
    return cost


def submit(ctx: Ctx, action: Submit) -> None:
    state, seat = ctx.state, action.seat
    r = _check_actor(ctx, seat)
    idea = next((i for i in r.ideas if i.id == action.manuscript), None)
    if idea is None:
        raise IllegalAction(f"you have no development stack D{action.manuscript}")
    records = build_records(ctx, r, action.records)
    cost = check_submission(ctx, r, idea, action.tier, records, action.pay_apc)
    tier = ctx.settings.journal_tiers[action.tier]
    index = r.ideas.index(idea)
    r.money -= cost
    r.ideas.remove(idea)
    taken = _remove_records(r, action.records)
    state.pending[seat].submissions.append(SubmissionUndo(manuscript=idea.id, cost=cost, index=index, taken=taken))
    r.used[Task.WRITE_UP] = r.used.get(Task.WRITE_UP, 0) + 1
    manuscript = Manuscript(
        idea=idea,
        author=seat,
        tier=action.tier,
        open_access=action.pay_apc,
        records=records,
        round_submitted=state.round,
        area="review" if tier.peer_review else "accept",
    )
    state.manuscripts.append(manuscript)
    where = ""
    if tier.peer_review:
        manuscript.position = free_position(ctx)
        where = f" (Awaiting peer review position {manuscript.position})"
    content = f": {describe(idea)}" if action.pay_apc else ""
    ctx.log(
        "submission",
        f"{ctx.name(seat)} submits D{idea.id} to tier {action.tier} with {len(records)} record(s)"
        f"{' open access' if action.pay_apc else ''}{where}{content}",
        seat=seat,
        manuscript=idea.id,
    )
    if not tier.peer_review:
        to_accept(ctx, manuscript)


def revise(ctx: Ctx, action: Revise) -> None:
    r = _check_actor(ctx, action.seat)
    try:
        manuscript = ctx.state.manuscript(action.manuscript)
    except KeyError:
        raise IllegalAction(f"there is no manuscript D{action.manuscript}") from None
    if manuscript.author != action.seat or manuscript.area != "revise":
        raise IllegalAction(f"D{action.manuscript} is not one of your manuscripts in the Revise area")
    ctx.state.pending[action.seat].submissions.append(
        SubmissionUndo(manuscript=manuscript.id, before=manuscript.model_copy(deep=True))
    )
    r.used[Task.WRITE_UP] = r.used.get(Task.WRITE_UP, 0) + 1
    ctx.log("revision", f"{ctx.name(action.seat)} revises D{manuscript.id}", seat=action.seat)
    to_accept(ctx, manuscript)


def withdraw_submission(ctx: Ctx, action: WithdrawSubmission) -> None:
    """Undo a submission (fee and APC refunded, development stack and records returned, Portal
    position freed) or a revision (back to the Revise area); the write-up staff member is free again."""
    state, seat = ctx.state, action.seat
    pending = state.pending[seat]
    undo = next((u for u in pending.submissions if u.manuscript == action.manuscript), None)
    if undo is None:
        raise IllegalAction(f"D{action.manuscript} is not a submission or revision you made in this step")
    r = state.researcher(seat)
    index = next(i for i, m in enumerate(state.manuscripts) if m.id == action.manuscript)
    if undo.before is not None:
        state.manuscripts[index] = undo.before
        what = "revision"
    else:
        manuscript = state.manuscripts.pop(index)
        r.money += undo.cost
        r.ideas.insert(undo.index, manuscript.idea)
        _return_records(ctx, r, undo.taken)
        what = "submission"
    pending.submissions.remove(undo)
    r.used[Task.WRITE_UP] -= 1
    ctx.log("withdrawal", f"{ctx.name(seat)} withdraws the {what} of D{action.manuscript}", seat=seat)


def supporting_records(ctx: Ctx, r: Researcher, idea: Idea) -> tuple[list[ObservationRecord], list[ExperimentRecord]]:
    """Every observation record, and as many disjoint experiment records as can be built, that
    do not mismatch ``idea``. Experiment records keep the cards of one experiment together where
    possible, so cards are only mixed (fabricated) when nothing else fits."""
    values = {**idea.inputs, **idea.outcomes} if idea.kind == "theory" else {}
    observations = [
        ObservationRecord(observation=o.id)
        for area in (r.fresh, r.stale)
        for o in area.observations
        if not mismatch(values, {c.var: c for c in o.cards})
    ]
    experiments: list[ExperimentRecord] = []
    variables = [v.id for v in ctx.world.variables]
    for area in (r.fresh, r.stale):
        fitting = {
            var: [c for c in area.cards if c.card.var == var and (var not in values or c.card.state == values[var])]
            for var in variables
        }
        whole = sorted(
            e
            for e in {c.experiment for c in area.cards}
            if all(any(c.experiment == e for c in fitting[var]) for var in variables)
        )
        for e in whole:
            experiments.append(ExperimentRecord(cards=[(e, var) for var in variables]))
            for var in variables:
                fitting[var] = [c for c in fitting[var] if c.experiment != e]
        while all(fitting[var] for var in variables):
            experiments.append(ExperimentRecord(cards=[(fitting[var].pop(0).experiment, var) for var in variables]))
    return observations, experiments


def possible_submissions(ctx: Ctx, seat: int) -> list[tuple[Submit, list]]:
    """Every (manuscript, tier) that ``seat`` can submit now, highest tier first. Each comes as a
    legal submission with the minimum records (no APC), plus the spare records that would also fit."""
    r = ctx.state.researcher(seat)
    found = []
    for tier_number in range(len(ctx.settings.journal_tiers) - 1, -1, -1):
        tier = ctx.settings.journal_tiers[tier_number]
        for idea in r.ideas:
            observations, experiments = supporting_records(ctx, r, idea)
            if len(observations) < tier.min_observations or len(experiments) < tier.min_experiments:
                continue
            records: list = observations[: tier.min_observations] + experiments[: tier.min_experiments]
            rest = observations[tier.min_observations :] + experiments[tier.min_experiments :]
            needed = max(0, tier.min_records - len(records))
            records += rest[:needed]
            try:
                check_submission(ctx, r, idea, tier_number, build_records(ctx, r, records), False)
            except IllegalAction:
                continue
            spare = rest[needed:] if tier.peer_review else []
            found.append((Submit(seat=seat, manuscript=idea.id, tier=tier_number, records=records), spare))
    return found


def find_submission(ctx: Ctx, seat: int) -> Submit | None:
    """A legal submission for ``seat`` (highest tier first, no APC), or None."""
    found = possible_submissions(ctx, seat)
    return found[0][0] if found else None


def check_commit_submission(ctx: Ctx, seat: int) -> None:
    r = ctx.state.researcher(seat)
    if r.credit != 0 or r.remaining(Task.WRITE_UP) < 1:
        return
    message = "at 0 academic credit you must use every staff member that can still be used"
    revisable = [m.id for m in ctx.state.manuscripts if m.author == seat and m.area == "revise"]
    if revisable:
        raise IllegalAction(f"{message}: you can still revise D{revisable[0]}")
    possible = find_submission(ctx, seat)
    if possible:
        raise IllegalAction(f"{message}: you can still submit D{possible.manuscript} to tier {possible.tier}")


# Article processing --------------------------------------------------------------------------
def processing_time(ctx: Ctx, tier_number: int, idea: Idea, records: int, open_access: bool) -> dict[str, int]:
    """Rounds in processing, if accepted now, with each bonus that went into it (Article processing)."""
    tier = ctx.settings.journal_tiers[tier_number]
    base = tier.rounds_in_processing
    extra_records = extra_elements = hot_topic = 0
    if idea.kind == "theory":
        extra_records = max(0, records - tier.min_records)
        extra_elements = max(0, _elements(idea) - tier.min_elements)
        hot = ctx.state.probes[ctx.state.hot_topic].readings
        matches = any(var in hot and hot[var].state == value for var, value in idea.inputs.items())
        if matches and not mismatch(idea.inputs, hot):  # hot topic publication
            hot_topic = 1
    reduction = (1 if open_access else 0) + extra_records + extra_elements + hot_topic
    value = max(min(base, 1), base - reduction)
    crisis = 0
    if ctx.state.period == "crisis":  # Crisis fast-track
        crisis = min(1, value)
        value -= crisis
    return {"rounds": value, "base": base, "extra_records": extra_records, "extra_elements": extra_elements,
            "hot_topic": hot_topic, "crisis": crisis}


def rounds_in_processing(ctx: Ctx, manuscript: Manuscript) -> int:
    return processing_time(ctx, manuscript.tier, manuscript.idea, len(manuscript.records), manuscript.open_access)["rounds"]


def to_accept(ctx: Ctx, manuscript: Manuscript) -> None:
    manuscript.area = "accept"
    manuscript.position = None
    manuscript.votes = []
    manuscript.tokens = rounds_in_processing(ctx, manuscript)
    ctx.log(
        "accept_area",
        f"D{manuscript.id} enters the Accept area with {manuscript.tokens} Rounds in processing token(s)",
        manuscript=manuscript.id,
    )


def describe(idea: Idea) -> str:
    if idea.kind == "method":
        return f"method for {idea.parameter}"
    inputs = ", ".join(f"{k}={v}" for k, v in idea.inputs.items())
    outcomes = ", ".join(f"{k}={v}" for k, v in idea.outcomes.items())
    return f"theory {inputs} -> {outcomes}"


# Peer review --------------------------------------------------------------------------------
def start_peer_review(ctx: Ctx) -> None:
    state, s = ctx.state, ctx.settings
    for pending in state.pending:
        pending.submissions = []  # submissions can no longer be withdrawn
    occupied = sorted(m.position for m in state.manuscripts if m.area == "review")
    reviewers = {seat: state.researcher(seat).allocated(Task.PEER_REVIEW) for seat in state.turn_order()}
    deck = [p for p in occupied for _ in range(s.min_reviews_for_decision)] + [0] * sum(reviewers.values())
    ctx.rng.shuffle("peer_review", deck)
    state.review_cards = {}
    for seat, n in reviewers.items():
        state.review_cards[seat], deck = deck[:n], deck[n:]
        r = state.researcher(seat)
        if n:
            r.used[Task.PEER_REVIEW] = n  # always used, whatever the cards
            ctx.log("review_cards", f"{ctx.name(seat)} gets peer review card(s) {state.review_cards[seat]}", seat=seat)
        state.pending[seat].votes = {}
    state.review_rest = deck
    state.waiting = [seat for seat in state.turn_order() if any(state.review_cards.get(seat, []))]


def review_vote(ctx: Ctx, action: ReviewVote) -> None:
    cards = ctx.state.review_cards.get(action.seat, [])
    if not 0 <= action.card < len(cards) or cards[action.card] == 0:
        raise IllegalAction("choose one of your peer review cards that shows a position")
    ctx.state.pending[action.seat].votes[action.card] = action.vote


def check_commit_review(ctx: Ctx, seat: int) -> None:
    cards = ctx.state.review_cards.get(seat, [])
    missing = [i for i, c in enumerate(cards) if c and i not in ctx.state.pending[seat].votes]
    if missing:
        raise IllegalAction(f"vote on every manuscript you were allocated (card(s) {[i + 1 for i in missing]})")


def finish_peer_review(ctx: Ctx) -> None:
    state, s = ctx.state, ctx.settings
    by_position = {m.position: m for m in state.manuscripts if m.area == "review"}
    for seat in state.turn_order():
        cards = state.review_cards.get(seat, [])
        for index, vote in sorted(state.pending[seat].votes.items()):
            by_position[cards[index]].votes.append(vote)
        state.pending[seat].votes = {}
    draws, state.review_rest = state.review_rest[: s.peer_review_random_draws], []
    ctx.log("review_draws", f"Random peer review draws: {draws}")
    for position in draws:
        if position:
            by_position[position].votes.append("accept")
    for position in sorted(by_position):
        manuscript = by_position[position]
        votes = manuscript.votes
        if len(votes) < s.min_reviews_for_decision:
            continue
        accepts, revises = votes.count("accept"), votes.count("revise")
        decision = "Revise area" if revises > len(votes) / 2 else "Accept area"
        state.review_log.append(ReviewLog(
            manuscript=manuscript.id, author=manuscript.author, tier=manuscript.tier, round=state.round,
            accepts=accepts, revises=revises, accepted=decision == "Accept area",
            fabricated=sum(r.fabricated for r in manuscript.records),
        ))
        ctx.log("review_decision", f"D{manuscript.id} (position {position}): {accepts} accept, {revises} revise -> {decision}")
        if decision == "Revise area":
            manuscript.area = "revise"
            manuscript.position = None
            manuscript.votes = []
        else:
            to_accept(ctx, manuscript)
    state.review_cards = {}

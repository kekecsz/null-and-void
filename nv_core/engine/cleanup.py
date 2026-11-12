"""Talent development phase and Clean-up phase (with Publication, Publication scoring,
Research grants and Patents, which happen during Clean-up)."""

from nv_core.engine.context import Ctx
from nv_core.engine.ending import credit_victory, end_game
from nv_core.engine.publication import describe
from nv_core.state import Paper, PaperLog, RoundLog, Task


def talent_development(ctx: Ctx) -> None:
    state, s = ctx.state, ctx.settings
    for seat in state.turn_order():
        r = state.researcher(seat)
        staff = r.allocated(Task.TALENT_DEVELOPMENT)
        if not staff:
            continue
        r.used[Task.TALENT_DEVELOPMENT] = staff  # always used, even at the maximum
        if r.talent_position < s.talent_track_max:
            r.talent_position += 1
            ctx.log("talent", f"{ctx.name(seat)} advances to {r.talent_position} on the Talent development track")


def cleanup(ctx: Ctx) -> None:
    state, s = ctx.state, ctx.settings
    order = state.turn_order()

    # Pay the postdocs; the unpaid ones leave after the grant check and the unused-staff penalty.
    for seat in order:
        r = state.researcher(seat)
        paid = r.postdocs if s.cost_of_postdoc == 0 else min(r.postdocs, r.money // s.cost_of_postdoc)
        r.money -= paid * s.cost_of_postdoc
        r.unpaid = r.postdocs - paid
        if r.unpaid:
            ctx.log("unpaid", f"{ctx.name(seat)} cannot pay {r.unpaid} postdoc(s)", seat=seat)

    state.hot_topic = (state.hot_topic + 1) % len(state.probes)
    for probe in state.probes:
        probe.probe_time = None
        probe.probe_time_from_sensor = False
    for paper in state.published:
        paper.fresh = False

    # Publication
    ready = [m for m in state.manuscripts if m.area == "accept" and m.tokens == 0]
    ready.sort(key=lambda m: (order.index(m.author), m.id))
    for manuscript in ready:
        state.manuscripts.remove(manuscript)
        for record in manuscript.records:
            for card in record.cards:
                ctx.discard_card(card)
        paper = Paper(
            id=state.new_id(),
            idea=manuscript.idea,
            author=manuscript.author,
            tier=manuscript.tier,
            open_access=manuscript.open_access,
            round=state.round,
        )
        state.published.append(paper)
        state.paper_log.append(PaperLog(
            paper=paper.id, manuscript=manuscript.id, idea=paper.idea, author=paper.author, tier=paper.tier,
            open_access=paper.open_access, round=state.round, records=len(manuscript.records),
            fabricated=sum(r.fabricated for r in manuscript.records),
            reviewed=s.journal_tiers[paper.tier].peer_review,
        ))
        letter = "T" if paper.kind == "theory" else "M"
        ctx.log(
            "published",
            f"{ctx.name(paper.author)} publishes D{manuscript.id} as {letter}{paper.id} in tier {paper.tier}: "
            f"{describe(paper.idea)}",
            paper=paper.id,
        )
        state.researcher(paper.author).publications_this_round += 1
        reward = paper.tier + (s.OA_publication_AC_reward if paper.open_access else 0)
        ctx.credit(paper.author, reward, f"{letter}{paper.id} published")
    for manuscript in state.manuscripts:
        if manuscript.area == "accept" and manuscript.tokens:
            manuscript.tokens -= 1

    # Research grants
    for seat in order:
        r = state.researcher(seat)
        position = s.grant_track[r.grant_position - 1]
        grants_staff = r.allocated(Task.GRANTS)
        r.used[Task.GRANTS] = min(grants_staff, position.admin)  # specification 5.7
        maintained = grants_staff >= position.admin and r.publications_this_round >= position.expected_to_maintain
        before = r.grant_position
        if not maintained:
            r.grant_position = max(1, r.grant_position - 1)
        elif position.expected_to_increase is not None and r.publications_this_round >= position.expected_to_increase:
            r.grant_position += 1
        if r.grant_position != before:
            ctx.log("grant", f"{ctx.name(seat)} moves to position {r.grant_position} on the Grant funding track")

    # Unused staff, the staff who leave, unspent money, returning staff
    for seat in order:
        r = state.researcher(seat)
        unused = sum(r.remaining(task) for task in r.staff)
        if unused:
            ctx.credit(seat, s.unused_staff_penalty * unused, f"{unused} unused staff member(s)")
        if r.unpaid:
            r.postdocs -= r.unpaid
            ctx.credit(seat, s.unpaid_postdoc_penalty * r.unpaid, "unpaid postdocs")
            if r.talent_position > 0:
                r.talent_position -= 1
                ctx.log("talent", f"{ctx.name(seat)} moves back to {r.talent_position} on the Talent development track")
            r.unpaid = 0
        r.students = 0
        r.lab_expanded = False
        r.money = 0  # unspent money returned to the bank
        r.staff = {}
        r.used = {}

    # Funding
    for seat in order:
        r = state.researcher(seat)
        patents = sum(p.patents.count(seat) for p in state.published)
        r.money = s.grant_track[r.grant_position - 1].funding + patents * s.patent_funding

    state.round_log.append(RoundLog(
        round=state.round, credit=[r.credit for r in state.researchers],
        nobel={p.id: p.nobel for p in state.published if p.kind == "theory"},
    ))

    if state.period == "crisis":
        if state.rounds_in_crisis >= s.crisis_length:
            end_game(ctx, "credit", credit_victory(ctx))
            return
        state.rounds_in_crisis += 1

    for r in state.researchers:
        ctx.discard_area(r.stale)
        r.stale, r.fresh = r.fresh, r.stale  # the emptied stale area becomes the new fresh area
    state.first_player = (state.first_player + 1) % state.n_players

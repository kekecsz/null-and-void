"""Rulebook "Publication": "Submission", "Supporting observational and experimental records",
"Revisions", "Peer review", "Article processing"; "Academic credit rules" (spending at 0 credit);
specification 5.2 (submission is open, first come first served) and 5.7 (records, methods,
Hot topic, peer review).

Most tests use a small hand-made journal tier table (TIERS) so that each boundary can be worked
out by hand; the peer review tests use docs/parameter_defaults.yaml.
"""

import pytest

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply, validate
from nv_core.engine.context import Ctx
from nv_core.engine.observation import deal_probes
from nv_core.engine.publication import rounds_in_processing
from nv_core.state import Card, ExperimentCard, Idea, Manuscript, Observation, Phase, SupportRecord, Task
from tests.core.engine_helpers import do, game, set_readings, settings, to_phase

S = settings()

# Hand-made tiers. Tier 0: no review, fee 1. Tier 1: 1 record, 3 elements, 2 rounds, APC 1.
# Tier 2: 2 records incl. at least 1 observation and 1 experiment, no methods, 3 rounds.
_TIER = dict(min_records=0, min_observations=0, min_experiments=0, min_elements=2, rounds_in_processing=0,
             peer_review=False, methods_accepted=True, submission_fee=1, apc=0)
TIERS = [
    _TIER,
    _TIER | dict(min_records=1, min_elements=3, rounds_in_processing=2, peer_review=True, submission_fee=0, apc=1),
    _TIER | dict(min_records=2, min_observations=1, min_experiments=1, rounds_in_processing=3, peer_review=True,
                 methods_accepted=False, submission_fee=0, apc=2),
]
VARS = ("IP1", "IP2", "IP3", "WO1")


def _card(var, value):
    return Card(var=var, state=value, origin="supply")


def _experiment(exp_id, values):
    return [ExperimentCard(experiment=exp_id, card=_card(v, s)) for v, s in zip(VARS, values)]


def _observation(obs_id, values):
    return Observation(id=obs_id, probe=0, round=1, cards=[_card(v, s) for v, s in zip(VARS, values)])


def _exp_record(exp_id):
    return a.ExperimentRecord(cards=[(exp_id, v) for v in VARS])


def _obs_record(obs_id):
    return a.ObservationRecord(observation=obs_id)


def _manuscript(idea_id, author, area, position=None, tier=1, inputs=None, records=0, open_access=False, kind="theory"):
    idea = Idea(
        id=idea_id, kind=kind,
        inputs={} if kind == "method" else (inputs or {"IP1": "a", "IP2": "x"}),
        outcomes={} if kind == "method" else {"WO1": "up"},
        parameter="IP2" if kind == "method" else None,
    )
    return Manuscript(
        idea=idea, author=author, tier=tier, open_access=open_access,
        records=[SupportRecord(kind="observation", area="fresh", cards=[]) for _ in range(records)],
        round_submitted=1, area=area, position=position, votes=[], tokens=None,
    )


def _submission(write_up=3, other_write_up=1, positions=None, manuscripts=()):
    """Reach the Submission step with researcher 0 holding:
    ideas   901 theory IP1=a, IP2=x -> WO1=up (3 elements); 903 theory IP1=a -> WO1=up (2 elements);
            902 method for IP2
    fresh   experiments 801 (a x p up), 802 (a x q up), 804 (b y q down), 805 (a x p down);
            observation 701 (a x blank up)
    stale   experiment 803 (a x p up); observation 702 (a x q up)
    Researcher 1 holds theory 911 IP1=b, IP2=y -> WO1=down with fresh experiment 811 (b y q down).
    """
    overrides = {"journal_tiers": TIERS}
    if positions:
        overrides["submission_portal_positions"] = positions
    state = game(**overrides)
    state = to_phase(state, Phase.DEVELOPMENT, {0: {"development": 1, "write_up": write_up}, 1: {"development": 1, "write_up": other_write_up}})
    r = state.researcher(0)
    r.money = 10
    r.ideas = [
        Idea(id=901, kind="theory", inputs={"IP1": "a", "IP2": "x"}, outcomes={"WO1": "up"}),
        Idea(id=903, kind="theory", inputs={"IP1": "a"}, outcomes={"WO1": "up"}),
        Idea(id=902, kind="method", parameter="IP2"),
    ]
    r.fresh.cards = (
        _experiment(801, ("a", "x", "p", "up"))
        + _experiment(802, ("a", "x", "q", "up"))
        + _experiment(804, ("b", "y", "q", "down"))
        + _experiment(805, ("a", "x", "p", "down"))
    )
    r.fresh.observations = [_observation(701, ("a", "x", None, "up"))]
    r.stale.cards = _experiment(803, ("a", "x", "p", "up"))
    r.stale.observations = [_observation(702, ("a", "x", "q", "up"))]
    other = state.researcher(1)
    other.money = 10
    other.ideas = [Idea(id=911, kind="theory", inputs={"IP1": "b", "IP2": "y"}, outcomes={"WO1": "down"})]
    other.fresh.cards = _experiment(811, ("b", "y", "q", "down"))
    other.fresh.observations = []
    state.manuscripts.extend(manuscripts)
    state = do(state, a.CommitPhase(seat=0), a.CommitPhase(seat=1))
    assert state.phase == Phase.SUBMISSION
    return state


def _refused(state, action):
    with pytest.raises(IllegalAction):
        apply(state, action)


# Submission -------------------------------------------------------------------------------
def test_theory_needs_the_tier_minimum_of_elements_exactly():
    """Submission: each tier sets the minimum number of elements in the theory (tier 1 here: 3)."""
    state = _submission()
    _refused(state, a.Submit(seat=0, manuscript=903, tier=1, records=[_exp_record(801)]))
    assert validate(state, a.Submit(seat=0, manuscript=901, tier=1, records=[_exp_record(801)])) is None


def test_separate_minimums_of_observations_and_experiments():
    """Submission: separate minimums for each kind of record (tier 2 here: 1 observation, 1 experiment)."""
    state = _submission()
    _refused(state, a.Submit(seat=0, manuscript=901, tier=2, records=[_exp_record(801), _exp_record(802)]))
    _refused(state, a.Submit(seat=0, manuscript=901, tier=2, records=[_obs_record(701), _obs_record(702)]))
    assert validate(state, a.Submit(seat=0, manuscript=901, tier=2, records=[_obs_record(701), _exp_record(801)])) is None


def test_methods_meet_record_minimums_but_not_element_minimums():
    """Supporting records for methods (specification 5.7): a method manuscript meets the record
    minimums with any records; min_elements does not apply. Methods only where accepted."""
    state = _submission()
    _refused(state, a.Submit(seat=0, manuscript=902, tier=1, records=[]))
    # A record that would mismatch a theory is fine for a method.
    assert validate(state, a.Submit(seat=0, manuscript=902, tier=1, records=[_exp_record(804)])) is None
    _refused(state, a.Submit(seat=0, manuscript=902, tier=2, records=[_obs_record(701), _exp_record(801)]))


def test_each_submission_uses_one_write_up_staff_member():
    """Submission: one submission or revision per staff member allocated to Write-up."""
    state = _submission(write_up=1)
    state = do(state, a.Submit(seat=0, manuscript=901, tier=1, records=[_exp_record(801)]))
    _refused(state, a.Submit(seat=0, manuscript=903, tier=0, records=[]))


def test_full_portal_refuses_peer_review_tiers_but_not_tier_0():
    """Submission: with every numbered position occupied, no submissions to journals with peer
    review; journals without peer review still accept."""
    occupant = _manuscript(990, author=1, area="review", position=1, inputs={"IP1": "b", "IP2": "y"})
    state = _submission(positions=1, manuscripts=[occupant])
    _refused(state, a.Submit(seat=0, manuscript=901, tier=1, records=[_exp_record(801)]))
    state = do(state, a.Submit(seat=0, manuscript=903, tier=0, records=[]))
    assert state.manuscript(903).area == "accept"


def test_journals_without_peer_review_take_no_records_beyond_their_minimum():
    """docs/open_questions.md (pending rulebook change): spare records cannot help a submission to
    a journal without peer review, so they are refused there, and not offered."""
    from nv_core.engine import legal_actions

    state = _submission()
    _refused(state, a.Submit(seat=0, manuscript=903, tier=0, records=[_exp_record(801)]))
    assert validate(state, a.Submit(seat=0, manuscript=903, tier=0, records=[])) is None
    assert validate(state, a.Submit(seat=0, manuscript=901, tier=1, records=[_exp_record(801), _exp_record(802)])) is None
    submit = next(o for o in legal_actions(state, 0) if o.type == "submit")
    assert all(not spare for key, spare in submit.template["spare_records"].items() if key.endswith("/0"))
    assert any(spare for key, spare in submit.template["spare_records"].items() if key.endswith("/1"))


def test_submission_takes_the_first_open_position():
    """Submission: the manuscript goes to the first open numbered position."""
    taken = [
        _manuscript(991, author=1, area="review", position=1, inputs={"IP1": "b"}),
        _manuscript(992, author=1, area="review", position=3, inputs={"IP2": "y"}),
    ]
    state = _submission(positions=3, manuscripts=taken)
    state = do(state, a.Submit(seat=0, manuscript=901, tier=1, records=[_exp_record(801)]))
    assert state.manuscript(901).position == 2


def test_first_to_submit_gets_the_last_free_position():
    """Specification 5.2: submissions are applied the moment they arrive, so the first to submit
    gets the free Submission Portal position."""
    state = _submission(positions=1)
    state = do(state, a.Submit(seat=1, manuscript=911, tier=1, records=[_exp_record(811)]))
    assert state.manuscript(911).position == 1 and state.phase == Phase.SUBMISSION
    _refused(state, a.Submit(seat=0, manuscript=901, tier=1, records=[_exp_record(801)]))


def test_apc_is_paid_and_makes_the_manuscript_open_access():
    """Article processing: paying the APC costs [apc] (plus the [submission_fee]) and the manuscript is open."""
    state = _submission()
    money = state.researcher(0).money
    state = do(state, a.Submit(seat=0, manuscript=901, tier=1, records=[_exp_record(801)], pay_apc=True))
    assert state.manuscript(901).open_access
    assert state.researcher(0).money == money - TIERS[1]["submission_fee"] - TIERS[1]["apc"]


@pytest.mark.parametrize("spare, allowed", [(0, True), (-1, False)])
def test_at_zero_credit_apc_only_if_postdocs_can_still_be_paid(spare, allowed):
    """Academic credit rules: at 0 credit a researcher cannot spend money they need to pay their postdocs."""
    state = _submission()
    r = state.researcher(0)
    r.credit = 0
    r.money = r.postdocs * S.cost_of_postdoc + TIERS[1]["apc"] + spare
    action = a.Submit(seat=0, manuscript=901, tier=1, records=[_exp_record(801)], pay_apc=True)
    assert (validate(state, action) is None) is allowed


def test_at_zero_credit_submission_fee_only_if_postdocs_can_still_be_paid():
    """Academic credit rules: the same limit applies to the [submission_fee]."""
    state = _submission()
    r = state.researcher(0)
    r.credit = 0
    r.money = r.postdocs * S.cost_of_postdoc + TIERS[0]["submission_fee"] - 1
    _refused(state, a.Submit(seat=0, manuscript=903, tier=0, records=[]))
    r.money += 1
    assert validate(state, a.Submit(seat=0, manuscript=903, tier=0, records=[])) is None


# Supporting observational and experimental records ----------------------------------------
def test_a_card_can_support_only_once():
    """Supporting records: each card can be used only once."""
    state = _submission()
    _refused(state, a.Submit(seat=0, manuscript=901, tier=1, records=[_exp_record(801), _exp_record(801)]))


def test_record_stack_has_one_card_per_row():
    """Supporting records (specification 5.7): exactly one card per input parameter and world outcome."""
    state = _submission()
    missing = a.ExperimentRecord(cards=[(801, "IP1"), (801, "IP2"), (801, "IP3")])
    doubled = a.ExperimentRecord(cards=[(801, "IP1"), (802, "IP1"), (801, "IP2"), (801, "IP3"), (801, "WO1")])
    _refused(state, a.Submit(seat=0, manuscript=901, tier=1, records=[missing]))
    _refused(state, a.Submit(seat=0, manuscript=901, tier=1, records=[doubled]))


def test_record_stack_comes_from_one_record_area():
    """Supporting records: all cards of one stack come from the same record area; different stacks
    may come from different areas."""
    state = _submission()
    mixed = a.ExperimentRecord(cards=[(801, "IP1"), (801, "IP2"), (803, "IP3"), (801, "WO1")])
    _refused(state, a.Submit(seat=0, manuscript=901, tier=1, records=[mixed]))
    state = do(state, a.Submit(seat=0, manuscript=901, tier=1, records=[_exp_record(803), _exp_record(801)]))
    r = state.researcher(0)
    assert not any(c.experiment == 803 for c in r.stale.cards)
    assert not any(c.experiment == 801 for c in r.fresh.cards)


def test_a_mismatching_world_outcome_is_refused():
    """Supporting records: no mismatching elements, world outcomes included."""
    state = _submission()
    _refused(state, a.Submit(seat=0, manuscript=901, tier=1, records=[_exp_record(805)]))


# Revisions ----------------------------------------------------------------------------------
def test_revision_moves_own_revise_area_manuscript_to_accept_with_tokens():
    """Revisions: a Write-up staff member advances one of the researcher's own manuscripts from the
    Revise area to the Accept area, with rounds in processing tokens."""
    pending = [
        _manuscript(960, author=0, area="revise", records=1),
        _manuscript(961, author=0, area="revise", records=1, inputs={"IP1": "a", "IP3": "p"}),
        _manuscript(962, author=1, area="revise", records=1, inputs={"IP1": "b", "IP2": "y"}),
        _manuscript(963, author=0, area="review", position=1, records=1, inputs={"IP2": "x", "IP3": "p"}),
    ]
    state = _submission(write_up=1, manuscripts=pending)
    _refused(state, a.Revise(seat=0, manuscript=962))  # someone else's
    _refused(state, a.Revise(seat=0, manuscript=963))  # not in the Revise area
    state = do(state, a.Revise(seat=0, manuscript=960))
    m = state.manuscript(960)
    assert m.area == "accept" and m.tokens == rounds_in_processing(Ctx(state), m)
    _refused(state, a.Revise(seat=0, manuscript=961))  # the only Write-up staff member is used


# Withdrawing (specification 5.2) -------------------------------------------------------------
def test_withdrawing_a_submission_undoes_it_completely():
    """Specification 5.2: before committing, a submission can be withdrawn: fee and APC refunded,
    the development stack and records back in their areas, the staff member free again."""
    state = _submission(write_up=1)
    before = state.researcher(0).model_copy(deep=True)
    records = [_exp_record(803), _obs_record(701)]
    state = do(state, a.Submit(seat=0, manuscript=901, tier=1, records=records, pay_apc=True))
    assert state.researcher(0).money < before.money
    state = do(state, a.WithdrawSubmission(seat=0, manuscript=901))
    r = state.researcher(0)
    assert not any(m.id == 901 for m in state.manuscripts)
    assert r.money == before.money and r.ideas == before.ideas
    assert r.fresh == before.fresh and r.stale == before.stale
    assert r.remaining(Task.WRITE_UP) == 1
    state = do(state, a.Submit(seat=0, manuscript=903, tier=0, records=[]))  # the staff member can be used again
    assert state.manuscript(903).area == "accept"


def test_withdrawing_frees_the_portal_position_for_the_next_submission():
    """Specification 5.2: a freed position goes to the next submission; others keep theirs."""
    state = _submission(positions=2)
    state = do(state, a.Submit(seat=0, manuscript=901, tier=1, records=[_exp_record(801)]))
    state = do(state, a.Submit(seat=1, manuscript=911, tier=1, records=[_exp_record(811)]))
    state = do(state, a.WithdrawSubmission(seat=0, manuscript=901))
    assert state.manuscript(911).position == 2
    state = do(state, a.Submit(seat=0, manuscript=902, tier=1, records=[_exp_record(802)]))
    assert state.manuscript(902).position == 1


def test_withdrawing_a_revision_puts_the_manuscript_back_in_the_revise_area():
    """Specification 5.2: a revision can be withdrawn too."""
    pending = [_manuscript(960, author=0, area="revise", records=1)]
    state = _submission(write_up=1, manuscripts=pending)
    before = state.manuscript(960).model_copy(deep=True)
    state = do(state, a.Revise(seat=0, manuscript=960), a.WithdrawSubmission(seat=0, manuscript=960))
    assert state.manuscript(960) == before
    state = do(state, a.Revise(seat=0, manuscript=960))  # the staff member is free again
    assert state.manuscript(960).area == "accept"


def test_only_this_steps_own_submissions_can_be_withdrawn_and_only_before_committing():
    """Specification 5.2: only your own submissions from this step, until you commit."""
    earlier = [_manuscript(963, author=0, area="review", position=1, records=1, inputs={"IP2": "x", "IP3": "p"})]
    state = _submission(manuscripts=earlier)
    _refused(state, a.WithdrawSubmission(seat=0, manuscript=963))  # submitted in an earlier round
    state = do(state, a.Submit(seat=1, manuscript=911, tier=1, records=[_exp_record(811)]))
    _refused(state, a.WithdrawSubmission(seat=0, manuscript=911))  # someone else's
    state = do(state, a.Submit(seat=0, manuscript=901, tier=1, records=[_exp_record(801)]))
    state = do(state, a.CommitPhase(seat=0))
    _refused(state, a.WithdrawSubmission(seat=0, manuscript=901))  # committed


# Article processing ------------------------------------------------------------------------
def _processing_state(hot=None, others=None):
    """Hot topic Probe shows ``hot``; every other Probe shows ``others`` (both IP1, IP2 readings)."""
    state = game(journal_tiers=TIERS)
    deal_probes(Ctx(state))
    for p in state.probes:
        set_readings(state, p.index, others or {"IP1": "b", "IP2": "y"})
    set_readings(state, state.hot_topic, hot or {"IP1": "b", "IP2": "y"})
    return state


@pytest.mark.parametrize(
    "inputs, records, open_access, expected",
    [
        # tier 1: 2 rounds; theory with 2 inputs + 1 outcome = 3 elements (the minimum), 1 record (the minimum)
        ({"IP1": "a", "IP2": "x"}, 1, False, 2),
        ({"IP1": "a", "IP2": "x"}, 2, False, 1),  # one extra record
        ({"IP1": "a", "IP2": "x"}, 4, False, 1),  # three extra records, but never below 1
        ({"IP1": "a", "IP2": "x", "IP3": "p"}, 1, False, 1),  # one extra element
        ({"IP1": "a", "IP2": "x"}, 1, True, 1),  # APC
        ({"IP1": "a", "IP2": "x", "IP3": "p"}, 2, True, 1),  # three reductions, floor 1
    ],
)
def test_rounds_in_processing_reductions(inputs, records, open_access, expected):
    """Article processing: each reduction shortens by 1, never below 1 through these means."""
    state = _processing_state()
    m = _manuscript(970, author=0, area="accept", tier=1, inputs=inputs, records=records, open_access=open_access)
    assert rounds_in_processing(Ctx(state), m) == expected


@pytest.mark.parametrize(
    "hot, others, expected",
    [
        ({"IP1": "a", "IP2": "x"}, {"IP1": "b", "IP2": "y"}, 1),  # matches the Hot topic Probe
        ({"IP1": "a", "IP2": None}, {"IP1": "b", "IP2": "y"}, 1),  # a blank reading never mismatches
        ({"IP1": "a", "IP2": "y"}, {"IP1": "a", "IP2": "x"}, 2),  # only the Hot topic Probe counts
    ],
)
def test_hot_topic_publication_uses_visible_readings_of_the_hot_topic_probe(hot, others, expected):
    """Article processing: a theory with no mismatching input parameter from the
    visible readings of the Hot topic Probe is shortened by 1 (tier 1 here: 2 rounds)."""
    state = _processing_state(hot=hot, others=others)
    m = _manuscript(971, author=0, area="accept", tier=1, records=1)
    assert rounds_in_processing(Ctx(state), m) == expected


def test_crisis_fast_track_can_reach_zero_but_not_below():
    """Article processing: Crisis fast-track reduces by 1 more, to 0 at most."""
    state = _processing_state()
    state.period = "crisis"
    base = _manuscript(972, author=0, area="accept", tier=1, records=1)
    reduced = _manuscript(973, author=0, area="accept", tier=1, records=4)
    tier0 = _manuscript(974, author=0, area="accept", tier=0)
    assert rounds_in_processing(Ctx(state), base) == 1  # 2 - 1
    assert rounds_in_processing(Ctx(state), reduced) == 0  # floor 1, then - 1
    assert rounds_in_processing(Ctx(state), tier0) == 0


def test_methods_only_benefit_from_apc_and_crisis():
    """Article processing: a method publication only benefits from the APC and the Crisis fast-track."""
    state = _processing_state(hot={"IP1": "a", "IP2": "x"})
    plain = _manuscript(975, author=0, area="accept", tier=1, records=4, kind="method")
    paid = _manuscript(976, author=0, area="accept", tier=1, records=4, kind="method", open_access=True)
    assert rounds_in_processing(Ctx(state), plain) == 2
    assert rounds_in_processing(Ctx(state), paid) == 1
    state.period = "crisis"
    assert rounds_in_processing(Ctx(state), paid) == 0


# Peer review (docs/parameter_defaults.yaml) --------------------------------------------------
def _review_tier():
    return next(i for i, t in enumerate(S.journal_tiers) if t.peer_review)


def test_random_draws_give_accept_decisions_without_reviewers():
    """Peer review: [peer_review_random_draws] cards of the remaining allocation deck give "accept"
    decisions, even when no one allocated staff to peer review (the deck then holds only the
    [min_reviews_for_decision] cards of the one occupied position)."""
    state = to_phase(game(), Phase.DEVELOPMENT, {0: {"development": 1}, 1: {"development": 1}})
    state.manuscripts.append(_manuscript(980, author=1, area="review", position=1, tier=_review_tier(), records=1))
    state = do(state, a.CommitPhase(seat=0), a.CommitPhase(seat=1))
    assert state.round == 2 and state.phase == Phase.HIRING
    drawn = min(S.peer_review_random_draws, S.min_reviews_for_decision)
    m = next((x for x in state.manuscripts if x.idea.id == 980), None)
    if drawn >= S.min_reviews_for_decision:
        assert m is None or m.area == "accept"
    else:
        assert m.area == "review" and m.votes == ["accept"] * drawn


def _at_peer_review():
    """Two manuscripts awaiting review (researcher 0's at position 1, researcher 1's at position 2);
    each researcher has two peer review staff. Tries seeds until someone is dealt a manuscript."""
    for seed in range(1, 60):
        alloc = {"development": 1, "peer_review": 2}
        state = to_phase(game(seed=seed), Phase.DEVELOPMENT, {0: alloc, 1: alloc})
        state.manuscripts += [
            _manuscript(981, author=0, area="review", position=1, tier=_review_tier(), records=1),
            _manuscript(982, author=1, area="review", position=2, tier=_review_tier(), records=1, inputs={"IP1": "b"}),
        ]
        state = do(state, a.CommitPhase(seat=0), a.CommitPhase(seat=1))
        if state.phase == Phase.PEER_REVIEW:
            return state
    raise AssertionError("never reached the peer review votes")


def test_allocation_cards_one_per_peer_review_staff_member():
    """Peer review: [min_reviews_for_decision] cards per occupied position plus one "0" per peer review
    staff member; one card dealt per staff member."""
    state = _at_peer_review()
    dealt = [c for seat in (0, 1) for c in state.review_cards[seat]]
    assert [len(state.review_cards[seat]) for seat in (0, 1)] == [2, 2]
    assert set(dealt) <= {0, 1, 2}
    assert all(dealt.count(pos) <= S.min_reviews_for_decision for pos in (1, 2))


def test_own_manuscript_and_two_cards_for_one_manuscript_give_two_votes():
    """Peer review (specification 5.7): a researcher can be dealt and vote on their own manuscript;
    each allocation card gives one vote; a "0" card gives no vote."""
    state = _at_peer_review()
    seat = state.waiting[0]
    own = 1 if seat == 0 else 2
    twice = state.clone()
    twice.review_cards[seat] = [own, own]
    do(twice, a.ReviewVote(seat=seat, card=0, vote="revise"), a.ReviewVote(seat=seat, card=1, vote="revise"))
    zero = state.clone()
    zero.review_cards[seat] = [0, own]
    _refused(zero, a.ReviewVote(seat=seat, card=0, vote="accept"))
    assert validate(zero, a.ReviewVote(seat=seat, card=1, vote="accept")) is None

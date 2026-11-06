"""Rules engine: Development, Publication (submission, records, revisions, peer review, article
processing), Talent development, Clean-up (publication, grants, unused staff, unpaid postdocs,
funding, records), Alliance, game end, views and replay."""

import json

import pytest

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply
from nv_core.engine.cleanup import cleanup
from nv_core.engine.context import Ctx
from nv_core.engine.ending import credit_victory, end_game
from nv_core.engine.publication import finish_peer_review, rounds_in_processing
from nv_core.record import GameRecord
from nv_core.state import Card, ExperimentCard, Idea, Manuscript, Observation, Phase, StaffCount, SupportRecord, Task
from nv_core.views import player_view, spectator_view
from tests.core.engine_helpers import do, game, publish, set_readings, settings, to_phase, tiny_world

S = settings()


# Development phase ---------------------------------------------------------------------------
def test_development_formulates_and_refuses_published_theories():
    state = game()
    published = publish(state, 1, inputs={"IP1": "a"}, outcomes={"WO1": "up"})
    state = to_phase(state, Phase.DEVELOPMENT, {0: {"development": 2}, 1: {"development": 1}})
    with pytest.raises(IllegalAction, match=f"T{published.id}"):
        apply(state, a.FormulateTheory(seat=0, inputs={"IP1": "a"}, outcomes={"WO1": "up"}))
    with pytest.raises(IllegalAction, match="at least one"):
        apply(state, a.FormulateTheory(seat=0, inputs={}, outcomes={"WO1": "up"}))
    state = do(
        state,
        a.FormulateTheory(seat=0, inputs={"IP2": "x", "IP1": "b"}, outcomes={"WO1": "down"}),
        a.DevelopMethod(seat=0, parameter="IP3"),
    )
    with pytest.raises(IllegalAction, match="2 staff"):
        apply(state, a.DevelopMethod(seat=0, parameter="IP2"))
    state = do(state, a.CommitPhase(seat=0), a.CommitPhase(seat=1))
    ideas = state.researcher(0).ideas
    assert [i.kind for i in ideas] == ["theory", "method"]
    assert list(ideas[0].inputs) == ["IP1", "IP2"]  # stored in row order


# Submission and supporting records -------------------------------------------------------------
def _submission_state():
    state = game()
    state = to_phase(state, Phase.DEVELOPMENT, {0: {"development": 1, "write_up": 3}, 1: {"development": 1}})
    r = state.researcher(0)
    r.money = 10
    r.ideas = [
        Idea(id=901, kind="theory", inputs={"IP1": "a"}, outcomes={"WO1": "up"}),
        Idea(id=902, kind="method", parameter="IP2"),
    ]
    cards = lambda e, values: [ExperimentCard(experiment=e, card=Card(var=k, state=v, origin="supply")) for k, v in values.items()]
    r.fresh.cards = cards(801, {"IP1": "a", "IP2": "x", "IP3": "p", "WO1": "up"}) + cards(
        802, {"IP1": "b", "IP2": "y", "IP3": "q", "WO1": "down"}
    )
    r.fresh.observations = [
        Observation(
            id=701, probe=0, round=1,
            cards=[Card(var="IP1", state="a", origin="supply"), Card(var="IP2", state=None, origin="supply"),
                   Card(var="IP3", state=None, origin="supply"), Card(var="WO1", state="up", origin="supply")],
        )
    ]
    state = do(state, a.CommitPhase(seat=0), a.CommitPhase(seat=1))
    assert state.phase == Phase.SUBMISSION
    return state


def test_submission_needs_the_tier_records_and_no_mismatch():
    state = _submission_state()
    tier = next(i for i, t in enumerate(S.journal_tiers) if t.min_records >= 1 and t.min_observations == 0)
    with pytest.raises(IllegalAction, match="supporting record"):
        apply(state, a.Submit(seat=0, manuscript=901, tier=tier, records=[]))
    mismatching = a.ExperimentRecord(cards=[(802, v) for v in ("IP1", "IP2", "IP3", "WO1")])
    with pytest.raises(IllegalAction, match="mismatches"):
        apply(state, a.Submit(seat=0, manuscript=901, tier=tier, records=[mismatching] * 1))
    state = do(state, a.Submit(seat=0, manuscript=901, tier=tier, records=[a.ObservationRecord(observation=701)]))
    m = state.manuscript(901)
    assert m.area == "review" and m.position == 1 and not m.records[0].fabricated
    assert not state.researcher(0).fresh.observations  # the record went with the manuscript
    assert state.researcher(0).money == 10 - S.journal_tiers[tier].submission_fee


def test_mixed_experiment_record_is_flagged_fabricated():
    """Specification 5.5: a record not from a single experiment is silently flagged."""
    state = _submission_state()
    tier = next(i for i, t in enumerate(S.journal_tiers) if t.methods_accepted and t.min_records >= 1)
    mixed = a.ExperimentRecord(cards=[(801, "IP1"), (802, "IP2"), (801, "IP3"), (802, "WO1")])
    state = do(state, a.Submit(seat=0, manuscript=902, tier=tier, records=[mixed]))
    assert state.manuscript(902).records[0].fabricated
    assert "fabricated" not in json.dumps(player_view(state, 1))
    assert player_view(state, 0)["manuscripts"][0].get("fabricated_records") is None


def test_methods_only_where_accepted_and_tier_zero_goes_to_accept_area():
    state = _submission_state()
    refusing = next((i for i, t in enumerate(S.journal_tiers) if not t.methods_accepted), None)
    if refusing is not None:
        with pytest.raises(IllegalAction, match="does not accept methods"):
            apply(state, a.Submit(seat=0, manuscript=902, tier=refusing, records=[]))
    no_review = next(i for i, t in enumerate(S.journal_tiers) if not t.peer_review)
    state = do(state, a.Submit(seat=0, manuscript=901, tier=no_review))
    assert state.manuscript(901).area == "accept"


# Article processing ------------------------------------------------------------------------
def _manuscript(state, tier, records=0, inputs=None, open_access=False, kind="theory"):
    idea = Idea(id=950, kind=kind, inputs=inputs or {"IP1": "a"}, outcomes={"WO1": "up"}, parameter="IP2" if kind == "method" else None)
    record = SupportRecord(kind="observation", area="fresh", cards=[])
    return Manuscript(idea=idea, author=0, tier=tier, open_access=open_access, records=[record] * records, round_submitted=1, area="accept")


def test_rounds_in_processing_reductions_and_floor():
    state = game()
    set_readings(state, state.hot_topic, {"IP1": "b"})  # IP1=a theories are not hot topic publications
    tier_number = max(range(len(S.journal_tiers)), key=lambda i: S.journal_tiers[i].rounds_in_processing)
    tier = S.journal_tiers[tier_number]
    ctx = Ctx(state)
    base = _manuscript(state, tier_number, records=tier.min_records)
    elements = len(base.idea.inputs) + len(base.idea.outcomes)
    extra_elements = max(0, elements - tier.min_elements)
    expected = max(min(tier.rounds_in_processing, 1), tier.rounds_in_processing - extra_elements)
    assert rounds_in_processing(ctx, base) == expected
    one_more = _manuscript(state, tier_number, records=tier.min_records + 1)
    assert rounds_in_processing(ctx, one_more) == max(1, expected - 1)
    lots = _manuscript(state, tier_number, records=tier.min_records + 10, open_access=True)
    assert rounds_in_processing(ctx, lots) == 1  # never below 1 through these reductions
    set_readings(state, state.hot_topic, {"IP1": "a"})
    assert rounds_in_processing(ctx, one_more) == max(1, expected - 2)  # hot topic too
    # Article processing: blank rows alone under the theory's inputs are not a hot topic publication.
    blank_only = _manuscript(state, tier_number, records=tier.min_records + 1, inputs={"IP3": "p"})
    set_readings(state, state.hot_topic, {"IP3": None})
    assert rounds_in_processing(ctx, blank_only) == max(1, expected - 1)
    set_readings(state, state.hot_topic, {"IP3": "p"})
    assert rounds_in_processing(ctx, blank_only) == max(1, expected - 2)
    method = _manuscript(state, tier_number, records=tier.min_records + 3, kind="method", open_access=True)
    assert rounds_in_processing(ctx, method) == max(1, tier.rounds_in_processing - 1)  # only the APC counts
    state.period = "crisis"
    assert rounds_in_processing(ctx, lots) == 0  # Crisis fast-track


# Peer review ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "votes, area",
    [
        (["revise", "revise", "accept"], "revise"),
        (["accept", "revise"], "accept"),  # no simple majority for revise
        (["revise"], "review"),  # below [min_reviews_for_decision] (with the default of 2)
    ],
)
def test_peer_review_decision(votes, area):
    state = game()
    if len(votes) >= S.min_reviews_for_decision and area == "review":
        pytest.skip("min_reviews_for_decision changed")
    m = _manuscript(state, 1)
    m.area, m.position, m.votes, m.tokens = "review", 1, list(votes), None
    state.manuscripts.append(m)
    state.review_cards, state.review_rest = {}, []
    finish_peer_review(Ctx(state))
    assert state.manuscripts[0].area == area


# Clean-up phase ----------------------------------------------------------------------------
def test_cleanup_publishes_scores_and_moves_the_grant_marker():
    state = game()
    r = state.researcher(0)
    position = S.grant_track[r.grant_position - 1]
    m = _manuscript(state, 2, open_access=True)
    m.tokens = 0
    state.manuscripts.append(m)
    old = publish(state, 1, parameter="IP3", fresh=True)
    r.staff = {Task.GRANTS: StaffCount(postdocs=position.admin)}
    credit = r.credit
    cleanup(Ctx(state))
    paper = next(p for p in state.published if p.idea.id == 950)
    assert paper.fresh and not state.paper(old.id).fresh
    assert r.credit == credit + 2 + S.OA_publication_AC_reward
    if position.expected_to_increase is not None and 1 >= position.expected_to_increase:
        assert r.grant_position == S.grant_track_starting_position + 1
    assert r.money == S.grant_track[r.grant_position - 1].funding


def test_cleanup_counts_students_as_unused_and_unpaid_postdocs_leave():
    """Clean-up phase: the unused-staff penalty comes before unpaid postdocs and students leave."""
    state = game()
    r = state.researcher(0)
    r.credit, r.money, r.postdocs, r.students, r.talent_position = 20, 1 * S.cost_of_postdoc, 2, 1, 1
    r.staff = {Task.WRITE_UP: StaffCount(postdocs=2, students=1)}
    r.used = {Task.WRITE_UP: 1}
    cleanup(Ctx(state))
    assert r.postdocs == 1 and r.students == 0 and r.talent_position == 0
    assert r.credit == 20 + 2 * S.unused_staff_penalty + 1 * S.unpaid_postdoc_penalty


def test_cleanup_patent_income_and_record_ageing():
    state = game()
    theory = publish(state, 1, inputs={"IP1": "a"}, outcomes={"WO1": "up"})
    theory.patents = [0, 0]
    r = state.researcher(0)
    r.fresh.observations = [Observation(id=1, probe=0, round=1, cards=[])]
    r.stale.observations = [Observation(id=2, probe=0, round=0, cards=[])]
    cleanup(Ctx(state))
    assert r.money == S.grant_track[r.grant_position - 1].funding + 2 * S.patent_funding
    assert [o.id for o in r.stale.observations] == [1] and not r.fresh.observations


def test_crisis_ends_after_its_last_round_with_credit_victory():
    state = game(n=3)
    state.period, state.rounds_in_crisis = "crisis", S.crisis_length
    for seat, credit in enumerate([30, 30, 5]):
        state.researcher(seat).credit = credit
    publish(state, 1, inputs={"IP1": "a"}, outcomes={"WO1": "up"})
    state.alliances = [[1, 2]]
    cleanup(Ctx(state))
    assert state.result.ending == "credit" and state.result.primary == [1] and state.result.winners == [1, 2]


def test_tied_credit_and_theories_is_a_tied_victory():
    state = game(n=3)
    for seat, credit in enumerate([30, 30, 5]):
        state.researcher(seat).credit = credit
    assert credit_victory(Ctx(state)) == [0, 1]


# Alliance -------------------------------------------------------------------------------------
def test_alliance_propose_accept_and_leave_until_warning_shot():
    state = game(n=3)
    with pytest.raises(IllegalAction, match="not proposed"):
        apply(state, a.AcceptAlliance(seat=1, partner=0))
    state = do(state, a.ProposeAlliance(seat=0, partner=1), a.AcceptAlliance(seat=1, partner=0))
    assert state.alliances == [[0, 1]]
    left = do(state, a.LeaveAlliance(seat=1, partner=0))
    assert left.alliances == []
    state.warning_revealed = True
    with pytest.raises(IllegalAction, match="unbreakable"):
        apply(state, a.LeaveAlliance(seat=1, partner=0))
    state.crisis_revealed = True
    with pytest.raises(IllegalAction, match="Crisis card"):
        apply(state, a.ProposeAlliance(seat=2, partner=0))


def test_last_chance_to_leave_is_simultaneous():
    state = game(n=3)
    state = do(state, a.ProposeAlliance(seat=0, partner=1), a.AcceptAlliance(seat=1, partner=0))
    state.period_deck = "w" + "c" * 50
    state = to_phase(state, Phase.LAST_CHANCE, {s: {"experimentation": 1} for s in range(3)})
    assert sorted(state.waiting) == [0, 1]
    state = do(state, a.LeaveAlliance(seat=0, partner=1))
    assert state.alliances == [[0, 1]]  # not revealed until everyone has decided
    state = do(state, a.CommitPhase(seat=0), a.CommitPhase(seat=1))
    assert state.alliances == [] and state.last_chance_done


def test_leave_choice_can_be_withdrawn_before_commit():
    """Specification 5.3: choices in a simultaneous step stay editable until CommitPhase."""
    state = game(n=3)
    state = do(state, a.ProposeAlliance(seat=0, partner=1), a.AcceptAlliance(seat=1, partner=0))
    state.period_deck = "w" + "c" * 50
    state = to_phase(state, Phase.LAST_CHANCE, {s: {"experimentation": 1} for s in range(3)})
    state = do(state, a.LeaveAlliance(seat=0, partner=1), a.StayInAlliance(seat=0, partner=1))
    state = do(state, a.CommitPhase(seat=0), a.CommitPhase(seat=1))
    assert state.alliances == [[0, 1]]


def test_end_game_includes_direct_allies_only():
    state = game(n=4)
    state.alliances = [[0, 1], [1, 2]]
    ctx = Ctx(state)
    end_game(ctx, "nobel", [0])
    assert state.result.winners == [0, 1]  # not 2: alliance victory is not transitional


# Views ------------------------------------------------------------------------------------
def test_player_view_hides_other_labs_and_spectator_sees_all():
    state = _submission_state()
    view_1 = json.dumps(player_view(state, 1))
    assert "LAB" not in view_1 and '"ideas": [{' not in view_1
    assert player_view(state, 1)["lab"]["seat"] == 1
    assert player_view(state, 1)["researchers"][0]["ideas"] == 2  # only the count is public
    spectator = spectator_view(state)
    assert spectator["labs"][0]["ideas"] and len(spectator["world_table"]) == len(tiny_world().rows)


def test_peer_reviewers_see_the_records_of_their_manuscripts():
    """Peer review: reviewers peek at the manuscript, records included; others see only counts."""
    state = _submission_state()
    tier = next(i for i, t in enumerate(S.journal_tiers) if t.peer_review and t.min_records >= 1 and t.min_observations == 0)
    state = do(state, a.Submit(seat=0, manuscript=901, tier=tier, records=[a.ObservationRecord(observation=701)]))
    position = state.manuscript(901).position
    assert player_view(state, 1)["manuscripts"][0]["record_cards"] is None
    state.phase, state.review_cards = Phase.PEER_REVIEW, {1: [position]}
    record_cards = player_view(state, 1)["manuscripts"][0]["record_cards"]
    assert record_cards == [{"kind": "observation", "cards": {"IP1": "a", "IP2": None, "IP3": None, "WO1": "up"}}]


def test_spectator_sees_true_probe_states():
    state = to_phase(game(), Phase.DEVELOPMENT, {0: {"development": 1}, 1: {"development": 1}})
    truth = spectator_view(state)["probe_truth"]
    for probe, states in zip(state.probes, truth):
        assert states == {**state.world.rows[state.stack_rows[probe.stack]].inputs, "WO1": probe.outcomes["WO1"].state}
    assert "probe_truth" not in player_view(state, 0)


# Replay and records ------------------------------------------------------------------------
def test_replaying_the_action_log_reproduces_the_state(tmp_path):
    record = GameRecord(world=tiny_world(), settings=S, seed=11, players=["A", "B"])
    state = record.replay()
    actions = []
    allocations = {0: {"experimentation": 1, "development": 1}, 1: {"experimentation": 1, "grants": 1}}
    for _ in range(3):  # three rounds of simple play
        for seat in list(state.waiting):
            for action in (
                a.AllocateStaff(
                    seat=seat,
                    hire_postdocs=max(0, 2 - state.researcher(seat).postdocs),
                    allocation={Task(t): StaffCount(postdocs=n) for t, n in allocations[seat].items()},
                ),
                a.CommitPhase(seat=seat),
            ):
                try:
                    state, _ = apply(state, action)
                    actions.append(action)
                except IllegalAction:
                    pass
        while state.phase != Phase.HIRING and not state.result:
            seat = state.current if state.current is not None else state.waiting[0]
            if state.phase == Phase.EXPERIMENTATION:
                action = a.RunExperiment(seat=seat, specified={"IP1": "a"})
            elif state.phase == Phase.PROBE_TIME:
                action = a.ClaimProbeTime(seat=seat, probe=next(p.index for p in state.probes if p.probe_time is None))
            elif state.phase == Phase.DEVELOPMENT and not state.pending[seat].development:
                action = a.DevelopMethod(seat=seat, parameter="IP2")
            else:
                action = a.CommitPhase(seat=seat)
            state, _ = apply(state, action)
            actions.append(action)
        if state.phase == Phase.HIRING:
            for r in state.researchers:
                assert r.money >= 0
    record.actions = actions
    path = tmp_path / "game.json"
    record.save(path)
    again = GameRecord.load(path).replay()
    assert again.model_dump() == state.model_dump()
    assert state.round == 4

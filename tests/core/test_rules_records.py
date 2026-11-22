"""Rulebook "Recording experimental findings", "Recording observations", "Archiving records",
"Supporting observational and experimental records" and "Clean-up phase": the Records area with
its record positions and [records_capacity], and the archive. Open question R4 (one slip, one
position); mixing a supporting record swaps cards so the slips stay complete, and a slip left
incomplete (only in games saved before that) is discarded at Clean-up.

The tiny world (tests/core/engine_helpers.py) has inputs IP1, IP2, IP3 and one outcome WO1.
"""

import pytest

from nv_core import actions as a
from nv_core.engine import IllegalAction, apply, legal_actions
from nv_core.engine.cleanup import cleanup
from nv_core.engine.context import Ctx
from nv_core.engine.records import positions
from nv_core.state import Idea, Phase, Researcher, SubmissionUndo, Task
from nv_core.views import player_view
from tests.core.engine_helpers import do, game, settings, to_phase
from tests.core.test_rules_publication import _exp_record, _experiment, _observation, _submission

S = settings()
VALUES = ("a", "x", "p", "up")


def _fill(r, ids, observations=()):
    r.records.cards = [c for i in ids for c in _experiment(i, VALUES)]
    r.records.observations = [_observation(i, VALUES) for i in observations]


def _cleanup(state):
    for r in state.researchers:  # nothing else of the Clean-up phase matters here
        r.credit = max(r.credit, 50)
    cleanup(Ctx(state))
    return state


# Record positions -----------------------------------------------------------------------------
def test_new_records_enter_at_the_first_position():
    """Recording experimental findings: new records enter at the first record position and push
    older ones one position higher."""
    state = to_phase(game(), Phase.EXPERIMENTATION, {0: {"experimentation": 2}, 1: {"experimentation": 2}})
    seat = state.current
    state = do(state, a.RunExperiment(seat=seat))
    first = positions(state.researcher(seat))
    while state.current != seat:
        state = do(state, a.RunExperiment(seat=state.current))
    state = do(state, a.RunExperiment(seat=seat))
    second = positions(state.researcher(seat))
    assert len(second) == 2 and second[1] == first[0]


def test_observations_and_experiments_share_the_positions():
    r = game().researcher(0)
    _fill(r, [10, 30], observations=[20])
    assert positions(r) == [30, 20, 10]


def test_cleanup_discards_records_beyond_the_capacity():
    """Clean-up phase: records in positions beyond [records_capacity] are discarded."""
    state = game()
    r = state.researcher(0)
    ids = list(range(100, 100 + S.records_capacity + 2))
    _fill(r, ids)
    _cleanup(state)
    assert positions(r) == sorted(ids, reverse=True)[: S.records_capacity]


def test_a_used_record_closes_the_gap():
    """R4: when a record leaves (here: used in a submission), the older records move down a position."""
    state = _submission()
    r = state.researcher(0)
    before = positions(r)
    used = 802
    state = do(state, a.Submit(seat=0, manuscript=901, tier=1, records=[_exp_record(used)]))
    assert positions(state.researcher(0)) == [slip for slip in before if slip != used]


def _slip(r, slip):
    """The cards on a record slip, by row: (the experiment each came from, its state)."""
    return {c.card.var: (c.experiment, c.card.state) for c in r.records.cards if c.on == slip}


def test_a_mixed_record_leaves_the_slips_it_took_from_complete():
    """Supporting observational and experimental records: mixing cards of several experiments, the
    researcher swaps cards of the same parameter position between experiment records. The slip that
    gave most cards hands its card of every row the other gave; a slip left without cards leaves."""
    state = _submission()
    mixed = a.ExperimentRecord(cards=[(801, "IP1"), (801, "IP2"), (803, "IP3"), (801, "WO1")])
    before = positions(state.researcher(0))
    state = do(state, a.Submit(seat=0, manuscript=901, tier=1, records=[mixed]))
    r = state.researcher(0)
    assert positions(r) == [slip for slip in before if slip != 801]  # 803 keeps its place
    assert _slip(r, 803) == {"IP1": (803, "a"), "IP2": (803, "x"), "IP3": (801, "p"), "WO1": (803, "up")}
    assert r.records.names == {803: [803, 801]}  # most of its cards are 803's
    record = state.manuscript(901).records[0]
    assert record.experiments == [801, 803] and record.fabricated
    _cleanup(state)
    assert 803 in positions(r)


def test_mixed_names_are_ordered_by_cards_then_age_and_never_repeat():
    """Ties go to the experiment run first, then to a name not used yet: with three cards from each,
    the record is E801 + E803 and the slip left E803 + E801."""
    state = _submission()  # tiny world: IP1, IP2, IP3, WO1 (four rows)
    mixed = a.ExperimentRecord(cards=[(801, "IP1"), (801, "IP2"), (803, "IP3"), (803, "WO1")])
    state = do(state, a.Submit(seat=0, manuscript=901, tier=1, records=[mixed]))
    r = state.researcher(0)
    assert state.manuscript(901).records[0].experiments == [801, 803]
    assert r.records.names == {803: [803, 801]}
    assert 801 not in positions(r)


def test_three_experiments_leave_two_complete_slips():
    state = _submission()
    mixed = a.ExperimentRecord(cards=[(801, "IP1"), (801, "IP2"), (803, "IP3"), (802, "WO1")])
    state = do(state, a.Submit(seat=0, manuscript=901, tier=1, records=[mixed]))
    r = state.researcher(0)
    assert state.manuscript(901).records[0].experiments == [801, 802, 803]
    assert _slip(r, 803)["IP3"] == (801, "p") and _slip(r, 802)["WO1"] == (801, "up")
    assert r.records.names == {802: [802, 801], 803: [803, 801]}
    assert 801 not in positions(r)


def test_a_mixed_slip_is_used_by_its_id_and_counts_as_fabricated():
    state = _submission()
    mixed = a.ExperimentRecord(cards=[(801, "IP1"), (801, "IP2"), (803, "IP3"), (801, "WO1")])
    state = do(state, a.Submit(seat=0, manuscript=901, tier=1, records=[mixed]))
    view = player_view(state, 0)["lab"]["records"]["experiments"]
    assert next(e for e in view if e["id"] == 803)["name"] == "E803 + E801"
    state.researcher(0).ideas.append(Idea(id=904, kind="theory", inputs={"IP1": "a", "IP2": "x"}, outcomes={"WO1": "up"}))
    state = do(state, a.Submit(seat=0, manuscript=904, tier=1, records=[_exp_record(803)]))
    record = state.manuscript(904).records[0]
    assert record.fabricated and record.experiments == [803, 801]
    assert 803 not in positions(state.researcher(0)) and state.researcher(0).records.names == {}


def test_withdrawing_a_mixed_submission_puts_every_card_back():
    state = _submission()
    r = state.researcher(0)
    before = (sorted((c.experiment, c.card.var, c.on) for c in r.records.cards), dict(r.records.names), positions(r))
    mixed = a.ExperimentRecord(cards=[(801, "IP1"), (801, "IP2"), (803, "IP3"), (801, "WO1")])
    state = do(state, a.Submit(seat=0, manuscript=901, tier=1, records=[mixed]),
               a.WithdrawSubmission(seat=0, manuscript=901))
    r = state.researcher(0)
    assert (sorted((c.experiment, c.card.var, c.on) for c in r.records.cards), dict(r.records.names), positions(r)) == before


def test_an_invalid_slip_is_discarded_at_cleanup_and_does_not_count():
    """R4: a slip without an input parameter or a world outcome card is discarded at Clean-up, and it
    does not push a valid record out of the Records area."""
    state = game()
    r = state.researcher(0)
    ids = list(range(100, 100 + S.records_capacity))
    _fill(r, ids)
    invalid = ids[-1] + 1  # the newest: only its world outcome card is left
    r.records.cards += [c for c in _experiment(invalid, VALUES) if c.card.var == "WO1"]
    _cleanup(state)
    assert positions(r) == sorted(ids, reverse=True)


def test_discarded_record_cards_go_to_the_discard_piles():
    state = game()
    r = state.researcher(0)
    _fill(r, list(range(100, 100 + S.records_capacity + 1)))
    oldest = r.records.cards[0]  # the oldest record's IP1 card, as if drawn from the Input Parameter Deck
    r.records.cards[0] = oldest.model_copy(update={"card": oldest.card.model_copy(update={"origin": "input_deck"})})
    before = len(state.input_discards["IP1"])
    _cleanup(state)
    assert len(state.input_discards["IP1"]) == before + 1


def test_no_capacity_in_a_game_saved_before_it():
    state = game(records_capacity=None)
    r = state.researcher(0)
    ids = list(range(100, 100 + S.records_capacity + 3))
    _fill(r, ids)
    _cleanup(state)
    assert len(positions(r)) == len(ids)


# Archiving records ---------------------------------------------------------------------------------
def _development(dev=1, records=4, observations=(), **overrides):
    """Researcher 0 also has a development stack and a write-up staff member, so the round stops at
    Submission after the Development phase (before Clean-up)."""
    state = to_phase(game(**overrides), Phase.DEVELOPMENT, {0: {"development": dev, "write_up": 1}, 1: {"development": 1}})
    r = state.researcher(0)
    _fill(r, list(range(100, 100 + records)), observations)
    r.ideas.append(Idea(id=990, kind="method", parameter="IP1"))
    return state


def _commit_all(state):
    while state.phase == Phase.DEVELOPMENT and state.waiting:
        state = do(state, a.CommitPhase(seat=state.waiting[0]))
    return state


def test_archiving_takes_records_out_of_the_positions():
    """Archiving records: archived records no longer have a record position."""
    state = _development(records=3)
    state = do(state, a.ArchiveRecords(seat=0, records=[101]))
    assert positions(state.researcher(0)) == [102, 101, 100]  # only a choice until the phase ends
    state = _commit_all(state)
    r = state.researcher(0)
    assert positions(r) == [102, 100] and r.archived == [101]
    assert r.used[Task.DEVELOPMENT] == 1


def test_archived_records_are_not_discarded_and_do_not_count_toward_the_capacity():
    """Archiving records: archived records are not discarded at Clean-up, nor do they count toward
    the Records capacity."""
    state = game()
    r = state.researcher(0)
    ids = list(range(100, 100 + S.records_capacity + 1))
    _fill(r, ids)
    r.archived = [ids[0]]  # the oldest, which would otherwise be discarded
    _cleanup(state)
    assert positions(r) == sorted(ids[1:], reverse=True)
    assert r.archived == [ids[0]]


def test_archived_records_support_submissions():
    """Archiving records: archived records count as being in the Records area for all other purposes."""
    state = _submission()
    r = state.researcher(0)
    r.archived = [801]
    state = do(state, a.Submit(seat=0, manuscript=901, tier=1, records=[_exp_record(801)]))
    assert state.manuscript(901).records


def test_at_most_max_archive_per_staff_member():
    """Archiving records: at most [max_archive_per_staff_member] records for each staff member."""
    per = S.max_archive_per_staff_member
    state = _development(dev=1, records=per + 1)
    ids = positions(state.researcher(0))
    state = do(state, a.ArchiveRecords(seat=0, records=ids[:per]))
    with pytest.raises(IllegalAction, match="needs 2 development staff"):
        apply(state, a.ArchiveRecords(seat=0, records=ids[: per + 1]))


def test_archiving_shares_the_development_staff_with_theories_and_methods():
    per = S.max_archive_per_staff_member
    state = _development(dev=2, records=per + 1)
    ids = positions(state.researcher(0))
    state = do(state, a.DevelopMethod(seat=0, parameter="IP1"))
    with pytest.raises(IllegalAction, match="you have 1 free"):
        apply(state, a.ArchiveRecords(seat=0, records=ids[: per + 1]))
    state = do(state, a.ArchiveRecords(seat=0, records=ids[:per]))
    with pytest.raises(IllegalAction, match="staff member"):
        apply(state, a.DevelopMethod(seat=0, parameter="IP2"))
    state = _commit_all(state)
    assert state.researcher(0).used[Task.DEVELOPMENT] == 2


def test_a_new_choice_replaces_the_old_and_an_empty_one_archives_nothing():
    state = _development(records=2)
    state = do(state, a.ArchiveRecords(seat=0, records=[100]), a.ArchiveRecords(seat=0, records=[]))
    state = _commit_all(state)
    assert state.researcher(0).archived == []
    assert state.researcher(0).used.get(Task.DEVELOPMENT, 0) == 0


def test_cannot_archive_a_record_twice_or_one_you_do_not_have():
    state = _development(records=2)
    state.researcher(0).archived = [100]
    with pytest.raises(IllegalAction, match="archived already"):
        apply(state, a.ArchiveRecords(seat=0, records=[100]))
    with pytest.raises(IllegalAction, match="no record"):
        apply(state, a.ArchiveRecords(seat=0, records=[999]))
    with pytest.raises(IllegalAction, match="twice"):
        apply(state, a.ArchiveRecords(seat=0, records=[101, 101]))


def test_observations_can_be_archived():
    state = _development(records=0, observations=[700])
    state = _commit_all(do(state, a.ArchiveRecords(seat=0, records=[700])))
    assert state.researcher(0).archived == [700]


def test_archiving_is_announced_but_the_records_stay_hidden():
    """Specification 5.7 (Archiving records): the others see that a researcher archives, and how many."""
    state = _development(records=2)
    state, events = apply(do(state, a.ArchiveRecords(seat=0, records=[100, 101])), a.CommitPhase(seat=0))
    state, events = apply(state, a.CommitPhase(seat=1))
    public = [e for e in events if e.kind == "archive"]
    private = [e for e in events if e.kind == "archive_private"]
    assert public and public[0].visible_to is None and "2 record(s)" in public[0].text
    assert private and private[0].visible_to == [0] and "E100" in private[0].text


def test_archive_option_lists_the_records_in_position_order():
    state = _development(records=3)
    option = next(o for o in legal_actions(state, 0) if o.type == "archive_records")
    assert option.template["records"] == [102, 101, 100]
    assert option.template["per_staff_member"] == S.max_archive_per_staff_member


def test_no_archiving_in_a_game_saved_before_it():
    state = _development(records=2, max_archive_per_staff_member=None)
    assert not any(o.type == "archive_records" for o in legal_actions(state, 0))
    with pytest.raises(IllegalAction, match="before archiving"):
        apply(state, a.ArchiveRecords(seat=0, records=[100]))


def test_view_gives_positions_and_archive():
    state = game()
    r = state.researcher(0)
    _fill(r, [100, 101, 102])
    r.archived = [101]
    records = player_view(state, 0)["lab"]["records"]
    found = {e["id"]: (e["position"], e["archived"]) for e in records["experiments"]}
    assert found == {102: (1, False), 101: (None, True), 100: (2, False)}
    assert records["capacity"] == S.records_capacity
    assert "lab" not in player_view(state, 1) or player_view(state, 1)["lab"]["seat"] == 1
    summary = player_view(state, 1)["researchers"][0]
    assert (summary["records"], summary["archived"]) == (2, 1)


# Games saved before the Records area -----------------------------------------------------------
def test_old_fresh_and_stale_areas_become_one_records_area():
    data = game().researcher(0).model_dump(mode="json")
    del data["records"]
    data["fresh"] = {"observations": [], "cards": [c.model_dump(mode="json") for c in _experiment(5, VALUES)]}
    data["stale"] = {"observations": [_observation(3, VALUES).model_dump(mode="json")], "cards": []}
    r = Researcher.model_validate(data)
    assert positions(r) == [5, 3]


def test_old_submission_undo_merges_its_areas():
    undo = SubmissionUndo.model_validate({"manuscript": 1, "taken": {
        "fresh": {"observations": [], "cards": [c.model_dump(mode="json") for c in _experiment(5, VALUES)]},
        "stale": {"observations": [], "cards": []},
    }})
    assert len(undo.taken.cards) == len(VALUES)

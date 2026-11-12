"""Specification 7.4: what the task panel shows before a choice (nv_core.preview) and the report after
scoring. These numbers must be the ones the engine then really applies."""

from nv_core import actions as a
from nv_core.engine import apply
from nv_core.engine.context import Ctx
from nv_core.engine.publication import rounds_in_processing
from nv_core.preview import task_preview
from nv_core.state import Idea, Manuscript, Phase, StaffCount, SupportRecord, Task
from nv_core.views import player_view
from tests.core.engine_helpers import do, game, settings, to_phase
from tests.core.test_rules_predictions import _at_prediction, _credits, _finish, _predict, _theory, _to_reveal

S = settings()
RIGHT = ({"IP1": "a", "IP2": "x"}, {"WO1": "up", "WO2": "big"})
WRONG = ({"IP1": "a"}, {"WO1": "down"})


def test_prediction_preview_is_what_scoring_then_gives():
    state = _at_prediction()
    t = _theory(state, 1, *RIGHT)
    preview = task_preview(state, 0)["theories"][t.id]
    assert preview["author_success"] is None and preview["patent"] == "new"
    before = _credits(state)
    state, _ = _predict(state, 0, t.id, 0, prereg=True)
    state = _finish(state)
    assert _credits(state)[0] - before[0] == preview["preregistered"]["success"]


def test_prediction_preview_of_a_failure():
    state = _at_prediction()
    t = _theory(state, 1, *WRONG)
    preview = task_preview(state, 0)["theories"][t.id]
    assert preview["plain"]["failure"] == S.failed_non_prereg_pred_ac
    assert preview["preregistered"]["failure"] == S.failed_prereg_pred_ac


def test_prediction_preview_counts_your_own_theory_as_author():
    state = _at_prediction()
    t = _theory(state, 0, *RIGHT)
    preview = task_preview(state, 0)["theories"][t.id]
    assert preview["author_success"] == S.citation_reward
    assert preview["author_failure"] == 0


def test_prediction_preview_in_the_crisis_has_only_preregistered_amounts():
    state = _at_prediction(period="crisis")
    t = _theory(state, 0, *RIGHT)
    preview = task_preview(state, 0)["theories"][t.id]
    assert preview["plain"] is None
    assert preview["preregistered"]["failure"] == S.failed_prereg_pred_ac_crisis
    assert preview["author_failure"] == S.crisis_failed_pred_citation_penalty
    assert preview["author_success"] == S.citation_reward + S.crisis_pred_citation_reward_bonus


def test_prediction_preview_names_who_already_holds_the_patent():
    state = _at_prediction()
    t = _theory(state, 1, *RIGHT, patents=[1])
    preview = task_preview(state, 0)["theories"][t.id]
    assert (preview["patent"], preview["patent_holder"]) == ("held", 1)


def test_reveal_preview_knows_the_outcome():
    state = _at_prediction()
    right = _theory(state, 1, *RIGHT)
    wrong = _theory(state, 1, *WRONG)
    state, good = _predict(state, 0, right.id, 0)
    state, bad = _predict(state, 0, wrong.id, 0)
    state = _to_reveal(state)
    assert state.phase == Phase.REVEAL
    reveals = task_preview(state, 0)["reveals"]
    assert reveals[good]["success"] and reveals[good]["patent"] == "new"
    assert not reveals[bad]["success"] and reveals[bad]["patent"] is None
    assert reveals[bad]["credit"] == S.failed_non_prereg_pred_ac


def test_reveal_preview_lists_preregistered_predictions_too():
    state = _at_prediction()
    t = _theory(state, 1, *RIGHT)
    other = _theory(state, 1, *WRONG)
    state, preregistered = _predict(state, 0, t.id, 0, prereg=True)
    state, _ = _predict(state, 0, other.id, 0)
    state = _to_reveal(state)
    assert state.phase == Phase.REVEAL
    reveals = task_preview(state, 0)["reveals"]
    assert reveals[preregistered]["credit"] == 2 * 2 * 2


# The report ------------------------------------------------------------------------------------
def _reveal_all(state):
    state = _to_reveal(state)
    for prediction in list(state.predictions):
        if not prediction.preregistered:
            state = do(state, a.RevealPrediction(seat=prediction.seat, prediction=prediction.id))
    return _finish(state)


def _entry(state, prediction_id):
    return next(p for p in state.prediction_report["predictions"] if p["id"] == prediction_id)


def test_report_gives_outcome_credit_author_and_patent():
    state = _at_prediction()
    t = _theory(state, 1, *RIGHT)
    state, pid = _predict(state, 0, t.id, 0, prereg=True)
    state = _finish(state)
    entry = _entry(state, pid)
    assert entry["outcome"] == "success" and entry["preregistered"]
    assert entry["credit"] == 2 * 2 * 2
    assert (entry["author"], entry["author_credit"]) == (1, S.citation_reward)
    assert entry["patent"] == "new"
    assert state.prediction_report["round"] == state.round


def test_report_of_a_later_success_shows_the_patent_stays():
    state = _at_prediction()
    t = _theory(state, 1, *RIGHT, patents=[1])
    state, pid = _predict(state, 0, t.id, 0, prereg=True)
    state = _finish(state)
    entry = _entry(state, pid)
    assert (entry["patent"], entry["patent_holder"]) == ("held", 1)
    assert state.paper(t.id).patents == [1]


def test_report_of_a_failure():
    state = _at_prediction()
    t = _theory(state, 1, *WRONG)
    state, pid = _predict(state, 0, t.id, 0, prereg=True)
    state = _finish(state)
    entry = _entry(state, pid)
    assert entry["outcome"] == "failed" and entry["patent"] is None
    assert entry["credit"] == S.failed_prereg_pred_ac


def test_report_of_two_predictions_on_one_theory():
    state = _at_prediction()
    first, second = state.turn_order()[:2]
    t = _theory(state, second, *WRONG)
    state, one = _predict(state, first, t.id, 0, prereg=True)
    state, two = _predict(state, second, t.id, 1, prereg=True)
    state = _finish(state)
    for pid in (one, two):
        entry = _entry(state, pid)
        assert entry["outcome"] == "failed" and entry["credit"] == S.failed_prereg_pred_ac
        assert entry["author"] == second


def test_report_leaves_out_predictions_that_stayed_hidden():
    state = _at_prediction()
    t = _theory(state, 1, *RIGHT)
    other = _theory(state, 1, *WRONG)
    state, shown = _predict(state, 0, t.id, 0, prereg=True)
    state, hidden = _predict(state, 0, other.id, 0)
    state = _finish(state)
    ids = {p["id"] for p in state.prediction_report["predictions"]}
    assert shown in ids and hidden not in ids


def test_no_report_when_nothing_was_revealed():
    state = _at_prediction()
    t = _theory(state, 1, *RIGHT)
    state, _ = _predict(state, 0, t.id, 0)
    state = _finish(state)
    assert state.prediction_report is None


def test_report_marks_the_prediction_that_won_the_nobel_prize():
    state = _at_prediction()
    first, second = state.turn_order()[:2]
    winner = _theory(state, second, *RIGHT, nobel=S.nobel_condition - 1)
    later = _theory(state, second, {"IP2": "x"}, {"WO2": "big"})
    state, won = _predict(state, first, winner.id, 0, prereg=True)
    state, unscored = _predict(state, second, later.id, 1, prereg=True)
    state = _finish(state)
    assert state.result and state.result.ending == "nobel"
    assert _entry(state, won)["nobel"] is True
    assert _entry(state, unscored)["outcome"] == "unscored"  # the game ended first


def test_report_of_a_crisis_round_counts_the_missed_probes():
    state = _at_prediction(period="crisis")
    t = _theory(state, 1, *RIGHT)
    state, _ = _predict(state, 0, t.id, 0)
    state = _finish(state)
    report = state.prediction_report
    assert report["crisis"] and report["missed"] == [p.index for p in state.probes if p.index != 0]
    assert report["unsuccessful"] == len(state.probes) - 1
    assert report["crisis_condition"] == S.crisis_condition


def test_report_is_in_every_players_view():
    state = _at_prediction()
    t = _theory(state, 1, *RIGHT)
    state, _ = _predict(state, 0, t.id, 0, prereg=True)
    state = _finish(state)
    assert player_view(state, 1)["prediction_report"] == state.prediction_report


def test_preview_changes_nothing():
    state = _at_prediction()
    _theory(state, 1, *RIGHT)
    before = state.model_dump_json()
    task_preview(state, 0)
    assert state.model_dump_json() == before


# Hiring and Submission ------------------------------------------------------------------------------
def test_repeat_has_nothing_in_the_first_round():
    assert task_preview(game(), 0)["previous_allocation"] is None


def test_repeat_gives_the_allocation_as_made_at_hiring():
    state = game()
    state.period_deck = "c" * 200
    state = to_phase(state, Phase.EXPERIMENTATION, {0: {"experimentation": 2}, 1: {"experimentation": 1}})
    state = state.clone()
    state.researcher(0).staff[Task.EXPERIMENTATION] = StaffCount(postdocs=1)  # e.g. someone left later
    state.phase = Phase.HIRING
    assert task_preview(state, 0)["previous_allocation"] == {"experimentation": {"postdocs": 2, "students": 0}}


def _at_submission(records=0):
    state = game()
    state.period_deck = "c" * 200
    idea = Idea(id=950, kind="theory", inputs={"IP1": "a"}, outcomes={"WO1": "up"})
    state.researcher(0).ideas.append(idea)
    state = to_phase(state, Phase.SUBMISSION, {0: {"write_up": 1}, 1: {"write_up": 1}})
    assert state.phase == Phase.SUBMISSION
    return state, idea


def test_processing_preview_is_what_acceptance_then_gives():
    state, idea = _at_submission()
    processing = task_preview(state, 0)["processing"]
    assert processing
    ctx = Ctx(state)
    record = SupportRecord(kind="observation", area="fresh", cards=[])
    for key, p in processing.items():
        tier = int(key.split("/")[1])
        manuscript = Manuscript(idea=idea, author=0, tier=tier, open_access=False, records=[record] * p["first_records"],
                                round_submitted=1, area="accept")
        assert p["rounds"][0] == rounds_in_processing(ctx, manuscript)
        manuscript.open_access = True
        assert p["rounds_with_apc"][0] == rounds_in_processing(ctx, manuscript)
        assert p["base"] == S.journal_tiers[tier].rounds_in_processing


def test_no_processing_preview_without_write_up_staff():
    state, _ = _at_submission()
    state = state.clone()
    state.researcher(1).used[Task.WRITE_UP] = 1
    assert task_preview(state, 1) == {"processing": {}}


def test_apply_ignores_the_preview():
    """The preview adds no state: an action is accepted or refused exactly as without it."""
    state = _at_prediction()
    t = _theory(state, 1, *RIGHT)
    action = a.MakePrediction(seat=0, theory=t.id, probe=0)
    without, _ = apply(state, action)
    task_preview(state, 0)
    again, _ = apply(state, action)
    assert again.model_dump_json() == without.model_dump_json()


# The Grants row ---------------------------------------------------------------------------------------
def test_hiring_preview_names_the_admin_of_the_current_grant_position():
    state = game()
    state.researcher(0).grant_position = len(S.grant_track)
    assert task_preview(state, 0)["grant_admin_needed"] == S.grant_track[-1].admin
    assert task_preview(state, 1)["grant_admin_needed"] == S.grant_track[S.grant_track_starting_position - 1].admin


def test_student_check_preview_names_it_too():
    state = game()
    state = state.clone()
    state.phase = Phase.STUDENT_CHECK
    assert task_preview(state, 0) == {"grant_admin_needed": S.grant_track[S.grant_track_starting_position - 1].admin}


def test_prediction_preview_counts_against_the_limit():
    state = _at_prediction(dc=1)
    t = _theory(state, 1, *RIGHT)
    assert task_preview(state, 0)["prediction_limit"] == {"made": 0, "allowed": S.predictions_per_staff}
    state, _ = _predict(state, 0, t.id, 0)
    assert task_preview(state, 0)["prediction_limit"]["made"] == 1


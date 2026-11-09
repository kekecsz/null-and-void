"""What a choice would lead to, for the web client's task panel (specification 7.4).

Read only: nothing here changes the state or draws at random. The numbers come from the same
functions the engine scores with, so the client holds no game rule. Kept apart from
``legal_actions`` because only people need it; the bots and AI players never see it.
"""

from typing import Any

from nv_core.engine.context import Ctx
from nv_core.engine.observation import _success, cited_theory, credit_changes
from nv_core.engine.publication import possible_submissions, processing_time
from nv_core.state import GameState, Paper, Phase, Prediction, Researcher, Task


def _patent(paper: Paper) -> tuple[str, int | None]:
    return ("held", paper.patents[0]) if paper.patents else ("new", None)


def _theories(ctx: Ctx, seat: int) -> dict[int, dict[str, Any]]:
    """For each theory the researcher may predict with: the credit if it succeeds or fails."""
    state = ctx.state
    crisis = state.period == "crisis"
    result = {}
    for paper in state.published:
        if paper.kind != "theory" or not ctx.usable_by(paper, seat):
            continue
        idea = paper.idea
        probe_id = Prediction(id=0, seat=seat, probe=0, theory=paper.id, inputs=idea.inputs, outcomes=idea.outcomes)
        cited = state.paper(cited_theory(ctx, probe_id))
        changes = {
            preregistered: {
                outcome: credit_changes(ctx.settings, crisis, len(idea.inputs), len(idea.outcomes), preregistered, outcome)
                for outcome in (True, False)
            }
            for preregistered in (False, True)
        }
        own = cited.author == seat
        patent, patent_holder = _patent(cited)
        result[paper.id] = {
            "plain": None if crisis else {"success": changes[False][True][0], "failure": changes[False][False][0]},
            "preregistered": {"success": changes[True][True][0], "failure": changes[True][False][0]},
            "author_success": changes[True][True][1] if own else None,
            "author_failure": changes[True][False][1] if own else None,
            "patent": patent,
            "patent_holder": patent_holder,
        }
    return result


def _reveals(ctx: Ctx, seat: int) -> dict[int, dict[str, Any]]:
    """For each of the researcher's predictions: what revealing it does, if it is not pruned."""
    state = ctx.state
    crisis = state.period == "crisis"
    result = {}
    for p in state.predictions:
        if p.seat != seat:
            continue
        success = _success(ctx, p)
        gained, author_gained = credit_changes(ctx.settings, crisis, len(p.inputs), len(p.outcomes), p.preregistered, success)
        paper = state.paper(p.cited)
        patent, patent_holder = _patent(paper) if success else (None, None)
        result[p.id] = {
            "success": success,
            "credit": gained,
            "author_credit": author_gained if paper.author == seat else None,
            "patent": patent,
            "patent_holder": patent_holder,
            "pruned": p.status == "pruned",
        }
    return result


def _processing(ctx: Ctx, r: Researcher, seat: int) -> dict[str, dict[str, Any]]:
    """For each possible submission: rounds in processing for every number of records it can have."""
    if r.remaining(Task.WRITE_UP) <= 0:
        return {}
    ideas = {i.id: i for i in r.ideas}
    result = {}
    for submit, spare in possible_submissions(ctx, seat):
        idea = ideas[submit.manuscript]
        first = len(submit.records)
        counts = range(first, first + len(spare) + 1)
        without = [processing_time(ctx, submit.tier, idea, n, False) for n in counts]
        result[f"{submit.manuscript}/{submit.tier}"] = {
            "first_records": first,
            "base": without[0]["base"],
            "extra_elements": without[0]["extra_elements"],
            "hot_topic": without[0]["hot_topic"],
            "crisis": without[0]["crisis"],
            "extra_records": [t["extra_records"] for t in without],
            "rounds": [t["rounds"] for t in without],
            "rounds_with_apc": [processing_time(ctx, submit.tier, idea, n, True)["rounds"] for n in counts],
        }
    return result


def task_preview(state: GameState, seat: int) -> dict[str, Any]:
    """Only what the current step can use."""
    ctx = Ctx(state)
    r = state.researcher(seat)
    if state.phase == Phase.HIRING:
        previous = {t.value: c.model_dump() for t, c in r.last_allocation.items()}
        return {"previous_allocation": previous or None}
    if state.phase == Phase.PREDICTION:
        return {"theories": _theories(ctx, seat)}
    if state.phase == Phase.REVEAL:
        return {"reveals": _reveals(ctx, seat)}
    if state.phase == Phase.SUBMISSION:
        return {"processing": _processing(ctx, r, seat)}
    return {}

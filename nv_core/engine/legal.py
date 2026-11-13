"""What a researcher may do now (specification section 5.3).

``legal_actions(state, seat)`` returns a list of options. A small choice comes as complete
actions (``actions``); a large one (staff allocation, experiments, theories, submissions) as a
template (``template``) that states its limits. Every complete action listed is legal now; an
action built from a template still goes through ``validate``/``apply``, which give the reason
when it is refused.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict

from nv_core import actions as a
from nv_core.engine.context import Ctx, IllegalAction
from nv_core.engine.experimentation import MAX_SENSOR_LEVEL, check_expand_lab
from nv_core.engine.hiring import POSTDOC_ONLY
from nv_core.engine.observation import _capacity, _revealable, _success, mismatch, same_theory_on_probe
from nv_core.engine.development import staff_chosen
from nv_core.engine.publication import possible_submissions
from nv_core.engine.records import positions
from nv_core.state import GameState, Phase, Task


class Option(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str  # the action type, as in nv_core.actions
    actions: list[a.Action] = []
    template: dict[str, Any] | None = None


def _commit_ok(ctx: Ctx, seat: int, check) -> bool:
    if check is None:
        return True
    try:
        check(ctx, seat)
    except IllegalAction:
        return False
    return True


def legal_actions(state: GameState, seat: int) -> list[Option]:
    from nv_core.engine import SIMULTANEOUS, STEPS  # imported here: the engine package imports this module

    if state.result is not None:
        return []
    ctx = Ctx(state)  # only read: none of the helpers below changes the state or draws at random
    s = ctx.state
    options: list[Option] = []
    r = s.researcher(seat)
    waiting = seat in s.waiting
    phase = s.phase

    if phase == Phase.HIRING and waiting:
        cost = ctx.settings.cost_of_postdoc
        affordable = r.money // cost if cost else None
        # None as the upper limit: postdocs cost nothing, so any number can be hired.
        max_postdocs = affordable
        if r.credit == 0:  # Academic credit rules: only the un-fundable postdocs are fired
            min_postdocs = r.postdocs if affordable is None else min(r.postdocs, affordable)
        else:
            min_postdocs = 0
        options.append(
            Option(
                type="allocate_staff",
                template={
                    "postdocs_now": r.postdocs,
                    "postdocs_after": [min_postdocs, max_postdocs],
                    "max_students": ctx.settings.student_hire_cap(r.talent_position),
                    "tasks": [t.value for t in Task],
                    "postdoc_only": [t.value for t in POSTDOC_ONLY],
                    "at_most_one": [Task.TALENT_DEVELOPMENT.value],
                    # the most staff members (postdocs and students together) a task can take
                    "task_caps": {
                        Task.TALENT_DEVELOPMENT.value: 1,
                        **({Task.EXPERIMENTATION.value: r.lab_capacity} if r.lab_capacity is not None else {}),
                    },
                    "every_staff_member_needs_a_task": True,
                },
            )
        )
    elif phase == Phase.LAST_CHANCE and waiting:
        chosen = s.pending[seat].leave_alliances
        for pair in s.alliances:
            if seat in pair:
                partner = pair[0] if pair[1] == seat else pair[1]
                cls = a.StayInAlliance if partner in chosen else a.LeaveAlliance
                options.append(Option(type=cls.model_fields["type"].default, actions=[cls(seat=seat, partner=partner)]))
    elif phase == Phase.STUDENT_CHECK and waiting:
        options.append(
            Option(
                type="choose_leaving_students",
                template={
                    "count": r.leaving_students,
                    "students_by_task": {t.value: c.students for t, c in r.staff.items() if c.students},
                },
            )
        )
    elif phase == Phase.EXPERIMENTATION and s.current == seat:
        methods = [
            p for p in s.published if p.kind == "method" and ctx.usable_by(p, seat)
        ]
        options.append(
            Option(
                type="run_experiment",
                template={
                    "free_input_parameters": ctx.settings.experiment_free_input_parameters,
                    "states": {v.id: v.states for v in ctx.world.input_parameters},
                    "methods": [{"id": m.id, "parameter": m.idea.parameter} for m in methods],
                    "rule": "each cited method adds its own parameter, which must be specified; "
                    "cited methods are specific to different parameters",
                },
            )
        )
        sensors = []
        for probe in s.probes:
            for parameter in ctx.world.input_ids:
                if parameter in probe.specialty:
                    continue
                level = probe.sensors.get(parameter, 0)
                usable = [m.id for m in methods if m.idea.parameter == parameter]
                if level < MAX_SENSOR_LEVEL and len(usable) >= level + 1:
                    sensors.append(
                        {"probe": probe.index, "parameter": parameter, "methods_needed": level + 1, "methods": usable}
                    )
        if sensors:
            options.append(Option(type="install_sensor", template={"choices": sensors}))
        if r.credit > 0:
            options.append(Option(type="pass", actions=[a.Pass(seat=seat)]))
    elif phase == Phase.PROBE_TIME and s.current == seat:
        options.append(
            Option(
                type="claim_probe_time",
                actions=[a.ClaimProbeTime(seat=seat, probe=p.index) for p in s.probes if p.probe_time is None],
            )
        )
    elif phase == Phase.PREDICTION and waiting:
        mine = [p for p in s.predictions if p.seat == seat]
        staff = r.allocated(Task.DATA_COLLECTION)
        preregistered = [p for p in mine if p.preregistered]
        crisis = s.period == "crisis"
        theories = [p for p in s.published if p.kind == "theory" and ctx.usable_by(p, seat)]
        limit = ctx.settings.prediction_limit(staff)
        if limit is not None and len(mine) >= limit:
            theories = []  # Formulating predictions and preregistration: no room for another
        makes = []
        for paper in theories:
            can_prereg = len(preregistered) < staff
            for probe in s.probes:
                if mismatch(paper.idea.inputs, probe.readings):
                    continue
                if same_theory_on_probe(ctx, seat, paper.idea.inputs, paper.idea.outcomes, probe.index):
                    continue
                if crisis:
                    if can_prereg:
                        makes.append(a.MakePrediction(seat=seat, theory=paper.id, probe=probe.index, preregister=True))
                    continue
                makes.append(a.MakePrediction(seat=seat, theory=paper.id, probe=probe.index))
                if can_prereg:
                    makes.append(a.MakePrediction(seat=seat, theory=paper.id, probe=probe.index, preregister=True))
        if makes:
            options.append(Option(type="make_prediction", actions=makes))
        if mine:
            options.append(
                Option(type="cancel_prediction", actions=[a.CancelPrediction(seat=seat, prediction=p.id) for p in mine])
            )
    elif phase == Phase.REVEAL and waiting:
        chosen = [p for p in s.predictions if p.seat == seat and not p.preregistered and p.revealed]
        room = len(chosen) < _capacity(ctx, seat)
        reveals = []
        for p in _revealable(ctx, seat):
            if p.revealed:
                reveals.append(a.RevealPrediction(seat=seat, prediction=p.id, reveal=False))
            elif room and (r.credit > 0 or _success(ctx, p)):
                reveals.append(a.RevealPrediction(seat=seat, prediction=p.id))
        if reveals:
            options.append(Option(type="reveal_prediction", actions=reveals))
    elif phase == Phase.SCORING_ORDER and waiting:
        from nv_core.engine.observation import _order_choices

        ids = [p.id for group in _order_choices(ctx).get(seat, []) for p in group]
        options.append(Option(type="order_predictions", template={"predictions": ids}))
    elif phase == Phase.DEVELOPMENT and waiting:
        pending = s.pending[seat].development
        if staff_chosen(ctx, seat) < r.allocated(Task.DEVELOPMENT):
            options.append(
                Option(
                    type="formulate_theory",
                    template={
                        "inputs": {v.id: v.states for v in ctx.world.input_parameters},
                        "outcomes": {v.id: v.states for v in ctx.world.world_outcomes},
                        "at_least_one_each": True,
                        "published": [
                            {"inputs": p.idea.inputs, "outcomes": p.idea.outcomes} for p in s.published if p.kind == "theory"
                        ],
                    },
                )
            )
            options.append(
                Option(
                    type="develop_method",
                    actions=[a.DevelopMethod(seat=seat, parameter=v) for v in ctx.world.input_ids],
                )
            )
        per = ctx.settings.max_archive_per_staff_member
        archivable = positions(r)
        if per is not None and (archivable or s.pending[seat].archive):
            options.append(
                Option(
                    type="archive_records",
                    template={
                        "records": archivable,  # in record position order, the first is position 1
                        "chosen": list(s.pending[seat].archive),
                        "per_staff_member": per,
                        "staff_free": r.allocated(Task.DEVELOPMENT) - len(pending),
                        "rule": "the list replaces the earlier choice; every started group of "
                        "per_staff_member records uses one development staff member",
                    },
                )
            )
        if pending:
            options.append(
                Option(
                    type="cancel_development",
                    actions=[a.CancelDevelopment(seat=seat, index=i) for i in range(len(pending))],
                )
            )
    elif phase == Phase.SUBMISSION and waiting:
        revisable = [m for m in s.manuscripts if m.author == seat and m.area == "revise"]
        room = r.remaining(Task.WRITE_UP) > 0
        if revisable and room:
            options.append(Option(type="revise", actions=[a.Revise(seat=seat, manuscript=m.id) for m in revisable]))
        if s.pending[seat].submissions:
            options.append(
                Option(
                    type="withdraw_submission",
                    actions=[a.WithdrawSubmission(seat=seat, manuscript=u.manuscript) for u in s.pending[seat].submissions],
                )
            )
        found = possible_submissions(ctx, seat) if room else []
        if found:
            tiers = ctx.settings.journal_tiers
            options.append(
                Option(
                    type="submit",
                    actions=[submit for submit, _ in found],
                    template={
                        "spare_records": {
                            f"{submit.manuscript}/{submit.tier}": [rec.model_dump() for rec in spare]
                            for submit, spare in found
                        },
                        "apc": {str(i): t.apc for i, t in enumerate(tiers)},
                        "submission_fee": {str(i): t.submission_fee for i, t in enumerate(tiers)},
                        "spendable": ctx.spendable(r),
                        "rule": "extra records and pay_apc may be added to a listed submission",
                    },
                )
            )
    elif phase == Phase.PEER_REVIEW and waiting:
        votes = [
            a.ReviewVote(seat=seat, card=i, vote=vote)
            for i, card in enumerate(s.review_cards.get(seat, []))
            if card
            for vote in ("accept", "revise")
        ]
        if votes:
            options.append(Option(type="review_vote", actions=votes))

    if phase == Phase.EXPERIMENTATION and _commit_ok(ctx, seat, check_expand_lab):
        # any time during the phase, also when it is not the researcher's turn
        options.append(Option(type="expand_lab", actions=[a.ExpandLab(seat=seat)]))

    if phase in SIMULTANEOUS and waiting and _commit_ok(ctx, seat, STEPS[phase].commit_check):
        options.append(Option(type="commit", actions=[a.CommitPhase(seat=seat)]))

    # Alliance actions, any time the rulebook allows
    if phase != Phase.LAST_CHANCE:
        alliance: list = []
        for other in range(s.n_players):
            if other == seat:
                continue
            pair = sorted((seat, other))
            if pair in s.alliances:
                if not s.warning_revealed:
                    alliance.append(a.LeaveAlliance(seat=seat, partner=other))
            elif not s.crisis_revealed:
                if [other, seat] in s.proposals:
                    alliance.append(a.AcceptAlliance(seat=seat, partner=other))
                elif [seat, other] not in s.proposals:
                    alliance.append(a.ProposeAlliance(seat=seat, partner=other))
        if alliance:
            options.append(Option(type="alliance", actions=alliance))
    return options

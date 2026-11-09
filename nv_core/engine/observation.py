"""Observation and prediction phase, Nobel Prize, Retraction and the Crisis count."""

from nv_core.actions import CancelPrediction, MakePrediction, OrderPredictions, RevealPrediction, SetPreregistered
from nv_core.engine.context import Ctx, IllegalAction, stack_cards
from nv_core.engine.ending import allies, check_crisis_crash, end_game
from nv_core.settings import Settings
from nv_core.state import Card, Idea, Observation, Paper, Prediction, Probe, Task


# Revealing input parameters ------------------------------------------------------------------
def deal_probes(ctx: Ctx) -> None:
    state, s = ctx.state, ctx.settings
    for probe in state.probes:
        stack = ctx.draw_probe_stack()
        cards = stack_cards(ctx, stack)
        probe.stack = stack
        probe.outcomes = {o: cards[o] for o in ctx.world.outcome_ids}
        probe.outcomes_revealed = False
        probe.unrevealed_noise = {}
        probe.readings = {}
        for parameter in ctx.world.input_ids:
            true_state = cards[parameter].state
            level = probe.sensors.get(parameter, 0)
            if parameter in probe.specialty:
                probe.readings[parameter] = cards[parameter]
            elif state.period == "crisis":
                # Probes in Crisis: the top card of the base deck, no Noise cards.
                probe.readings[parameter] = Card(var=parameter, state=true_state, origin="supply")
            elif level:
                n_noise = s.probe_fake_input_deck_size // 2 ** (level - 1)
                noise = [ctx.draw_input(parameter) for _ in range(n_noise)]
                deck: list[tuple[str, str]] = [("true", true_state)] * s.probe_true_input_deck_size
                deck += [("noise", value) for value in noise]
                ctx.rng.shuffle("sensor_noise", deck)
                kind, value = deck[0]
                origin = "supply" if kind == "true" else "input_deck"
                probe.readings[parameter] = Card(var=parameter, state=value, origin=origin)
                if kind == "noise":
                    noise.remove(value)
                probe.unrevealed_noise[parameter] = noise
            else:
                probe.readings[parameter] = Card(var=parameter, state=None, origin="supply")
        shown = ", ".join(f"{k}={c.state or 'blank'}" for k, c in probe.readings.items())
        ctx.log("probe", f"P{probe.index + 1}: {shown}", probe=probe.index, readings={k: c.state for k, c in probe.readings.items()})


def mismatch(values: dict[str, str], cards: dict[str, Card]) -> bool:
    """True when a specified state differs from a non-blank card on the same row."""
    return any(var in cards and cards[var].state is not None and cards[var].state != value for var, value in values.items())


# Formulating predictions and preregistration -----------------------------------------------------
def _usable_theories(ctx: Ctx, seat: int) -> list[Paper]:
    return [p for p in ctx.state.published if p.kind == "theory" and ctx.usable_by(p, seat)]


def _can_predict(ctx: Ctx, seat: int) -> bool:
    if ctx.state.researcher(seat).allocated(Task.DATA_COLLECTION) < 1:
        return False
    return any(
        not mismatch(paper.idea.inputs, probe.readings) for paper in _usable_theories(ctx, seat) for probe in ctx.state.probes
    )


def start_prediction(ctx: Ctx) -> None:
    state = ctx.state
    state.predictions = []
    state.waiting = [seat for seat in state.turn_order() if _can_predict(ctx, seat)]


def _own(ctx: Ctx, seat: int, prediction_id: int) -> Prediction:
    for prediction in ctx.state.predictions:
        if prediction.id == prediction_id and prediction.seat == seat:
            return prediction
    raise IllegalAction(f"you have no prediction Q{prediction_id}")


def _check_preregister(ctx: Ctx, seat: int, prediction: Prediction) -> None:
    r = ctx.state.researcher(seat)
    mine = [p for p in ctx.state.predictions if p.seat == seat and p.preregistered and p.id != prediction.id]
    if len(mine) + 1 > r.allocated(Task.DATA_COLLECTION):
        raise IllegalAction(
            f"you can preregister at most {r.allocated(Task.DATA_COLLECTION)} prediction(s) "
            "(staff on data collection)"
        )
    if any(p.inputs == prediction.inputs and p.outcomes == prediction.outcomes for p in mine):
        raise IllegalAction("you already preregistered a prediction based on this theory (specification 5.7)")


def make_prediction(ctx: Ctx, action: MakePrediction) -> None:
    state, seat = ctx.state, action.seat
    if state.researcher(seat).allocated(Task.DATA_COLLECTION) < 1:
        raise IllegalAction("making predictions needs at least one staff member on data collection")
    try:
        paper = state.paper(action.theory)
    except KeyError:
        raise IllegalAction(f"T{action.theory} is not a published theory") from None
    if paper.kind != "theory":
        raise IllegalAction(f"M{action.theory} is a method, not a theory")
    if not ctx.usable_by(paper, seat):
        raise IllegalAction(f"T{paper.id} is Fresh out of print: only its author can use it")
    if not 0 <= action.probe < len(state.probes):
        raise IllegalAction(f"there is no Probe P{action.probe + 1}")
    if mismatch(paper.idea.inputs, state.probes[action.probe].readings):
        raise IllegalAction(f"T{paper.id} mismatches the readings of P{action.probe + 1}")
    preregister = action.preregister or state.period == "crisis"
    prediction = Prediction(
        id=state.new_id(),
        round=state.round,
        seat=seat,
        probe=action.probe,
        theory=paper.id,
        inputs=dict(paper.idea.inputs),
        outcomes=dict(paper.idea.outcomes),
        preregistered=preregister,
    )
    if preregister:
        _check_preregister(ctx, seat, prediction)
    state.predictions.append(prediction)
    ctx.log(
        "prediction",
        f"Q{prediction.id}: T{paper.id} on P{action.probe + 1}{' (preregistered)' if preregister else ''}",
        visible_to=[seat],
    )


def cancel_prediction(ctx: Ctx, action: CancelPrediction) -> None:
    prediction = _own(ctx, action.seat, action.prediction)
    ctx.state.predictions.remove(prediction)


def set_preregistered(ctx: Ctx, action: SetPreregistered) -> None:
    prediction = _own(ctx, action.seat, action.prediction)
    if not action.preregister and ctx.state.period == "crisis":
        raise IllegalAction("during the Crisis period all predictions must be preregistered")
    if action.preregister and not prediction.preregistered:
        _check_preregister(ctx, action.seat, prediction)
    prediction.preregistered = action.preregister


# Preregistration pruning ---------------------------------------------------------------------
def cited_theory(ctx: Ctx, prediction: Prediction) -> int:
    """The cited theory among identical published theories (Preregistration pruning; 5.7)."""
    state = ctx.state
    order = state.turn_order()
    candidates = [
        p
        for p in state.published
        if p.kind == "theory"
        and p.idea.inputs == prediction.inputs
        and p.idea.outcomes == prediction.outcomes
        and ctx.usable_by(p, prediction.seat)
    ]
    own = [p for p in candidates if p.author == prediction.seat]
    if own:
        candidates = own
    candidates.sort(
        key=lambda p: (p.nobel, state.researcher(p.author).credit, p.round, order.index(p.author), p.id)
    )
    return candidates[0].id


def _prune(ctx: Ctx, predictions: list[Prediction], step: int) -> None:
    """Discard revealed predictions based on the same theory (Preregistration pruning)."""
    order = ctx.state.turn_order()
    by_theory: dict[int, list[Prediction]] = {}
    for prediction in predictions:
        prediction.revealed = True
        prediction.reveal_step = step
        by_theory.setdefault(prediction.cited, []).append(prediction)
    for theory, group in by_theory.items():
        group.sort(key=lambda p: (order.index(p.seat), p.probe, p.id))
        group[0].status = "revealed"
        ctx.state.paper(theory).sideways = True
        for loser in group[1:]:
            loser.status = "pruned"
            ctx.log(
                "pruned",
                f"{ctx.name(loser.seat)}'s prediction Q{loser.id} on T{theory} is discarded "
                f"({ctx.name(group[0].seat)} is earlier in turn order)",
            )
            loser.author = ctx.state.paper(theory).author
            loser.author_credit_change = ctx.settings.citation_reward
            ctx.credit(loser.author, loser.author_credit_change, f"T{theory} cited")


def _public_prediction(ctx: Ctx, p: Prediction) -> str:
    inputs = ", ".join(f"{k}={v}" for k, v in p.inputs.items())
    outcomes = ", ".join(f"{k}={v}" for k, v in p.outcomes.items())
    return f"{ctx.name(p.seat)}: Q{p.id} T{p.cited} on P{p.probe + 1} ({inputs} -> {outcomes})"


def finish_prediction(ctx: Ctx) -> None:
    state = ctx.state
    for prediction in state.predictions:
        prediction.cited = cited_theory(ctx, prediction)
    for seat in state.turn_order():
        mine = [p for p in state.predictions if p.seat == seat]
        hidden = [f"P{p.probe + 1}" for p in mine if not p.preregistered]
        if mine:
            ctx.log(
                "shield",
                f"{ctx.name(seat)}: {sum(p.preregistered for p in mine)} preregistered, "
                f"{len(hidden)} hidden prediction(s){' on ' + ', '.join(hidden) if hidden else ''}",
            )
    preregistered = [p for p in state.predictions if p.preregistered]
    for p in preregistered:
        ctx.log("preregistered", "Preregistered: " + _public_prediction(ctx, p), seat=p.seat, prediction=p.id)
    _prune(ctx, preregistered, step=1)
    for probe in state.probes:
        probe.outcomes_revealed = True
        shown = ", ".join(f"{k}={c.state}" for k, c in probe.outcomes.items())
        ctx.log("outcomes", f"P{probe.index + 1} outcomes: {shown}", probe=probe.index, outcomes={k: c.state for k, c in probe.outcomes.items()})
    for prediction in state.predictions:
        prediction.success = _success(ctx, prediction)  # hidden ones too, for the debrief


# Outcome and Prediction Reveal -------------------------------------------------------------------
def _success(ctx: Ctx, prediction: Prediction) -> bool:
    probe = ctx.state.probes[prediction.probe]
    return all(probe.outcomes[var].state == value for var, value in prediction.outcomes.items())


def _capacity(ctx: Ctx, seat: int) -> int:
    staff = ctx.state.researcher(seat).allocated(Task.DATA_COLLECTION)
    return staff - sum(1 for p in ctx.state.predictions if p.seat == seat and p.preregistered)


def _preregistered_theories(ctx: Ctx) -> set[int]:
    return {p.cited for p in ctx.state.predictions if p.preregistered}


def _revealable(ctx: Ctx, seat: int) -> list[Prediction]:
    blocked = _preregistered_theories(ctx)
    return [p for p in ctx.state.predictions if p.seat == seat and not p.preregistered and p.cited not in blocked]


def start_reveal(ctx: Ctx) -> None:
    state = ctx.state
    state.waiting = [seat for seat in state.turn_order() if _capacity(ctx, seat) > 0 and _revealable(ctx, seat)]


def reveal_prediction(ctx: Ctx, action: RevealPrediction) -> None:
    seat = action.seat
    prediction = _own(ctx, seat, action.prediction)
    if not action.reveal:
        if not prediction.preregistered:
            prediction.revealed = False
        return
    if prediction.preregistered:
        raise IllegalAction("preregistered predictions are revealed already")
    if prediction not in _revealable(ctx, seat):
        raise IllegalAction("a preregistered prediction is based on the same theory")
    chosen = [p for p in ctx.state.predictions if p.seat == seat and not p.preregistered and p.revealed]
    if prediction in chosen:
        return
    if len(chosen) >= _capacity(ctx, seat):
        raise IllegalAction(f"you can reveal at most {_capacity(ctx, seat)} more prediction(s)")
    if any(p.cited == prediction.cited for p in chosen):
        raise IllegalAction("you already reveal a prediction based on this theory (specification 5.7)")
    if ctx.state.researcher(seat).credit == 0 and not _success(ctx, prediction):
        raise IllegalAction("at 0 academic credit you cannot reveal a failed non-preregistered prediction")
    prediction.revealed = True


def check_commit_reveal(ctx: Ctx, seat: int) -> None:
    if ctx.state.researcher(seat).credit != 0:
        return
    chosen = [p for p in ctx.state.predictions if p.seat == seat and not p.preregistered and p.revealed]
    if len(chosen) >= _capacity(ctx, seat):
        return
    theories = {p.cited for p in chosen}
    if any(p.cited not in theories and _success(ctx, p) for p in _revealable(ctx, seat) if not p.revealed):
        raise IllegalAction("at 0 academic credit you must use every staff member that can still be used")


def finish_reveal(ctx: Ctx) -> None:
    state = ctx.state
    newly = [p for p in state.predictions if not p.preregistered and p.revealed]
    for p in newly:
        ctx.log("revealed", "Revealed: " + _public_prediction(ctx, p), seat=p.seat, prediction=p.id)
    _prune(ctx, newly, step=2)
    for seat in state.turn_order():
        r = state.researcher(seat)
        # As many staff are used as predictions revealed, pruned ones included.
        r.used[Task.DATA_COLLECTION] = sum(1 for p in state.predictions if p.seat == seat and p.revealed)


# Scoring predictions ---------------------------------------------------------------------------
def _scoring_groups(ctx: Ctx) -> list[list[Prediction]]:
    """Revealed predictions in scoring order, grouped by (step, researcher, Probe)."""
    state = ctx.state
    order = state.turn_order()
    alive = [p for p in state.predictions if p.status == "revealed"]
    alive.sort(key=lambda p: (p.reveal_step, order.index(p.seat), p.probe, p.id))
    groups: list[list[Prediction]] = []
    for p in alive:
        if groups and (groups[-1][0].reveal_step, groups[-1][0].seat, groups[-1][0].probe) == (
            p.reveal_step,
            p.seat,
            p.probe,
        ):
            groups[-1].append(p)
        else:
            groups.append([p])
    return groups


def _would_win_nobel(ctx: Ctx, p: Prediction) -> bool:
    return (
        ctx.state.period == "calm"
        and _success(ctx, p)
        and ctx.state.paper(p.cited).nobel + 1 >= ctx.settings.nobel_condition
    )


def _order_choices(ctx: Ctx) -> dict[int, list[list[Prediction]]]:
    """Groups whose order decides who wins the Nobel Prize: the predictor chooses the order."""
    choices: dict[int, list[list[Prediction]]] = {}
    for group in _scoring_groups(ctx):
        winners = {ctx.state.paper(p.cited).author for p in group if _would_win_nobel(ctx, p)}
        if len(winners) > 1:
            choices.setdefault(group[0].seat, []).append(group)
    return choices


def start_scoring_order(ctx: Ctx) -> None:
    state = ctx.state
    choices = _order_choices(ctx)
    state.waiting = [seat for seat in state.turn_order() if seat in choices]
    for seat in state.waiting:
        state.pending[seat].scoring_order = None


def order_predictions(ctx: Ctx, action: OrderPredictions) -> None:
    groups = _order_choices(ctx).get(action.seat, [])
    expected = sorted(p.id for g in groups for p in g)
    if sorted(action.order) != expected:
        raise IllegalAction(f"order exactly these predictions: {', '.join(f'Q{i}' for i in expected)}")
    ctx.state.pending[action.seat].scoring_order = list(action.order)


def check_commit_order(ctx: Ctx, seat: int) -> None:
    if ctx.state.pending[seat].scoring_order is None:
        raise IllegalAction("choose the scoring order first")


def finish_scoring(ctx: Ctx) -> None:
    missed: list[int] = []
    _score_round(ctx, missed)
    ctx.state.prediction_report = _prediction_report(ctx, missed)


def _prediction_report(ctx: Ctx, missed: list[int]) -> dict | None:
    """What the round's predictions did, for the web client's report (specification 7.4). Only
    revealed predictions, so all of it is public. None when there is nothing to report."""
    state = ctx.state
    shown = [p for p in state.prediction_log + state.predictions
             if p.round == state.round and p.status in ("scored", "pruned", "revealed")]
    if not shown and not missed:
        return None
    shown.sort(key=lambda p: (p.seat, p.probe, p.id))
    outcome = {"pruned": lambda p: "pruned", "revealed": lambda p: "unscored",
               "scored": lambda p: "success" if p.success else "failed"}
    return {
        "round": state.round,
        "crisis": state.period == "crisis",
        "missed": missed,
        "unsuccessful": state.unsuccessful_predictions,
        "crisis_condition": ctx.settings.crisis_condition,
        "predictions": [
            {"id": p.id, "seat": p.seat, "probe": p.probe, "theory": p.cited, "inputs": p.inputs, "outcomes": p.outcomes,
             "preregistered": p.preregistered, "outcome": outcome[p.status](p), "credit": p.credit_change,
             "author": p.author, "author_credit": p.author_credit_change, "patent": p.patent,
             "patent_holder": p.patent_holder, "nobel": p.won_nobel}
            for p in shown
        ],
    }


def _score_round(ctx: Ctx, missed: list[int]) -> None:
    state = ctx.state
    for group in _scoring_groups(ctx):
        chosen = state.pending[group[0].seat].scoring_order
        if chosen:
            group.sort(key=lambda p: chosen.index(p.id) if p.id in chosen else p.id)
        for prediction in group:
            score(ctx, prediction)
            if state.result:
                return
    for seat in state.turn_order():
        state.pending[seat].scoring_order = None
    if state.period == "crisis":
        for probe in state.probes:
            if not any(p.probe == probe.index and p.status == "scored" for p in state.predictions):
                state.unsuccessful_predictions += 1
                missed.append(probe.index)
                ctx.log("crisis_miss", f"No prediction on P{probe.index + 1}: one unsuccessful prediction", probe=probe.index)
                if check_crisis_crash(ctx):
                    return
    record_observations(ctx)


def credit_changes(s: Settings, crisis: bool, inputs: int, outcomes: int, preregistered: bool, success: bool) -> tuple[int, int]:
    """Academic credit for the researcher who predicted and for the cited theory's author
    (Scoring predictions)."""
    if success:
        base = inputs + (s.crisis_pred_base_bonus if crisis else 0)
        return (base * outcomes * (2 if preregistered else 1),
                s.citation_reward + (s.crisis_pred_citation_reward_bonus if crisis else 0))
    if crisis:
        return s.failed_prereg_pred_ac_crisis, s.crisis_failed_pred_citation_penalty
    return s.failed_prereg_pred_ac if preregistered else s.failed_non_prereg_pred_ac, 0


def score(ctx: Ctx, p: Prediction) -> None:
    state, s = ctx.state, ctx.settings
    paper = state.paper(p.cited)
    success = _success(ctx, p)
    p.success = success
    p.status = "scored"
    crisis = state.period == "crisis"
    ctx.log("scored", f"Q{p.id} ({ctx.name(p.seat)}, T{paper.id} on P{p.probe + 1}): {'success' if success else 'failed'}")
    gained, author_gained = credit_changes(s, crisis, len(p.inputs), len(p.outcomes), p.preregistered, success)
    p.author, p.credit_change, p.author_credit_change = paper.author, gained, author_gained
    if success:
        ctx.credit(p.seat, gained, "successful prediction")
        ctx.credit(paper.author, author_gained, f"T{paper.id} cited")
        # Funding > Patents: one patent per theory, kept by the first successful predictor.
        if paper.patents:
            p.patent, p.patent_holder = "held", paper.patents[0]
        else:
            p.patent, p.patent_holder = "new", p.seat
            paper.patents = [p.seat]
            ctx.log("patent", f"{ctx.name(p.seat)} gets a patent on T{paper.id}", seat=p.seat, theory=paper.id)
        if not crisis:
            paper.nobel += 1
            paper.retraction = 0
            if paper.nobel >= s.nobel_condition:
                p.won_nobel = True
                ctx.log("nobel", f"T{paper.id} reaches {paper.nobel} on its Nobel Prize counter")
                end_game(ctx, "nobel", [paper.author], theory=paper.id)
        return
    if crisis:
        ctx.credit(p.seat, gained, "failed prediction in the Crisis")
        ctx.credit(paper.author, author_gained, f"T{paper.id} failed in the Crisis")
        state.unsuccessful_predictions += 1
        check_crisis_crash(ctx)
        return
    ctx.credit(p.seat, gained, "failed prediction")
    paper.nobel = 0
    paper.retraction += 1
    if paper.retraction >= s.retraction_threshold:
        retract(ctx, paper)


def retract(ctx: Ctx, paper: Paper) -> None:
    """Retraction: the theory is unpublished and returned to its author."""
    state = ctx.state
    state.published.remove(paper)
    idea = Idea(id=state.new_id(), kind="theory", inputs=dict(paper.idea.inputs), outcomes=dict(paper.idea.outcomes))
    state.researcher(paper.author).ideas.append(idea)
    for entry in state.paper_log:
        if entry.paper == paper.id:
            entry.retracted_round = state.round
    ctx.log("retraction", f"T{paper.id} is retracted and returned to {ctx.name(paper.author)}", theory=paper.id)
    ctx.credit(paper.author, ctx.settings.retraction_ac_penalty, f"T{paper.id} retracted")


# Recording observations -------------------------------------------------------------------------
def record_observations(ctx: Ctx) -> None:
    state = ctx.state
    for probe in state.probes:
        _clear_probe(ctx, probe)
    for p in state.predictions:
        if p.status == "hidden":
            p.status = "discarded"
        p.readings = {v: c.state for v, c in state.probes[p.probe].readings.items()}
    state.prediction_log += state.predictions
    state.predictions = []


def _clear_probe(ctx: Ctx, probe: Probe) -> None:
    visible = [probe.readings[v] for v in ctx.world.input_ids] + [probe.outcomes[v] for v in ctx.world.outcome_ids]
    hidden = [c for v, c in stack_cards(ctx, probe.stack).items() if c not in visible]
    if probe.probe_time is not None:
        observation = Observation(id=ctx.state.new_id(), probe=probe.index, round=ctx.state.round, cards=visible)
        ctx.state.researcher(probe.probe_time).fresh.observations.append(observation)
        ctx.log(
            "observation",
            f"{ctx.name(probe.probe_time)} records P{probe.index + 1} as O{observation.id}",
            seat=probe.probe_time,
        )
    else:
        for card in visible:
            ctx.discard_card(card)
    for card in hidden:
        ctx.discard_card(card)
    for parameter, noise in probe.unrevealed_noise.items():
        ctx.state.input_discards[parameter].extend(noise)
    probe.unrevealed_noise = {}

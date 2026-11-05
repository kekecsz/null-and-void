"""Generating a World Table from a scenario's effect model (specification sections 4.2 and 4.3).

Randomness: one ``random.Random(seed)`` per try, used in a fixed order (main effects, then
interactions, then row outcomes), so the same scenario and seed always give the same world.
"""

import itertools
import math
import random
from collections import Counter
from dataclasses import dataclass, replace

from nv_world.scenario import Scenario
from nv_world.screening import CRITERIA, Row, ScreeningReport, score_all, screen


@dataclass(frozen=True)
class MainEffect:
    outcome: str
    outcome_state: str
    input: str
    input_state: str
    effect: str  # a signed main_effect_urn entry, e.g. "+large"


@dataclass(frozen=True)
class Interaction:
    outcome: str
    outcome_state: str
    input_a: str
    state_a: str
    input_b: str
    state_b: str
    size: str  # a key of effect_sizes_logit
    sign: int  # +1 or -1


@dataclass
class World:
    scenario_id: str
    yaml_hash: str
    requested_seed: int
    seed: int
    tries: int
    main_effects: list[MainEffect]
    interactions: list[Interaction]
    rows: list[Row]
    screening: ScreeningReport | None = None


class GenerationFailed(Exception):
    """No world passed the acceptance criteria within max_generation_tries."""

    def __init__(self, tries: int, failure_counts: dict[str, int]):
        self.tries = tries
        self.failure_counts = failure_counts
        detail = ", ".join(f"{name}: {count}" for name, count in sorted(failure_counts.items()))
        super().__init__(f"no acceptable world in {tries} tries (failed criteria: {detail})")


def _outcome_states(scenario: Scenario) -> list[tuple[str, str]]:
    """World outcome states that receive effects (all but the reference state, if there is one)."""
    skip = 1 if scenario.effect_model.reference_state_per_outcome else 0
    return [(o.id, s) for o in scenario.world_outcomes for s in o.states[skip:]]


def _assign_main_effects(scenario: Scenario, rng: random.Random) -> list[MainEffect]:
    input_states = [(p.id, s) for p in scenario.input_parameters for s in p.states]
    urn = scenario.effect_model.main_effect_urn
    effects = []
    for outcome, outcome_state in _outcome_states(scenario):
        padded = list(urn) + [None] * (len(input_states) - len(urn))
        rng.shuffle(padded)
        for (parameter, state), effect in zip(input_states, padded):
            if effect is not None:
                effects.append(MainEffect(outcome, outcome_state, parameter, state, effect))
    return effects


def _assign_interactions(scenario: Scenario, rng: random.Random) -> list[Interaction]:
    model = scenario.effect_model
    parameters = scenario.input_parameters
    pairs = [
        ((a.id, sa), (b.id, sb))
        for i, a in enumerate(parameters)
        for b in parameters[i + 1 :]
        for sa in a.states
        for sb in b.states
    ]
    outcome_states = _outcome_states(scenario)
    taken: Counter = Counter()
    interactions = []
    for size in model.interactions:
        eligible = [os for os in outcome_states if taken[os] < model.max_interactions_per_outcome_state]
        outcome, outcome_state = rng.choice(eligible)
        (input_a, state_a), (input_b, state_b) = rng.choice(pairs)
        if model.interaction_sign == "positive":
            sign = 1
        elif model.interaction_sign == "negative":
            sign = -1
        else:
            sign = rng.choice((1, -1))
        taken[(outcome, outcome_state)] += 1
        interactions.append(Interaction(outcome, outcome_state, input_a, state_a, input_b, state_b, size, sign))
    return interactions


def _effect_value(scenario: Scenario, signed_size: str) -> float:
    sign = -1.0 if signed_size.startswith("-") else 1.0
    return sign * scenario.effect_model.effect_sizes_logit[signed_size[1:]]


def outcome_scores(
    scenario: Scenario, main_effects: list[MainEffect], interactions: list[Interaction], inputs: dict[str, str]
) -> dict[str, dict[str, float]]:
    """Score of every world outcome state for one input combination (step 3)."""
    sizes = scenario.effect_model.effect_sizes_logit
    scores = {o.id: dict.fromkeys(o.states, 0.0) for o in scenario.world_outcomes}
    for effect in main_effects:
        if inputs[effect.input] == effect.input_state:
            scores[effect.outcome][effect.outcome_state] += _effect_value(scenario, effect.effect)
    for inter in interactions:
        if inputs[inter.input_a] == inter.state_a and inputs[inter.input_b] == inter.state_b:
            scores[inter.outcome][inter.outcome_state] += inter.sign * sizes[inter.size]
    return scores


def softmax(scores: dict[str, float]) -> dict[str, float]:
    top = max(scores.values())
    exps = {state: math.exp(score - top) for state, score in scores.items()}
    total = sum(exps.values())
    return {state: value / total for state, value in exps.items()}


def _draw(probabilities: dict[str, float], rng: random.Random) -> str:
    u = rng.random()
    cumulative = 0.0
    for state, p in probabilities.items():
        cumulative += p
        if u < cumulative:
            return state
    return next(reversed(probabilities))  # guards against rounding when u is just below 1


def build_world(scenario: Scenario, seed: int) -> World:
    """One generation try (specification section 4.2), without screening."""
    rng = random.Random(seed)
    main_effects = _assign_main_effects(scenario, rng)
    interactions = _assign_interactions(scenario, rng)
    parameters = scenario.input_parameters
    rows = []
    for combo in itertools.product(*(p.states for p in parameters)):
        inputs = {p.id: s for p, s in zip(parameters, combo)}
        scores = outcome_scores(scenario, main_effects, interactions, inputs)
        probabilities = {outcome: softmax(s) for outcome, s in scores.items()}
        # outcome_realisation (section 4.2 step 3); the schema accepts only draw_once.
        outcomes = {outcome: _draw(p, rng) for outcome, p in probabilities.items()}
        rows.append(Row(inputs, outcomes, probabilities))
    return World(
        scenario_id=scenario.id,
        yaml_hash=scenario.yaml_hash,
        requested_seed=seed,
        seed=seed,
        tries=1,
        main_effects=main_effects,
        interactions=interactions,
        rows=rows,
    )


def generate_world(scenario: Scenario, seed: int) -> World:
    """Generate and screen worlds with seed, seed + 1, ... until one passes (section 4.3)."""
    max_tries = scenario.acceptance_criteria.max_generation_tries
    failures: Counter = Counter(dict.fromkeys(CRITERIA, 0))
    for attempt in range(max_tries):
        world = build_world(scenario, seed + attempt)
        report = screen(scenario, world.rows, score_all(scenario, world.rows))
        if report.passed:
            return replace(world, requested_seed=seed, tries=attempt + 1, screening=report)
        failures.update(report.failed)
    raise GenerationFailed(max_tries, dict(failures))

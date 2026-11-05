"""Screening a World Table against the scenario's acceptance criteria (specification section 4.3).

All shares are exact fractions. Internally, row weights are scaled to whole numbers by a common
denominator, so sums stay in fast integer arithmetic and every share is an exact integer ratio.
"""

import itertools
import math
from collections import defaultdict
from dataclasses import dataclass, field
from fractions import Fraction

from nv_world.scenario import Scenario


@dataclass
class Row:
    """One World Table row: an input combination and its realised world outcome states."""

    inputs: dict[str, str]
    outcomes: dict[str, str]
    probabilities: dict[str, dict[str, float]] | None = None


class Theory:
    """A theory (section 4.3); states keyed by variable id."""

    __slots__ = ("inputs", "outcomes", "_key")

    def __init__(self, inputs: dict[str, str], outcomes: dict[str, str]):
        self.inputs = dict(inputs)
        self.outcomes = dict(outcomes)
        self._key = (tuple(sorted(self.inputs.items())), tuple(sorted(self.outcomes.items())))

    @property
    def n_inputs(self) -> int:
        return len(self.inputs)

    @property
    def n_outcomes(self) -> int:
        return len(self.outcomes)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Theory) and self._key == other._key

    def __hash__(self) -> int:
        return hash(self._key)

    def __repr__(self) -> str:
        return f"Theory({self.inputs!r}, {self.outcomes!r})"

    def label(self) -> str:
        left = " & ".join(f"{k}={v}" for k, v in self.inputs.items())
        right = " & ".join(f"{k}={v}" for k, v in self.outcomes.items())
        return f"{left} -> {right}"


# Names of the acceptance criteria, as they appear in ScreeningReport.failed.
CRITERIA = ("max_base_rate", "max_one_input_theory_accuracy", "nobel_grade.min_count", "nobel_grade.max_count")


@dataclass(frozen=True)
class TheoryScore:
    theory: Theory
    coverage: Fraction
    accuracy: Fraction


@dataclass
class ScreeningReport:
    base_rates: dict[str, dict[str, Fraction]]
    best_accuracy_by_inputs: dict[int, Fraction]
    nobel_grade: list[TheoryScore]
    nobel_counts: dict[str, int]
    failed: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failed


def _choices(variables) -> list[dict[str, str]]:
    """The state choices section 4.3 enumerates, in a stable order."""
    options = [[None, *v.states] for v in variables]
    result = []
    for combo in itertools.product(*options):
        chosen = {v.id: s for v, s in zip(variables, combo) if s is not None}
        if chosen:
            result.append(chosen)
    return result


def enumerate_theories(scenario: Scenario) -> list[Theory]:
    """Every possible theory (specification section 4.3)."""
    input_choices = _choices(scenario.input_parameters)
    outcome_choices = _choices(scenario.world_outcomes)
    return [Theory(i, o) for i in input_choices for o in outcome_choices]


def check_rows(scenario: Scenario, rows: list[Row]) -> None:
    """Raise ValueError naming the first id or state in ``rows`` that the scenario does not define."""
    for kind, variables in (("inputs", scenario.input_parameters), ("outcomes", scenario.world_outcomes)):
        expected = {v.id: v.states for v in variables}
        for number, row in enumerate(rows):
            values = getattr(row, kind)
            if set(values) != set(expected):
                raise ValueError(
                    f"row {number} {kind} have ids {sorted(values)}, the scenario has {sorted(expected)}"
                )
            for variable_id, state in values.items():
                if state not in expected[variable_id]:
                    raise ValueError(f"row {number}: {state!r} is not a state of {variable_id}")


def row_weight(scenario: Scenario, row: Row) -> Fraction:
    """Product of the weights of the row's input states."""
    weight = Fraction(1)
    for parameter in scenario.input_parameters:
        weight *= parameter.weights[parameter.states.index(row.inputs[parameter.id])]
    return weight


def _integer_weights(scenario: Scenario, rows: list[Row]) -> list[int]:
    weights = [row_weight(scenario, row) for row in rows]
    scale = math.lcm(*(w.denominator for w in weights)) if weights else 1
    return [int(w * scale) for w in weights]


def _matches(row_values: dict[str, str], pattern: dict[str, str]) -> bool:
    return all(row_values.get(k) == v for k, v in pattern.items())


def _share(part: int, whole: int) -> Fraction:
    return Fraction(part, whole) if whole else Fraction(0)


def score_theory(scenario: Scenario, rows: list[Row], theory: Theory) -> TheoryScore:
    """Coverage and accuracy of one theory (straightforward version of score_all)."""
    weights = _integer_weights(scenario, rows)
    total = sum(weights)
    covered = correct = 0
    for row, weight in zip(rows, weights):
        if _matches(row.inputs, theory.inputs):
            covered += weight
            if _matches(row.outcomes, theory.outcomes):
                correct += weight
    return TheoryScore(theory, _share(covered, total), _share(correct, covered))


def score_all(scenario: Scenario, rows: list[Row]) -> list[TheoryScore]:
    """Coverage and accuracy of every theory, in enumerate_theories order."""
    weights = _integer_weights(scenario, rows)
    total = sum(weights)
    outcome_choices = _choices(scenario.world_outcomes)
    scores = []
    for inputs in _choices(scenario.input_parameters):
        # Weighted count of each realised outcome combination among the covered rows.
        joint: dict[tuple, int] = defaultdict(int)
        for row, weight in zip(rows, weights):
            if _matches(row.inputs, inputs):
                joint[tuple(sorted(row.outcomes.items()))] += weight
        covered = sum(joint.values())
        for outcomes in outcome_choices:
            correct = sum(w for combo, w in joint.items() if _matches(dict(combo), outcomes))
            scores.append(TheoryScore(Theory(inputs, outcomes), _share(covered, total), _share(correct, covered)))
    return scores


def base_rates(scenario: Scenario, rows: list[Row]) -> dict[str, dict[str, Fraction]]:
    """Weighted share of rows in which each world outcome state is realised."""
    weights = _integer_weights(scenario, rows)
    total = sum(weights)
    rates = {}
    for outcome in scenario.world_outcomes:
        counts = dict.fromkeys(outcome.states, 0)
        for row, weight in zip(rows, weights):
            counts[row.outcomes[outcome.id]] += weight
        rates[outcome.id] = {state: _share(count, total) for state, count in counts.items()}
    return rates


def nobel_counts(nobel_grade: list[TheoryScore]) -> dict[str, int]:
    """The three counts of specification section 4.3."""
    theories = [s.theory for s in nobel_grade]
    patterns = {tuple(sorted(t.inputs.items())) for t in theories}

    def implied(t: Theory) -> bool:
        return any(
            other.inputs == t.inputs
            and other.n_outcomes > t.n_outcomes
            and all(other.outcomes.get(k) == v for k, v in t.outcomes.items())
            for other in theories
        )

    return {
        "theories": len(theories),
        "input_patterns": len(patterns),
        "maximal_theories": sum(1 for t in theories if not implied(t)),
    }


def is_nobel_grade(scenario: Scenario, score: TheoryScore) -> bool:
    criteria = scenario.acceptance_criteria.nobel_grade
    return score.theory.n_inputs <= criteria.max_input_parameters and score.accuracy >= criteria.min_accuracy


def screen(scenario: Scenario, rows: list[Row], scores: list[TheoryScore] | None = None) -> ScreeningReport:
    """Base rates, best accuracies, Nobel-grade theories and the acceptance check."""
    criteria = scenario.acceptance_criteria
    scores = score_all(scenario, rows) if scores is None else scores
    rates = base_rates(scenario, rows)

    best: dict[int, Fraction] = {}
    for score in scores:
        n = score.theory.n_inputs
        if n not in best or score.accuracy > best[n]:
            best[n] = score.accuracy

    nobel = [s for s in scores if is_nobel_grade(scenario, s)]
    counts = nobel_counts(nobel)

    failed = []
    if any(rate > criteria.max_base_rate for states in rates.values() for rate in states.values()):
        failed.append("max_base_rate")
    if best.get(1, Fraction(0)) > criteria.max_one_input_theory_accuracy:
        failed.append("max_one_input_theory_accuracy")
    chosen = counts[criteria.nobel_grade.count]
    if chosen < criteria.nobel_grade.min_count:
        failed.append("nobel_grade.min_count")
    if chosen > criteria.nobel_grade.max_count:
        failed.append("nobel_grade.max_count")

    return ScreeningReport(
        base_rates=rates,
        best_accuracy_by_inputs=dict(sorted(best.items())),
        nobel_grade=nobel,
        nobel_counts=counts,
        failed=failed,
    )


def best_theories(scores: list[TheoryScore], n_inputs: int, top: int) -> list[TheoryScore]:
    """The ``top`` theories with ``n_inputs`` input parameters: accuracy, then coverage, then more outcomes."""
    candidates = [s for s in scores if s.theory.n_inputs == n_inputs]
    candidates.sort(key=lambda s: (-s.accuracy, -s.coverage, -s.theory.n_outcomes, s.theory.label()))
    return candidates[:top]

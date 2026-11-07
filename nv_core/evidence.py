"""The evidence tally of specification 9.4: how every possible theory fared on what a player saw.

A *case* for a theory is a Probe whose visible readings have no mismatch with the theory's inputs
(so a prediction with the theory would have been allowed there), or an experiment whose inputs
match the theory's inputs. The case is a *success* when the world outcomes match the theory's
outcomes. Blank readings never mismatch, as in the rulebook.

Used by the scripted bots; it only needs what a player may know, so it can also serve as a
player aid later.
"""

import math
from dataclasses import dataclass, field
from itertools import product
from typing import Iterable

Values = dict[str, str | None]
Key = tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]  # (inputs, outcomes), sorted


def theory_key(inputs: dict[str, str], outcomes: dict[str, str]) -> Key:
    return tuple(sorted(inputs.items())), tuple(sorted(outcomes.items()))


def wilson_lower(successes: int, n: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson interval (95% by default); 0 without cases."""
    if n == 0:
        return 0.0
    p = successes / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - spread) / (1 + z * z / n))


@dataclass(frozen=True)
class Case:
    """One thing seen: input readings (None = blank) and the world outcomes."""

    inputs: Values
    outcomes: dict[str, str]
    exact: bool = False  # an experiment: every input is known


@dataclass
class Tally:
    """Counts for every theory of a scenario. ``inputs``/``outcomes``: variable id -> states."""

    inputs: dict[str, list[str]]
    outcomes: dict[str, list[str]]
    cases: dict[tuple, int] = field(default_factory=dict)  # input pattern -> cases
    successes: dict[tuple, dict[tuple, int]] = field(default_factory=dict)  # input pattern -> outcome pattern -> n

    def __post_init__(self) -> None:
        self._in_vars = list(self.inputs)
        self._out_vars = list(self.outcomes)
        self.input_patterns = [
            p for p in product(*[[None, *self.inputs[v]] for v in self._in_vars]) if any(x is not None for x in p)
        ]
        self.outcome_patterns = [
            p for p in product(*[[None, *self.outcomes[v]] for v in self._out_vars]) if any(x is not None for x in p)
        ]

    # Building --------------------------------------------------------------------------------
    @classmethod
    def build(cls, inputs: dict[str, list[str]], outcomes: dict[str, list[str]], seen: Iterable[Case]) -> "Tally":
        tally = cls(inputs, outcomes)
        for case in seen:
            tally.add(case)
        return tally

    def add(self, case: Case) -> None:
        readings = tuple(case.inputs.get(v) for v in self._in_vars)
        result = tuple(case.outcomes.get(v) for v in self._out_vars)
        matching_outcomes = [
            op for op in self.outcome_patterns if all(x is None or x == y for x, y in zip(op, result))
        ]
        for ip in self.input_patterns:
            if any(x is not None and r is not None and x != r for x, r in zip(ip, readings)):
                continue  # a mismatch: not a case for this theory
            if case.exact and any(x is not None and r is None for x, r in zip(ip, readings)):
                continue
            self.cases[ip] = self.cases.get(ip, 0) + 1
            row = self.successes.setdefault(ip, {})
            for op in matching_outcomes:
                row[op] = row.get(op, 0) + 1

    # Reading ---------------------------------------------------------------------------------
    def _patterns(self, inputs: dict[str, str], outcomes: dict[str, str]) -> tuple[tuple, tuple]:
        return tuple(inputs.get(v) for v in self._in_vars), tuple(outcomes.get(v) for v in self._out_vars)

    def counts(self, inputs: dict[str, str], outcomes: dict[str, str]) -> tuple[int, int]:
        """(successes, cases) of a theory."""
        ip, op = self._patterns(inputs, outcomes)
        return self.successes.get(ip, {}).get(op, 0), self.cases.get(ip, 0)

    def seen(self, inputs: dict[str, str]) -> int:
        """Cases for these input states, whatever the outcomes."""
        return self.cases.get(self._patterns(inputs, {})[0], 0)

    def rate(self, inputs: dict[str, str], outcomes: dict[str, str]) -> float:
        """Estimated success rate, (successes + 1) / (cases + 2), so an unseen theory is at 1/2."""
        s, n = self.counts(inputs, outcomes)
        return (s + 1) / (n + 2)

    def lower(self, inputs: dict[str, str], outcomes: dict[str, str]) -> float:
        s, n = self.counts(inputs, outcomes)
        return wilson_lower(s, n)

    def theories(self) -> Iterable[tuple[dict[str, str], dict[str, str], int, int]]:
        """Every theory with at least one case: (inputs, outcomes, successes, cases)."""
        for ip, n in self.cases.items():
            inputs = {v: x for v, x in zip(self._in_vars, ip) if x is not None}
            for op, s in self.successes.get(ip, {}).items():
                yield inputs, {v: x for v, x in zip(self._out_vars, op) if x is not None}, s, n

    def confident(self, threshold: float) -> list[tuple[dict[str, str], dict[str, str], float]]:
        """Theories whose Wilson lower bound reaches ``threshold``: (inputs, outcomes, lower bound)."""
        return [(i, o, wilson_lower(s, n)) for i, o, s, n in self.theories() if wilson_lower(s, n) >= threshold]

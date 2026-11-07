"""Specification 9.4: the evidence tally (cases, successes, confidence)."""

import pytest

from nv_core.evidence import Case, Tally, theory_key, wilson_lower

INPUTS = {"IP1": ["a", "b"], "IP2": ["x", "y"]}
OUTCOMES = {"WO1": ["up", "down"]}


def test_wilson_lower_bound_examples_from_the_specification():
    assert wilson_lower(6, 6) == pytest.approx(0.61, abs=0.005)
    assert wilson_lower(10, 10) == pytest.approx(0.72, abs=0.005)
    assert wilson_lower(0, 0) == 0.0


def test_every_theory_with_at_least_one_input_and_one_outcome_is_counted():
    tally = Tally(INPUTS, OUTCOMES)
    assert len(tally.input_patterns) == 3 * 3 - 1
    assert len(tally.outcome_patterns) == 3 - 1


def test_blank_readings_never_mismatch_and_outcomes_decide_success():
    tally = Tally.build(
        INPUTS,
        OUTCOMES,
        [
            Case({"IP1": "a", "IP2": None}, {"WO1": "up"}),  # IP2 blank: a case for IP2=x and IP2=y theories
            Case({"IP1": "a", "IP2": "x"}, {"WO1": "down"}),
            Case({"IP1": "b", "IP2": "x"}, {"WO1": "up"}),
        ],
    )
    assert tally.counts({"IP1": "a"}, {"WO1": "up"}) == (1, 2)
    assert tally.counts({"IP1": "a", "IP2": "y"}, {"WO1": "up"}) == (1, 1)
    assert tally.counts({"IP2": "x"}, {"WO1": "up"}) == (2, 3)
    assert tally.seen({"IP1": "b"}) == 1
    assert tally.rate({"IP1": "b", "IP2": "y"}, {"WO1": "up"}) == 0.5  # never seen


def test_an_experiment_is_a_case_only_where_every_theory_input_is_known():
    tally = Tally.build(INPUTS, OUTCOMES, [Case({"IP1": "a", "IP2": "y"}, {"WO1": "up"}, exact=True)])
    assert tally.counts({"IP1": "a", "IP2": "y"}, {"WO1": "up"}) == (1, 1)
    assert tally.counts({"IP1": "a", "IP2": "x"}, {"WO1": "up"}) == (0, 0)


def test_confident_theories_reach_the_threshold():
    seen = [Case({"IP1": "a", "IP2": None}, {"WO1": "up"})] * 10 + [Case({"IP1": "b", "IP2": None}, {"WO1": "down"})] * 3
    tally = Tally.build(INPUTS, OUTCOMES, seen)
    confident = {theory_key(i, o) for i, o, _ in tally.confident(0.7)}
    assert theory_key({"IP1": "a"}, {"WO1": "up"}) in confident
    assert theory_key({"IP1": "b"}, {"WO1": "down"}) not in confident  # 3 of 3 is not enough

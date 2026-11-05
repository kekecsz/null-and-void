"""Specification section 4.3, "Screening", checked against hand-made worlds.

The worlds below are hand-made fixtures (tiny scenarios from conftest.py and hand-written
World Tables); every expected number is worked out by hand in the comments.
"""

import itertools
from fractions import Fraction as F

import pytest

from nv_world.generate import build_world
from nv_world.scenario import load_scenario
from nv_world.screening import Row, Theory, base_rates, enumerate_theories, score_theory, screen

from tests.world.conftest import (
    VENUS,
    screening_signature,
    tiny_data,
    two_outcome_data,
    venus_data,
    with_criteria,
    write_scenario,
)

# --- hand-made worlds --------------------------------------------------------------------
#
# Tiny scenario: IP1 colour [red, blue], IP2 shape [round, square, flat], WO1 result [hit, miss];
# the two-outcome variant adds WO2 tone [light, dark].
#
# World A (one outcome), rows in table order:
#   r1 red  round  -> hit      r4 blue round  -> miss
#   r2 red  square -> hit      r5 blue square -> miss
#   r3 red  flat   -> miss     r6 blue flat   -> hit
#
# World C (two outcomes):
#   r1 red  round  -> hit,  light     r4 blue round  -> miss, light
#   r2 red  square -> hit,  light     r5 blue square -> miss, dark
#   r3 red  flat   -> miss, dark      r6 blue flat   -> hit,  dark

COMBOS = [("red", "round"), ("red", "square"), ("red", "flat"),
          ("blue", "round"), ("blue", "square"), ("blue", "flat")]
WORLD_A = ["hit", "hit", "miss", "miss", "miss", "hit"]
# World A2: a second one-outcome table, used where weights change the base rates.
WORLD_A2 = ["hit", "hit", "miss", "hit", "miss", "miss"]
WORLD_C = [("hit", "light"), ("hit", "light"), ("miss", "dark"),
           ("miss", "light"), ("miss", "dark"), ("hit", "dark")]


def rows_a(outcomes=WORLD_A):
    return [Row(inputs={"IP1": c, "IP2": s}, outcomes={"WO1": o}) for (c, s), o in zip(COMBOS, outcomes)]


def rows_c():
    return [Row(inputs={"IP1": c, "IP2": s}, outcomes={"WO1": o1, "WO2": o2})
            for (c, s), (o1, o2) in zip(COMBOS, WORLD_C)]


def T(inputs: dict, outcomes: dict) -> Theory:
    return Theory(inputs=inputs, outcomes=outcomes)


def load(tmp_path, data, name="scenario.md"):
    return load_scenario(write_scenario(tmp_path, data, name))


def weighted(data, weights=(2, 1, 1)):
    """IP2 weights [2, 1, 1] -> round 1/2, square 1/4, flat 1/4; IP1 stays 1/2 each.

    Row weights: red/round 1/4, red/square 1/8, red/flat 1/8, and the same for blue.
    """
    data["input_parameters"][1]["weights"] = list(weights)
    return data


def strict_counts_criteria(data, *, max_inputs=2, min_accuracy=0.9, count="theories",
                           min_count=0, max_count=1000000):
    """Criteria where only the Nobel-grade definition matters (base-rate and one-input limits at 1)."""
    return with_criteria(
        data, max_base_rate=1.0, max_one_input_theory_accuracy=1.0,
        nobel_min_accuracy=min_accuracy, nobel_max_input_parameters=max_inputs,
        nobel_count=count, nobel_min_count=min_count, nobel_max_count=max_count,
    )


# --- listing theories --------------------------------------------------------------------

def _expected_theories(data):
    def choices(variables):
        options = [[None] + v["states"] for v in variables]
        for combo in itertools.product(*options):
            chosen = {v["id"]: s for v, s in zip(variables, combo) if s is not None}
            if chosen:
                yield chosen
    return {
        (frozenset(i.items()), frozenset(o.items()))
        for i in choices(data["input_parameters"])
        for o in choices(data["world_outcomes"])
    }


def _theory_count(data):
    # Each parameter contributes "no state" or one of its states; the empty choice is excluded.
    inputs = 1
    for p in data["input_parameters"]:
        inputs *= len(p["states"]) + 1
    outcomes = 1
    for o in data["world_outcomes"]:
        outcomes *= len(o["states"]) + 1
    return (inputs - 1) * (outcomes - 1)


@pytest.mark.parametrize("make, expected", [(tiny_data, 22), (two_outcome_data, 88)],
                         ids=["one outcome", "two outcomes"])
def test_every_possible_theory_is_listed(tmp_path, make, expected):
    """4.3 Screening: every non-empty choice of inputs combined with every non-empty choice of outcomes."""
    # One outcome: (3*4 - 1) * (3 - 1) = 22.  Two outcomes: (3*4 - 1) * (3*3 - 1) = 88.
    data = make()
    assert _theory_count(data) == expected
    theories = enumerate_theories(load(tmp_path, data))
    assert len(theories) == expected
    listed = {(frozenset(t.inputs.items()), frozenset(t.outcomes.items())) for t in theories}
    assert len(listed) == expected, "a theory is listed twice"
    assert listed == _expected_theories(data)


def test_venus_theory_count():
    """4.3 Screening: the number of theories follows from the scenario's states."""
    theories = enumerate_theories(load_scenario(VENUS))
    assert len(theories) == _theory_count(venus_data())
    assert len(set(theories)) == len(theories)


def test_theories_compare_by_content():
    """4.3 Screening: a theory is its choice of states."""
    a = T({"IP1": "red", "IP2": "round"}, {"WO1": "hit"})
    b = T({"IP2": "round", "IP1": "red"}, {"WO1": "hit"})
    assert a == b
    assert hash(a) == hash(b)
    assert a != T({"IP1": "red"}, {"WO1": "hit"})


# --- coverage and accuracy -----------------------------------------------------------------

# World A, unweighted (each row 1/6).
A_SCORES = [
    # theory inputs, theory outcomes, coverage, accuracy
    ({"IP1": "red"}, {"WO1": "hit"}, F(1, 2), F(2, 3)),       # r1 r2 r3: hit in r1 r2
    ({"IP1": "red"}, {"WO1": "miss"}, F(1, 2), F(1, 3)),      # miss in r3
    ({"IP1": "blue"}, {"WO1": "miss"}, F(1, 2), F(2, 3)),     # r4 r5 r6: miss in r4 r5
    ({"IP2": "round"}, {"WO1": "hit"}, F(1, 3), F(1, 2)),     # r1 r4: hit in r1
    ({"IP2": "flat"}, {"WO1": "miss"}, F(1, 3), F(1, 2)),     # r3 r6: miss in r3
    ({"IP1": "red", "IP2": "square"}, {"WO1": "hit"}, F(1, 6), F(1)),   # r2 only
    ({"IP1": "blue", "IP2": "flat"}, {"WO1": "miss"}, F(1, 6), F(0)),   # r6 only, a hit
]

# World A, IP2 weights [2, 1, 1] (rows weigh 1/4, 1/8, 1/8, 1/4, 1/8, 1/8).
A_WEIGHTED_SCORES = [
    ({"IP1": "red"}, {"WO1": "hit"}, F(1, 2), F(3, 4)),       # (1/4 + 1/8) / (1/2)
    ({"IP1": "blue"}, {"WO1": "miss"}, F(1, 2), F(3, 4)),     # (1/4 + 1/8) / (1/2)
    ({"IP1": "blue"}, {"WO1": "hit"}, F(1, 2), F(1, 4)),      # (1/8) / (1/2)
    ({"IP2": "round"}, {"WO1": "hit"}, F(1, 2), F(1, 2)),     # (1/4) / (1/4 + 1/4)
    ({"IP2": "square"}, {"WO1": "hit"}, F(1, 4), F(1, 2)),    # (1/8) / (1/8 + 1/8)
    ({"IP2": "flat"}, {"WO1": "miss"}, F(1, 4), F(1, 2)),     # (1/8) / (1/8 + 1/8)
    ({"IP1": "red", "IP2": "round"}, {"WO1": "hit"}, F(1, 4), F(1)),
    ({"IP1": "red", "IP2": "square"}, {"WO1": "hit"}, F(1, 8), F(1)),
    ({"IP1": "blue", "IP2": "flat"}, {"WO1": "miss"}, F(1, 8), F(0)),
]

# World C, unweighted.
C_SCORES = [
    ({"IP1": "red"}, {"WO1": "hit", "WO2": "light"}, F(1, 2), F(2, 3)),   # r1 r2 of r1 r2 r3
    ({"IP1": "blue"}, {"WO1": "miss", "WO2": "light"}, F(1, 2), F(1, 3)),  # r4 of r4 r5 r6
    ({"IP2": "round"}, {"WO2": "light"}, F(1, 3), F(1)),                   # r1 r4 both light
    ({"IP2": "square"}, {"WO1": "hit", "WO2": "light"}, F(1, 3), F(1, 2)),  # r2 of r2 r5
    ({"IP2": "flat"}, {"WO1": "hit", "WO2": "light"}, F(1, 3), F(0)),
    ({"IP1": "blue", "IP2": "square"}, {"WO1": "miss", "WO2": "dark"}, F(1, 6), F(1)),
    ({"IP1": "blue", "IP2": "square"}, {"WO1": "miss", "WO2": "light"}, F(1, 6), F(0)),
]


def _check_scores(scenario, rows, cases):
    for inputs, outcomes, coverage, accuracy in cases:
        theory = T(inputs, outcomes)
        score = score_theory(scenario, rows, theory)
        assert score.theory == theory
        assert score.coverage == coverage, (inputs, outcomes)
        assert score.accuracy == accuracy, (inputs, outcomes)
        assert isinstance(score.coverage, F) and isinstance(score.accuracy, F)


def test_coverage_and_accuracy_hand_checked(tmp_path):
    """4.3 Screening: coverage and accuracy of a theory (unweighted world)."""
    _check_scores(load(tmp_path, tiny_data()), rows_a(), A_SCORES)


def test_coverage_and_accuracy_are_weighted(tmp_path):
    """4.3 Screening: coverage and accuracy are weighted shares of rows."""
    _check_scores(load(tmp_path, weighted(tiny_data())), rows_a(), A_WEIGHTED_SCORES)


def test_coverage_and_accuracy_with_two_outcomes(tmp_path):
    """4.3 Screening: a covered row counts only when every outcome state of the theory matches."""
    _check_scores(load(tmp_path, two_outcome_data()), rows_c(), C_SCORES)


# --- base rates -------------------------------------------------------------------------

def test_base_rates_hand_checked(tmp_path):
    """4.3 Screening: a state's base rate is the share of rows in which it is realised."""
    scenario = load(tmp_path, two_outcome_data())
    # WO1: hit in r1 r2 r6 -> 1/2.  WO2: light in r1 r2 r4 -> 1/2.
    assert base_rates(scenario, rows_c()) == {
        "WO1": {"hit": F(1, 2), "miss": F(1, 2)},
        "WO2": {"light": F(1, 2), "dark": F(1, 2)},
    }


def test_base_rate_is_weighted_share_of_rows(tmp_path):
    """4.1 Reading the scenario file (row weight); 4.3 Screening: base rates are weighted shares."""
    rows = rows_a(WORLD_A2)  # hit in r1 r2 r4, miss in r3 r5 r6
    plain = load(tmp_path, tiny_data(), "plain.md")
    heavy = load(tmp_path, weighted(tiny_data()), "weighted.md")
    # Unweighted: 3 of 6 rows.
    assert base_rates(plain, rows) == {"WO1": {"hit": F(1, 2), "miss": F(1, 2)}}
    # Weighted: hit = 1/4 + 1/8 + 1/4 = 5/8, miss = 1/8 + 1/8 + 1/8 = 3/8.
    assert base_rates(heavy, rows) == {"WO1": {"hit": F(5, 8), "miss": F(3, 8)}}


def test_shares_are_normalised_by_the_rows_passed_in(tmp_path):
    """4.3 Screening: shares are weighted shares of the rows of the table."""
    red_rows = rows_a()[:3]  # r1 hit, r2 hit, r3 miss
    plain = load(tmp_path, tiny_data(), "plain.md")
    heavy = load(tmp_path, weighted(tiny_data()), "weighted.md")
    assert base_rates(plain, red_rows) == {"WO1": {"hit": F(2, 3), "miss": F(1, 3)}}
    # Weights 1/4, 1/8, 1/8 out of 1/2: hit = 3/8 / 1/2 = 3/4.
    assert base_rates(heavy, red_rows) == {"WO1": {"hit": F(3, 4), "miss": F(1, 4)}}


# --- the screening report ---------------------------------------------------------------

def test_report_base_rates_and_best_accuracy(tmp_path):
    """4.3 Screening: base rates and the best accuracy by number of input parameters."""
    scenario = load(tmp_path, tiny_data(), "plain.md")
    report = screen(scenario, rows_a())
    assert report.base_rates == {"WO1": {"hit": F(1, 2), "miss": F(1, 2)}}
    # Best one-input theories: red -> hit and blue -> miss, 2/3; every two-input theory covers
    # one row, so the best is 1.
    assert report.best_accuracy_by_inputs == {1: F(2, 3), 2: F(1)}

    heavy = screen(load(tmp_path, weighted(tiny_data()), "weighted.md"), rows_a())
    # Weighted: red -> hit and blue -> miss reach 3/4.
    assert heavy.best_accuracy_by_inputs == {1: F(3, 4), 2: F(1)}

    two = screen(load(tmp_path, two_outcome_data(), "two.md"), rows_c())
    # round -> light and flat -> dark are always right.
    assert two.best_accuracy_by_inputs == {1: F(1), 2: F(1)}


NOBEL_CASES = [
    # (scenario maker, rows maker, max_input_parameters, min_accuracy, theories, patterns, maximal)
    # World A, min 0.9: only the six two-input theories naming their row's outcome.
    ("A max2 min0.9", tiny_data, rows_a, 2, 0.9, 6, 6, 6),
    # World A, min 0.5 (on the limit): one-input red->hit, blue->miss (2/3) and both outcomes of
    # round, square and flat (1/2 each) = 8 theories on 5 patterns; plus the six two-input ones.
    # One outcome only, so no theory implies another: maximal = theories.
    ("A max2 min0.5", tiny_data, rows_a, 2, 0.5, 14, 11, 14),
    ("A max1 min0.5", tiny_data, rows_a, 1, 0.5, 8, 5, 8),
    # 2/3 is just above 0.66 and just below 0.7.
    ("A max1 min0.66", tiny_data, rows_a, 1, 0.66, 2, 2, 2),
    ("A max1 min0.7", tiny_data, rows_a, 1, 0.7, 0, 0, 0),
    # World C, max 1 input, min 0.5 (accuracies listed per input state):
    #   red:    hit 2/3, light 2/3, hit+light 2/3                 -> 3 theories, maximal: hit+light
    #   blue:   miss 2/3, dark 2/3 (every pair 1/3 or 0)          -> 2 theories, both maximal
    #   round:  hit, miss 1/2; light 1; hit+light, miss+light 1/2 -> 5 theories, 2 maximal
    #   square: hit, miss, light, dark, hit+light, miss+dark 1/2  -> 6 theories, 2 maximal
    #   flat:   hit, miss 1/2; dark 1; hit+dark, miss+dark 1/2    -> 5 theories, 2 maximal
    # Total 21 theories, 5 input patterns, 9 maximal theories.
    ("C max1 min0.5", two_outcome_data, rows_c, 1, 0.5, 21, 5, 9),
    # Adding two-input theories: each covers one row; the 3 non-empty outcome choices that agree
    # with the row are right (18 theories, 6 patterns, 6 maximal).
    ("C max2 min0.5", two_outcome_data, rows_c, 2, 0.5, 39, 11, 15),
    # min 0.9: one-input only round->light and flat->dark; plus the 18 two-input theories.
    ("C max2 min0.9", two_outcome_data, rows_c, 2, 0.9, 20, 8, 8),
]


@pytest.mark.parametrize("make, rows, max_inputs, min_accuracy, theories, patterns, maximal",
                         [c[1:] for c in NOBEL_CASES], ids=[c[0] for c in NOBEL_CASES])
def test_nobel_counts_hand_checked(tmp_path, make, rows, max_inputs, min_accuracy, theories, patterns, maximal):
    """4.3 Screening: Nobel-grade theories and the three counts."""
    data = strict_counts_criteria(make(), max_inputs=max_inputs, min_accuracy=min_accuracy)
    report = screen(load(tmp_path, data), rows())
    assert report.nobel_counts == {
        "theories": theories, "input_patterns": patterns, "maximal_theories": maximal,
    }
    assert len(report.nobel_grade) == theories
    for score in report.nobel_grade:
        assert len(score.theory.inputs) <= max_inputs
        assert score.accuracy >= F(str(min_accuracy))


def test_nobel_grade_list_hand_checked(tmp_path):
    """4.3 Screening: the Nobel-grade theories of world A at min_accuracy 0.9."""
    data = strict_counts_criteria(tiny_data(), max_inputs=2, min_accuracy=0.9)
    report = screen(load(tmp_path, data), rows_a())
    expected = {T({"IP1": c, "IP2": s}, {"WO1": o}) for (c, s), o in zip(COMBOS, WORLD_A)}
    assert {s.theory for s in report.nobel_grade} == expected
    for score in report.nobel_grade:
        assert score.coverage == F(1, 6)
        assert score.accuracy == 1


def test_accuracy_exactly_min_accuracy_is_nobel_grade(tmp_path):
    """4.3 Screening (Comparisons): a min_ criterion passes at the limit (>=)."""
    data = strict_counts_criteria(tiny_data(), max_inputs=1, min_accuracy=0.5)
    report = screen(load(tmp_path, data), rows_a())
    nobel = {s.theory: s for s in report.nobel_grade}
    # square -> hit: r2 hit, r5 miss = exactly 1/2.
    on_limit = T({"IP2": "square"}, {"WO1": "hit"})
    assert on_limit in nobel
    assert nobel[on_limit].accuracy == F(1, 2)
    # red -> miss: 1/3, below the limit.
    assert T({"IP1": "red"}, {"WO1": "miss"}) not in nobel


def test_more_input_parameters_than_allowed_are_not_nobel_grade(tmp_path):
    """4.3 Screening: Nobel-grade theories have at most max_input_parameters inputs."""
    data = strict_counts_criteria(tiny_data(), max_inputs=1, min_accuracy=0.9)
    report = screen(load(tmp_path, data), rows_a())
    # Only the two-input theories reach 1, and they have too many input parameters.
    assert report.nobel_grade == []
    assert report.nobel_counts == {"theories": 0, "input_patterns": 0, "maximal_theories": 0}


# --- acceptance criteria and their limits ---------------------------------------------------

@pytest.mark.parametrize(
    "changes, failed",
    [
        # Weighted world A: base rates 1/2 and 1/2 (hit = 1/4 + 1/8 + 1/8).
        ({"max_base_rate": 0.5}, []),
        ({"max_base_rate": 0.49}, ["max_base_rate"]),
        # Best one-input accuracy 3/4 (red -> hit, blue -> miss).
        ({"max_one_input_theory_accuracy": 0.75}, []),
        ({"max_one_input_theory_accuracy": 0.74}, ["max_one_input_theory_accuracy"]),
        # min_accuracy 0.9: the six two-input theories naming their row's outcome.
        ({"nobel_min_count": 6}, []),
        ({"nobel_min_count": 7}, ["nobel_grade.min_count"]),
        ({"nobel_max_count": 6}, []),
        ({"nobel_max_count": 5}, ["nobel_grade.max_count"]),
        ({"nobel_min_count": 6, "nobel_max_count": 6}, []),
        ({"max_base_rate": 0.49, "max_one_input_theory_accuracy": 0.74, "nobel_max_count": 5},
         ["max_base_rate", "max_one_input_theory_accuracy", "nobel_grade.max_count"]),
    ],
    ids=["base on limit", "base above", "one-input on limit", "one-input above",
         "min_count on limit", "min_count missed", "max_count on limit", "max_count exceeded",
         "count exactly the range", "three failures"],
)
def test_criteria_limits(tmp_path, changes, failed):
    """4.3 Screening (Comparisons): max_ passes at or below the limit, min_ at or above it."""
    data = strict_counts_criteria(weighted(tiny_data()), max_inputs=2, min_accuracy=0.9)
    data = with_criteria(data, **changes)
    report = screen(load(tmp_path, data), rows_a())
    assert sorted(report.failed) == sorted(failed)
    assert report.passed is (not failed)


@pytest.mark.parametrize(
    "count, low, high, failed",
    [
        # World C, max 1 input, min 0.5: 21 theories, 5 input patterns, 9 maximal theories.
        ("theories", 21, 21, []),
        ("input_patterns", 5, 5, []),
        ("maximal_theories", 9, 9, []),
        ("theories", 5, 5, ["nobel_grade.max_count"]),
        ("theories", 9, 9, ["nobel_grade.max_count"]),
        ("input_patterns", 9, 9, ["nobel_grade.min_count"]),
        ("input_patterns", 21, 21, ["nobel_grade.min_count"]),
        ("maximal_theories", 5, 5, ["nobel_grade.max_count"]),
        ("maximal_theories", 21, 21, ["nobel_grade.min_count"]),
    ],
)
def test_count_named_by_nobel_grade_count(tmp_path, count, low, high, failed):
    """4.3 Screening: nobel_grade.count names the count that min_count and max_count apply to."""
    data = strict_counts_criteria(two_outcome_data(), max_inputs=1, min_accuracy=0.5,
                                  count=count, min_count=low, max_count=high)
    report = screen(load(tmp_path, data), rows_c())
    assert sorted(report.failed) == failed
    assert report.passed is (not failed)


def test_shares_on_the_limit_are_exact(tmp_path):
    """4.3 Screening (Comparisons): a value on the limit is never misjudged by rounding."""
    data = tiny_data()
    # IP1 weights [3, 7]: red rows weigh 3/10 in total, blue rows 7/10. In floating point,
    # 0.7 * (1/3) summed three times and divided by the total comes out above 0.7.
    data["input_parameters"][0]["weights"] = [3, 7]
    data = with_criteria(data, max_base_rate=0.7)
    scenario = load(tmp_path, data)
    rows = rows_a(["miss", "miss", "miss", "hit", "hit", "hit"])
    report = screen(scenario, rows)
    assert report.base_rates == {"WO1": {"hit": F(7, 10), "miss": F(3, 10)}}
    assert "max_base_rate" not in report.failed
    assert report.passed


# --- screening a generated world --------------------------------------------------------------

def _reference_screen(data, rows):
    """A plain re-implementation of 4.3 for cross-checking generated worlds."""
    weight = {}
    for p in data["input_parameters"]:
        raw = [F(w) for w in p.get("weights", [1] * len(p["states"]))]
        for s, w in zip(p["states"], raw):
            weight[(p["id"], s)] = w / sum(raw)
    row_w = []
    for r in rows:
        w = F(1)
        for pid, s in r.inputs.items():
            w *= weight[(pid, s)]
        row_w.append(w)
    total = sum(row_w)
    rates = {
        o["id"]: {s: sum(w for r, w in zip(rows, row_w) if r.outcomes[o["id"]] == s) / total
                  for s in o["states"]}
        for o in data["world_outcomes"]
    }
    nobel_rule = data["acceptance_criteria"]["nobel_grade"]
    min_acc, max_in = F(str(nobel_rule["min_accuracy"])), nobel_rule["max_input_parameters"]
    best, nobel = {}, []
    for inputs, outcomes in _expected_theories(data):
        inputs, outcomes = dict(inputs), dict(outcomes)
        covered = [(r, w) for r, w in zip(rows, row_w) if all(r.inputs[k] == v for k, v in inputs.items())]
        cov_w = sum(w for _, w in covered)
        acc = sum(w for r, w in covered if all(r.outcomes[k] == v for k, v in outcomes.items())) / cov_w
        n = len(inputs)
        best[n] = max(best.get(n, F(0)), acc)
        if n <= max_in and acc >= min_acc:
            nobel.append((inputs, outcomes))
    maximal = [
        (i, o) for i, o in nobel
        if not any(i2 == i and set(o2.items()) > set(o.items()) for i2, o2 in nobel)
    ]
    counts = {
        "theories": len(nobel),
        "input_patterns": len({frozenset(i.items()) for i, _ in nobel}),
        "maximal_theories": len(maximal),
    }
    return rates, best, counts


@pytest.mark.parametrize("seed", [2, 9])
def test_generated_world_matches_reference_screening(tmp_path, seed):
    """4.3 Screening: base rates, best accuracies and Nobel counts of a generated world."""
    data = weighted(two_outcome_data())
    data["effect_model"]["interactions"] = ["large", "small"]
    data = strict_counts_criteria(data, max_inputs=1, min_accuracy=0.6)
    scenario = load(tmp_path, data)
    world = build_world(scenario, seed)
    report = screen(scenario, world.rows)
    rates, best, counts = _reference_screen(data, world.rows)
    assert report.base_rates == rates
    assert report.best_accuracy_by_inputs == best
    assert report.nobel_counts == counts


def test_screening_uses_the_realised_table_not_probabilities():
    """4.3 Screening: computed from the realised table, not from the softmax probabilities."""
    scenario = load_scenario(VENUS)
    world = build_world(scenario, 4)
    bare = [Row(inputs=dict(r.inputs), outcomes=dict(r.outcomes)) for r in world.rows]
    assert screening_signature(screen(scenario, world.rows)) == screening_signature(screen(scenario, bare))

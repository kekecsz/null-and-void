"""Specification section 4.3, "Screening": regenerating with the next seed until the world passes.

Uses the hand-made tiny scenario from conftest.py so each try is fast.
"""

import pytest

from nv_world.generate import GenerationFailed, build_world, generate_world
from nv_world.scenario import load_scenario
from nv_world.screening import screen

from tests.world.conftest import (
    rows_signature,
    screening_signature,
    tiny_data,
    with_criteria,
    world_signature,
    write_scenario,
)

CRITERIA = ("max_base_rate", "max_one_input_theory_accuracy", "nobel_grade.min_count", "nobel_grade.max_count")

# Criteria no world can pass (each alone; the others stay easy):
# - some outcome state always has a base rate of at least 1/2 > 0;
# - for a one-input theory naming one outcome, the states' accuracies add up to 1, so one is >= 1/2 > 0;
# - with min_accuracy 0 every one of the 22 theories is Nobel-grade, so min 10**6 is never reached
#   and max 0 is always exceeded.
IMPOSSIBLE = {
    "max_base_rate": {"max_base_rate": 0.0},
    "max_one_input_theory_accuracy": {"max_one_input_theory_accuracy": 0.0},
    "nobel_grade.min_count": {"nobel_min_accuracy": 0.0, "nobel_min_count": 10 ** 6},
    "nobel_grade.max_count": {"nobel_min_accuracy": 0.0, "nobel_max_count": 0},
}


def _scenario(tmp_path, name="scenario.md", **changes):
    return load_scenario(write_scenario(tmp_path, with_criteria(tiny_data(), **changes), name))


@pytest.mark.parametrize("criterion", CRITERIA)
def test_every_try_failing_raises_with_failure_counts(tmp_path, criterion):
    """4.3 Screening: if every try fails, the error says how often each criterion failed."""
    scenario = _scenario(tmp_path, max_generation_tries=3, **IMPOSSIBLE[criterion])
    with pytest.raises(GenerationFailed) as excinfo:
        generate_world(scenario, 10)
    error = excinfo.value
    assert error.tries == 3
    assert error.failure_counts[criterion] == 3
    for other in CRITERIA:
        if other != criterion:
            assert error.failure_counts.get(other, 0) == 0, other
    assert criterion in str(error)
    assert "3" in str(error)


def test_failure_counts_add_up_per_criterion(tmp_path):
    """4.3 Screening: each criterion's failures are counted separately."""
    scenario = _scenario(tmp_path, max_generation_tries=4, max_base_rate=0.0, max_one_input_theory_accuracy=0.0)
    with pytest.raises(GenerationFailed) as excinfo:
        generate_world(scenario, 0)
    assert excinfo.value.tries == 4
    assert excinfo.value.failure_counts["max_base_rate"] == 4
    assert excinfo.value.failure_counts["max_one_input_theory_accuracy"] == 4


def test_world_that_passes_at_once_needs_one_try(tmp_path):
    """4.3 Screening: the requested seed is tried first."""
    scenario = _scenario(tmp_path)  # easy criteria from conftest.py
    world = generate_world(scenario, 42)
    assert world.tries == 1
    assert world.requested_seed == 42
    assert world.seed == 42
    assert rows_signature(world.rows) == rows_signature(build_world(scenario, 42).rows)
    assert world.screening is not None and world.screening.passed


@pytest.mark.parametrize("requested", [0, 1, 2, 3, 4])
def test_retries_use_the_next_seeds(tmp_path, requested):
    """4.3 Screening: regenerate with seed + 1, seed + 2, ... and record both seeds."""
    # A base rate of at most 1/2 means exactly 3 of the 6 rows realise each state:
    # some worlds pass, many do not.
    scenario = _scenario(tmp_path, max_base_rate=0.5, max_generation_tries=300)
    world = generate_world(scenario, requested)
    assert world.requested_seed == requested
    assert 1 <= world.tries <= 300
    assert world.seed == requested + world.tries - 1
    # The accepted world is exactly the one try that used the accepted seed ...
    accepted = build_world(scenario, world.seed)
    assert world_signature(world) == world_signature(accepted)
    # ... it passes screening, and every earlier seed failed.
    assert world.screening.passed
    assert world.screening.failed == []
    assert screening_signature(world.screening) == screening_signature(screen(scenario, world.rows))
    for seed in range(requested, world.seed):
        assert not screen(scenario, build_world(scenario, seed).rows).passed, seed


def test_generation_is_deterministic(tmp_path):
    """13. Milestones (1): the same scenario and seed always give the same World Table."""
    first = _scenario(tmp_path, "a.md", max_base_rate=0.5, max_generation_tries=300)
    second = _scenario(tmp_path, "b.md", max_base_rate=0.5, max_generation_tries=300)
    a, b = generate_world(first, 7), generate_world(second, 7)
    assert (a.seed, a.tries) == (b.seed, b.tries)
    assert world_signature(a) == world_signature(b)
    assert screening_signature(a.screening) == screening_signature(b.screening)

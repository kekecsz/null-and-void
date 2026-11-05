"""Specification section 4.5, "Command-line tools" (nv-world generate / nv-world report).

Every file the tools write goes into tmp_path (--out, --csv-dir).
"""

import csv
import os
import subprocess
import sys

import pytest

from nv_core.paths import REPO_ROOT
from nv_world.cli import main
from nv_world.worldfile import load_world

from tests.world.conftest import (
    EASY_CRITERIA,
    venus_data,
    with_criteria,
    tiny_data,
    two_outcome_data,
    world_signature,
    write_scenario,
)

CSV_FILES = ("base_rates.csv", "best_theories.csv", "nobel_grade.csv", "summary.csv")


def _output(capsys, tmp_path=None) -> str:
    """stdout + stderr; without the tmp_path folder, whose name repeats the test name (e.g. "warns")."""
    captured = capsys.readouterr()
    text = captured.out + captured.err
    return text.replace(str(tmp_path), "<tmp>") if tmp_path is not None else text


def _generate(tmp_path, scenario_path, seed, out_name="world.json"):
    out = tmp_path / out_name
    code = main(["generate", str(scenario_path), "--seed", str(seed), "--out", str(out)])
    return code, out


@pytest.fixture
def tiny_scenario(tmp_path):
    data = two_outcome_data()
    data = with_criteria(data, nobel_min_accuracy=0.6, max_generation_tries=5)
    return data, write_scenario(tmp_path, data)


def test_generate_writes_a_world_file(tmp_path, capsys, tiny_scenario):
    """4.5 Command-line tools: nv-world generate gives a world file plus its screening report."""
    _, scenario_path = tiny_scenario
    code, out = _generate(tmp_path, scenario_path, 5)
    output = _output(capsys, tmp_path)
    assert code == 0
    assert out.exists()
    world = load_world(out)
    assert world.requested_seed == 5
    assert world.seed == 5 + world.tries - 1
    assert world.screening is not None and world.screening.passed
    assert output.strip(), "generate printed nothing"
    assert str(world.tries) in output


def test_generate_reports_failure(tmp_path, capsys):
    """4.3 Screening: if every try fails, the generator stops with an error (exit code 1)."""
    # No world can have every base rate at or below 0.
    data = with_criteria(tiny_data(), max_base_rate=0.0, max_generation_tries=3)
    code, out = _generate(tmp_path, write_scenario(tmp_path, data), 0)
    output = _output(capsys, tmp_path)
    assert code == 1
    assert "max_base_rate" in output


def test_report_prints_and_writes_csv(tmp_path, capsys, tiny_scenario):
    """4.5 Command-line tools: nv-world report gives base rates, best theories and Nobel counts as text and CSV."""
    data, scenario_path = tiny_scenario
    code, world_path = _generate(tmp_path, scenario_path, 1)
    assert code == 0
    capsys.readouterr()

    csv_dir = tmp_path / "csv"
    code = main(["report", str(world_path), "--scenario", str(scenario_path), "--csv-dir", str(csv_dir)])
    output = _output(capsys, tmp_path)
    assert code == 0
    for outcome in data["world_outcomes"]:
        for state in outcome["states"]:
            assert state in output, state
    assert "warn" not in output.lower()

    for name in CSV_FILES:
        path = csv_dir / name
        assert path.exists(), name
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        assert rows, f"{name} is empty"
        header = rows[0]
        assert header and all(cell.strip() for cell in header), f"{name} has no header: {header}"
        for row in rows[1:]:
            assert len(row) == len(header), name

    with (csv_dir / "base_rates.csv").open(encoding="utf-8", newline="") as handle:
        text = handle.read()
    for outcome in data["world_outcomes"]:
        for state in outcome["states"]:
            assert state in text, state
    for name in ("best_theories.csv", "summary.csv"):
        with (csv_dir / name).open(encoding="utf-8", newline="") as handle:
            assert len(list(csv.reader(handle))) > 1, f"{name} has no data rows"


def test_report_accepts_top(tmp_path, capsys, tiny_scenario):
    """4.5 Command-line tools: nv-world report with a limit on the theories listed."""
    _, scenario_path = tiny_scenario
    code, world_path = _generate(tmp_path, scenario_path, 2)
    assert code == 0
    code = main(["report", str(world_path), "--scenario", str(scenario_path),
                 "--csv-dir", str(tmp_path / "csv"), "--top", "2"])
    assert code == 0


def test_report_warns_when_the_scenario_changed(tmp_path, capsys):
    """4.4 World files: warn when a scenario's data was edited after a world was generated."""
    # A copy of Venus with criteria every world passes: same id, different data.
    data = venus_data()
    data["acceptance_criteria"] = dict(EASY_CRITERIA, max_generation_tries=3)
    scenario_path = write_scenario(tmp_path, data)
    code, world_path = _generate(tmp_path, scenario_path, 0)
    assert code == 0
    capsys.readouterr()

    # Matching scenario: no warning.
    code = main(["report", str(world_path), "--scenario", str(scenario_path), "--csv-dir", str(tmp_path / "a")])
    assert code == 0
    assert "warn" not in _output(capsys, tmp_path).lower()

    # Default scenario: scenarios/venus_expedition/scenario.md, whose criteria differ from the copy.
    code = main(["report", str(world_path), "--csv-dir", str(tmp_path / "b")])
    assert code == 0
    assert "warn" in _output(capsys, tmp_path).lower()


def test_generate_does_not_depend_on_hash_seed(tmp_path):
    """13. Milestones (1): the same scenario and seed always give the same World Table, in any process."""
    data = with_criteria(tiny_data(), max_base_rate=0.5, max_generation_tries=300)
    scenario_path = write_scenario(tmp_path, data)
    script = "import sys; from nv_world.cli import main; sys.exit(main(sys.argv[1:]))"
    worlds = []
    for hash_seed in ("1", "2"):
        out = tmp_path / f"world_{hash_seed}.json"
        env = dict(os.environ, PYTHONHASHSEED=hash_seed)
        result = subprocess.run(
            [sys.executable, "-c", script, "generate", str(scenario_path), "--seed", "4", "--out", str(out)],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        worlds.append(load_world(out))
    a, b = worlds
    assert (a.seed, a.tries) == (b.seed, b.tries)
    assert world_signature(a) == world_signature(b)

"""Specification section 4.5, "Command-line tools" (nv-world generate / nv-world report).

Every file the tools write goes into tmp_path (--out, --csv-dir).
"""

import copy
import csv
import os
import re
import subprocess
import sys
from collections import Counter

import pytest

from nv_core.paths import REPO_ROOT
from nv_world.cli import main
from nv_world.generate import build_world, generate_world
from nv_world.scenario import load_scenario
from nv_world.screening import enumerate_theories, score_theory, screen
from nv_world.worldfile import load_world, save_world

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
    data, scenario_path = tiny_scenario
    max_tries = data["acceptance_criteria"]["max_generation_tries"]
    code, out = _generate(tmp_path, scenario_path, 5)
    output = _output(capsys, tmp_path)
    assert code == 0
    assert out.exists()
    world = load_world(out)
    assert world.requested_seed == 5
    # 4.3 Screening: try k of requested seed s uses s x max_generation_tries + k.
    assert world.seed == 5 * max_tries + world.tries - 1
    assert world.screening is not None and world.screening.passed
    assert output.strip(), "generate printed nothing"


def _passes(scenario, seed) -> bool:
    return screen(scenario, build_world(scenario, seed).rows).passed


def test_generate_states_the_number_of_tries(tmp_path, capsys):
    """4.5 Command-line tools: generate prints the screening report, including the number of tries."""
    # Tiny one-outcome scenario (6 rows): max_base_rate 0.5 passes only on a 3-to-3 split.
    data = with_criteria(tiny_data(), max_base_rate=0.5, max_generation_tries=300)
    max_tries = data["acceptance_criteria"]["max_generation_tries"]
    scenario_path = write_scenario(tmp_path, data)
    scenario = load_scenario(scenario_path)
    # 4.3 Screening: try k of requested seed s uses s x max_generation_tries + k.
    # A requested seed whose first two tries fail (checked one try at a time), so tries >= 3.
    requested = next(s for s in range(100, 400)
                     if not _passes(scenario, s * max_tries) and not _passes(scenario, s * max_tries + 1))
    expected_tries = next(k + 1 for k in range(max_tries) if _passes(scenario, requested * max_tries + k))
    assert expected_tries >= 3

    code, out = _generate(tmp_path, scenario_path, requested)
    output = _output(capsys, tmp_path)
    assert code == 0
    world = load_world(out)
    assert world.tries == expected_tries
    assert world.seed == requested * max_tries + expected_tries - 1
    number = re.compile(rf"(?<!\d){expected_tries}(?!\d)")
    lines = [line for line in output.splitlines() if "tr" in line.lower() and number.search(line)]
    assert lines, f"no line states the number of tries ({expected_tries}):\n{output}"


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


# --- report: recomputed with the current scenario file ----------------------------------------

def _save(tmp_path, data, seed, name="scenario.md"):
    """Write a scenario, generate a world from it (easy criteria: one try) and save it."""
    scenario_path = write_scenario(tmp_path, data, name)
    world = generate_world(load_scenario(scenario_path), seed)
    world_path = tmp_path / f"world_{name}.json"
    save_world(world, world_path)
    return scenario_path, world_path


def _report(tmp_path, world_path, scenario_path, csv_name, *extra):
    return main(["report", str(world_path), "--scenario", str(scenario_path),
                 "--csv-dir", str(tmp_path / csv_name), *extra])


def _read_csv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows, f"{path.name} is empty"
    return rows[0], rows[1:]


def _float(cell):
    try:
        return float(cell)
    except ValueError:
        return None


def _numbers(cells) -> list:
    return [n for n in (_float(c) for c in cells) if n is not None]


def _tokens(cells) -> set:
    return set(re.findall(r"[A-Za-z]+", " ".join(cells)))


def _theory_key(cells, data):
    """The theory a CSV row names, read from the state names in it (all fixture state names are
    distinct single words): (sorted input items, sorted outcome items)."""
    words = _tokens(cells)
    inputs = {p["id"]: s for p in data["input_parameters"] for s in p["states"] if s in words}
    outcomes = {o["id"]: s for o in data["world_outcomes"] for s in o["states"] if s in words}
    return tuple(sorted(inputs.items())), tuple(sorted(outcomes.items()))


def _key(theory):
    return tuple(sorted(theory.inputs.items())), tuple(sorted(theory.outcomes.items()))


def _csv_base_rates(path, data) -> dict:
    """{(outcome id, state): numbers in that row} from base_rates.csv."""
    _, rows = _read_csv(path)
    found = {}
    for cells in rows:
        words = _tokens(cells)
        named = [(o["id"], s) for o in data["world_outcomes"] for s in o["states"] if s in words]
        assert len(named) == 1, f"base_rates.csv row does not name one outcome state: {cells}"
        assert named[0] not in found, f"{named[0]} listed twice in base_rates.csv"
        found[named[0]] = _numbers(cells)
    return found


def _check_base_rates_csv(path, data, expected):
    """Every outcome state has one row, holding its base rate as a decimal."""
    found = _csv_base_rates(path, data)
    assert set(found) == {(o, s) for o, states in expected.items() for s in states}
    for (outcome, state), numbers in found.items():
        rate = float(expected[outcome][state])
        assert any(n == pytest.approx(rate, abs=6e-3) for n in numbers), (outcome, state, rate, numbers)


def _accuracy_column(header, name) -> int:
    columns = [k for k, cell in enumerate(header) if "accuracy" in cell.lower()]
    assert columns, f"{name} has no accuracy column: {header}"
    return columns[0]


# Two outcomes (6 rows, each counted once); min_accuracy 0.6 keeps some theories out of the
# Nobel-grade list.
def _report_data():
    return with_criteria(two_outcome_data(), nobel_min_accuracy=0.6, max_generation_tries=5)


@pytest.mark.parametrize("top", [1, 3])
def test_report_matches_screening(tmp_path, capsys, top):
    """4.5 Command-line tools; 13. Milestones (1): the report lists base rates and Nobel-grade theories."""
    data = _report_data()
    scenario_path, world_path = _save(tmp_path, data, 3)
    scenario = load_scenario(scenario_path)
    rows = load_world(world_path).rows
    expected = screen(scenario, rows)
    capsys.readouterr()

    code = _report(tmp_path, world_path, scenario_path, "csv", "--top", str(top))
    text = _output(capsys, tmp_path)
    assert code == 0
    csv_dir = tmp_path / "csv"

    # base_rates.csv: one row per outcome state, holding float(base rate).
    _check_base_rates_csv(csv_dir / "base_rates.csv", data, expected.base_rates)

    # nobel_grade.csv: exactly one row per Nobel-grade theory.
    _, nobel_rows = _read_csv(csv_dir / "nobel_grade.csv")
    listed = [_theory_key(cells, data) for cells in nobel_rows]
    assert len(listed) == len(expected.nobel_grade)
    assert Counter(listed) == Counter(_key(s.theory) for s in expected.nobel_grade)

    # summary.csv: one row, holding the three Nobel-grade counts.
    _, summary_rows = _read_csv(csv_dir / "summary.csv")
    assert len(summary_rows) == 1
    integers = Counter(int(c) for c in summary_rows[0] if re.fullmatch(r"\s*-?\d+\s*", c))
    missing = Counter(expected.nobel_counts.values()) - integers
    assert not missing, f"summary.csv lacks the counts {dict(expected.nobel_counts)}: {summary_rows[0]}"

    # best_theories.csv: the `top` best per number of input parameters, sorted by accuracy.
    header, best_rows = _read_csv(csv_dir / "best_theories.csv")
    column = _accuracy_column(header, "best_theories.csv")
    all_scores = {_key(t): score_theory(scenario, rows, t).accuracy for t in enumerate_theories(scenario)}
    groups = {}
    for cells in best_rows:
        key = _theory_key(cells, data)
        assert key in all_scores, f"best_theories.csv row names no theory: {cells}"
        accuracy = _float(cells[column])
        assert accuracy == pytest.approx(float(all_scores[key]), abs=6e-3), (key, cells)
        groups.setdefault(len(key[0]), []).append(accuracy)
    assert set(groups) == set(expected.best_accuracy_by_inputs)
    for n, accuracies in groups.items():
        available = sorted((float(a) for k, a in all_scores.items() if len(k[0]) == n), reverse=True)
        assert len(accuracies) == min(top, len(available)), n
        assert accuracies == sorted(accuracies, reverse=True), f"{n} inputs: not sorted by accuracy"
        assert accuracies[0] == pytest.approx(float(expected.best_accuracy_by_inputs[n]), abs=6e-3)
        assert accuracies == pytest.approx(available[:len(accuracies)], abs=6e-3)

    # The text output: base rates as decimals and the Nobel-grade counts.
    assert "nobel" in text.lower()
    for count in expected.nobel_counts.values():
        assert re.search(rf"(?<![\d.]){count}(?![\d.])", text), f"count {count} not in the text output"
    lines = text.splitlines()
    for outcome, states in expected.base_rates.items():
        for state, rate in states.items():
            assert any(re.search(rf"\b{state}\b", line)
                       and any(n == pytest.approx(float(rate), abs=6e-3)
                               for n in map(float, re.findall(r"\d+\.\d+", line)))
                       for line in lines), f"base rate of {state} ({float(rate)}) not printed"


def test_report_uses_the_current_criteria(tmp_path, capsys):
    """4.5 Command-line tools: the report recomputes with the current scenario file's criteria."""
    # Generated with criteria every world passes (min_accuracy 0: all 22 theories Nobel-grade).
    data = with_criteria(tiny_data(), nobel_min_accuracy=0.0, max_generation_tries=5)
    scenario_path, world_path = _save(tmp_path, data, 4)
    rows = load_world(world_path).rows
    capsys.readouterr()
    assert _report(tmp_path, world_path, scenario_path, "a") == 0
    text_a = _output(capsys, tmp_path)

    # A copy with stricter criteria: no world has every base rate at or below 0.
    strict = with_criteria(data, max_base_rate=0.0, nobel_min_accuracy=0.9)
    strict_path = write_scenario(tmp_path, strict, "strict.md")
    expected = screen(load_scenario(strict_path), rows)
    assert "max_base_rate" in expected.failed
    _report(tmp_path, world_path, strict_path, "b")
    text_b = _output(capsys, tmp_path)

    def failure_lines(text):
        return [line for line in text.splitlines() if "max_base_rate" in line and "fail" in line.lower()]

    assert failure_lines(text_a) == [], text_a
    assert failure_lines(text_b), f"the report does not show max_base_rate failing:\n{text_b}"
    _, nobel_a = _read_csv(tmp_path / "a" / "nobel_grade.csv")
    _, nobel_b = _read_csv(tmp_path / "b" / "nobel_grade.csv")
    assert len(nobel_a) == 22  # (3*4 - 1) * (3 - 1) theories, all with accuracy >= 0
    assert len(nobel_b) == len(expected.nobel_grade) < 22


RENAMES = [
    # (case id, change to the scenario copy, names of which the error must mention one)
    ("input state", lambda d: d["input_parameters"][1]["states"].__setitem__(2, "oval"), ("flat", "oval")),
    ("outcome state", lambda d: d["world_outcomes"][0]["states"].__setitem__(1, "missed"), ("miss",)),
    ("input id", lambda d: d["input_parameters"][1].__setitem__("id", "IP7"), ("IP2", "IP7")),
    ("outcome id", lambda d: d["world_outcomes"][0].__setitem__("id", "WO9"), ("WO1", "WO9")),
]


@pytest.mark.parametrize("rename, names", [c[1:] for c in RENAMES], ids=[c[0] for c in RENAMES])
def test_report_stops_when_the_table_no_longer_fits(tmp_path, capsys, rename, names):
    """4.5 Command-line tools: report stops with an error when the table no longer fits the scenario."""
    data = with_criteria(tiny_data(), max_generation_tries=5)
    _, world_path = _save(tmp_path, data, 2)
    changed = copy.deepcopy(data)
    rename(changed)
    changed_path = write_scenario(tmp_path, changed, "renamed.md")
    load_scenario(changed_path)  # the copy itself is a valid scenario
    capsys.readouterr()

    code = _report(tmp_path, world_path, changed_path, "csv")
    error = capsys.readouterr().err.replace(str(tmp_path), "<tmp>")
    assert code == 1
    assert error.strip(), "no error printed on stderr"
    assert any(name in error for name in names), f"error does not mention {names}: {error}"


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

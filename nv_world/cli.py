"""Command-line tools (specification section 4.5).

    nv-world generate <scenario.md> --seed N [--out PATH]
    nv-world report <world.json> [--scenario PATH] [--csv-dir DIR] [--top N]
"""

import argparse
import csv
import sys
from fractions import Fraction
from pathlib import Path

from nv_core.paths import SCENARIOS_DIR
from nv_world.generate import GenerationFailed, World, generate_world
from nv_world.scenario import Scenario, ScenarioError, load_scenario
from nv_world.screening import ScreeningReport, TheoryScore, best_theories, check_rows, score_all, screen
from nv_world.worldfile import load_world, save_world, scenario_changed

DEFAULT_TOP = 5  # how many theories the report lists per number of input parameters (display only)


def _dec(value: Fraction) -> str:
    return f"{float(value):.3f}"


def _describe_theory(scenario: Scenario, score: TheoryScore) -> str:
    return f"{score.theory.label():<60} accuracy {_dec(score.accuracy)}  coverage {_dec(score.coverage)}"


def report_text(scenario: Scenario, world: World, report: ScreeningReport, scores: list[TheoryScore], top: int) -> str:
    criteria = scenario.acceptance_criteria
    nobel = criteria.nobel_grade
    lines = [
        f"World for scenario {world.scenario_id}: seed {world.seed} "
        f"(requested {world.requested_seed}, {world.tries} {'try' if world.tries == 1 else 'tries'})",
        "Acceptance criteria: " + ("passed" if report.passed else "FAILED: " + ", ".join(report.failed)),
        "",
        f"Base rates (criterion: at most {_dec(criteria.max_base_rate)}):",
    ]
    for outcome in scenario.world_outcomes:
        rates = ", ".join(f"{s} {_dec(r)}" for s, r in report.base_rates[outcome.id].items())
        lines.append(f"  {outcome.id} {outcome.name}: {rates}")

    counts = report.nobel_counts
    lines += [
        "",
        f"Nobel-grade theories (at most {nobel.max_input_parameters} input parameters, "
        f"accuracy at least {_dec(nobel.min_accuracy)}):",
        f"  input patterns {counts['input_patterns']}, theories {counts['theories']}, "
        f"maximal theories {counts['maximal_theories']}",
        f"  criterion: {nobel.count} between {nobel.min_count} and {nobel.max_count}",
    ]
    for score in sorted(report.nobel_grade, key=lambda s: (s.theory.n_inputs, -s.accuracy, s.theory.label())):
        lines.append("    " + _describe_theory(scenario, score))

    lines += ["", "Best theories by number of input parameters:"]
    for n, best in report.best_accuracy_by_inputs.items():
        note = f" (criterion: at most {_dec(criteria.max_one_input_theory_accuracy)})" if n == 1 else ""
        lines.append(f"  {n} input parameter{'s' if n > 1 else ''}: best accuracy {_dec(best)}{note}")
        for score in best_theories(scores, n, top):
            lines.append("    " + _describe_theory(scenario, score))
    return "\n".join(lines)


def write_csvs(scenario: Scenario, world: World, report: ScreeningReport, scores: list[TheoryScore], top: int, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)

    def write(name: str, header: list[str], rows: list[list]) -> None:
        with open(folder / name, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)

    write(
        "base_rates.csv",
        ["outcome", "outcome_name", "state", "base_rate", "base_rate_exact"],
        [
            [o.id, o.name, state, float(rate), str(rate)]
            for o in scenario.world_outcomes
            for state, rate in report.base_rates[o.id].items()
        ],
    )
    write(
        "best_theories.csv",
        ["n_inputs", "rank", "theory", "n_outcomes", "accuracy", "coverage"],
        [
            [n, rank, s.theory.label(), s.theory.n_outcomes, float(s.accuracy), float(s.coverage)]
            for n in report.best_accuracy_by_inputs
            for rank, s in enumerate(best_theories(scores, n, top), start=1)
        ],
    )
    write(
        "nobel_grade.csv",
        ["theory", "n_inputs", "n_outcomes", "accuracy", "coverage"],
        [
            [s.theory.label(), s.theory.n_inputs, s.theory.n_outcomes, float(s.accuracy), float(s.coverage)]
            for s in report.nobel_grade
        ],
    )
    header, row = world_summary(scenario, world, report)
    write("summary.csv", header, [row])


def world_summary(scenario: Scenario, world: World, report: ScreeningReport) -> tuple[list[str], list]:
    """One summary row of a world (also the row shape of the simulator's worlds.csv)."""
    best_columns = [f"best_accuracy_{n}_inputs" for n in report.best_accuracy_by_inputs]
    rate_columns = [f"base_rate_{o.id}_{state}" for o in scenario.world_outcomes for state in o.states]
    header = ["scenario_id", "requested_seed", "seed", "tries", "passed", *rate_columns, *best_columns,
              "nobel_theories", "nobel_input_patterns", "nobel_maximal_theories"]
    row = [
        world.scenario_id, world.requested_seed, world.seed, world.tries, report.passed,
        *(float(report.base_rates[o.id][state]) for o in scenario.world_outcomes for state in o.states),
        *(float(a) for a in report.best_accuracy_by_inputs.values()),
        report.nobel_counts["theories"], report.nobel_counts["input_patterns"],
        report.nobel_counts["maximal_theories"],
    ]
    return header, row


def _generate(args: argparse.Namespace) -> int:
    scenario = load_scenario(Path(args.scenario))
    try:
        world = generate_world(scenario, args.seed)
    except GenerationFailed as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else Path(args.scenario).parent / "worlds" / f"world_seed{args.seed}.json"
    save_world(world, out)
    scores = score_all(scenario, world.rows)
    print(report_text(scenario, world, world.screening, scores, DEFAULT_TOP))
    print(f"\nWorld file: {out}")
    return 0


def _report(args: argparse.Namespace) -> int:
    world_path = Path(args.world)
    world = load_world(world_path)
    scenario_path = Path(args.scenario) if args.scenario else SCENARIOS_DIR / world.scenario_id / "scenario.md"
    scenario = load_scenario(scenario_path)
    if scenario_changed(world, scenario):
        print(
            f"warning: the data in {scenario_path} changed after this world was generated; "
            "the report uses the current scenario file",
            file=sys.stderr,
        )
    try:
        check_rows(scenario, world.rows)
    except ValueError as exc:
        print(f"error: the world's table no longer fits {scenario_path}: {exc}", file=sys.stderr)
        return 1
    scores = score_all(scenario, world.rows)
    report = screen(scenario, world.rows, scores)
    print(report_text(scenario, world, report, scores, args.top))
    folder = Path(args.csv_dir) if args.csv_dir else world_path.parent / f"{world_path.stem}_report"
    write_csvs(scenario, world, report, scores, args.top, folder)
    print(f"\nCSV files: {folder}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nv-world", description="Null & Void world generator")
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate", help="generate and screen a world")
    generate.add_argument("scenario", help="scenario file (scenarios/<id>/scenario.md)")
    generate.add_argument("--seed", type=int, required=True)
    generate.add_argument("--out", help="world file to write (default: <scenario folder>/worlds/world_seed<N>.json)")
    generate.set_defaults(func=_generate)

    report = commands.add_parser("report", help="report on a world file")
    report.add_argument("world", help="world file (JSON)")
    report.add_argument("--scenario", help="scenario file (default: scenarios/<scenario_id>/scenario.md)")
    report.add_argument("--csv-dir", help="folder for the CSV files (default: next to the world file)")
    report.add_argument("--top", type=int, default=DEFAULT_TOP, help="theories listed per number of inputs")
    report.set_defaults(func=_report)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ScenarioError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""The headless balance simulator (specification section 9).

    nv-sim run --players 4 --games 100 --seed 42 --out results/run01
    nv-sim run --world scenarios/venus_expedition/worlds/world_seed1.json --sweep nobel_condition=4,5,6 ...
    nv-sim record results/run01 17 --save games/run01_game17.json   (then: nv-play load ...)

Every game's seed and settings are written to games.csv and run.json, so any game can be rebuilt
exactly with ``nv-sim record`` and replayed in the text client.
"""

import argparse
import csv
import itertools
import json
import math
import os
import random
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import yaml

from nv_core.paths import SCENARIOS_DIR
from nv_core.settings import SettingsError, load_settings
from nv_sim.game import AIContext, GameReport, check_seat_types, play_game
from nv_world.cli import world_summary
from nv_world.game import world_data
from nv_world.generate import GenerationFailed, generate_world
from nv_world.scenario import load_scenario
from nv_world.worldfile import load_world

CSV_FILES = ("games.csv", "rounds.csv", "theories.csv", "predictions.csv", "worlds.csv", "ai_decisions.csv")


def has_ai(seats: list[str]) -> bool:
    return any(s.split(":")[0] == "ai" for s in seats)


def ai_context() -> AIContext:
    """Settings, ledger and provider for AI seats; raises ValueError when the key is missing."""
    from nv_ai.config import SPENDING_LEDGER, load_software_settings, require_api_key
    from nv_ai.costs import Ledger
    from nv_ai.provider import make_provider

    software = load_software_settings()
    require_api_key(software.ai_provider)
    ledger = Ledger(SPENDING_LEDGER, software.ai_total_budget)
    return AIContext(
        software,
        ledger,
        lambda: make_provider(software.ai_provider, software.ai_default_model, software.ai_reasoning_effort),
    )


# Configuration -------------------------------------------------------------------------------
def _scenario_path(value: str) -> Path:
    path = Path(value)
    if path.suffix == ".md":
        return path
    return SCENARIOS_DIR / value / "scenario.md"


def _parse_assignment(text: str, many: bool) -> tuple[str, Any]:
    if "=" not in text:
        raise ValueError(f"expected name=value, got {text!r}")
    name, value = text.split("=", 1)
    if many:
        return name, [yaml.safe_load(v) for v in value.split(",")]
    return name, yaml.safe_load(value)


def _combinations(sets: list[str], sweeps: list[str]) -> list[dict[str, Any]]:
    fixed = dict(_parse_assignment(s, many=False) for s in sets)
    swept = dict(_parse_assignment(s, many=True) for s in sweeps)
    names = list(swept)
    return [{**fixed, **dict(zip(names, values))} for values in itertools.product(*swept.values())] or [fixed]


def game_seed(base: int, combination: int, game: int) -> int:
    return random.Random(f"{base}/{combination}/{game}").randrange(2**31)


# One game in a worker process -----------------------------------------------------------------
def _job(job: dict[str, Any]) -> dict[str, Any]:
    scenario = load_scenario(Path(job["scenario"]))
    overrides = {**scenario.parameter_overrides, **job["overrides"]}
    settings = load_settings(overrides)
    world_row = None
    if job["world"]:
        world_file = load_world(Path(job["world"]))
        world = world_data(scenario, world_file, Path(job["world"]).stem)
    else:
        try:
            world_file = generate_world(scenario, job["seed"])
        except GenerationFailed as exc:
            return {"index": job["index"], "error": f"world generation failed: {exc}"}
        world = world_data(scenario, world_file, f"generated_seed{job['seed']}")
        world_row = world_summary(scenario, world_file, world_file.screening)
    ai = job.get("ai_context") or (ai_context() if has_ai(job["seats"]) else None)
    report: GameReport = play_game(
        world, settings, job["seed"], job["seats"], max_actions=job["max_actions"], ai=ai, keep_record=ai is not None
    )
    if report.record is not None and job.get("records_dir"):
        report.record.save(Path(job["records_dir"]) / f"game{job['index'] + 1}.json")
        report.record = None
    return {"index": job["index"], "report": report, "world_row": world_row}


# Output --------------------------------------------------------------------------------------
def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns: list[str] = []
    for row in rows:
        columns += [c for c in row if c not in columns]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval of a proportion (Wilson score interval)."""
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def summary_text(games: list[dict[str, Any]]) -> str:
    lines = []
    for combination in sorted({g["combination"] for g in games}):
        mine = [g for g in games if g["combination"] == combination]
        settings = mine[0]["settings"] or "defaults"
        lines.append(f"Settings: {settings} ({len(mine)} games)")
        counts = Counter(g["ending"] for g in mine)
        for ending, count in counts.most_common():
            low, high = wilson(count, len(mine))
            lines.append(f"  {ending:<13} {count / len(mine):6.1%}  (95% CI {low:.1%} - {high:.1%})")
        finished = [g["rounds"] for g in mine if g["ending"] != "error"]
        if finished:
            lines.append(f"  median game length: {statistics.median(finished):g} rounds")
    return "\n".join(lines)


# Commands ------------------------------------------------------------------------------------
def _run(args: argparse.Namespace) -> int:
    scenario_path = _scenario_path(args.scenario)
    scenario = load_scenario(scenario_path)
    seats = args.seats.split(",") if args.seats else ["random"] * args.players
    if len(seats) != args.players:
        print(f"error: {len(seats)} seat types for {args.players} players", file=sys.stderr)
        return 2
    ai = None
    try:
        check_seat_types(seats)
        if has_ai(seats):
            ai = ai_context()
        combinations = _combinations(args.set or [], args.sweep or [])
        for overrides in combinations:
            settings = load_settings({**scenario.parameter_overrides, **overrides})
            if not settings.min_players <= args.players <= settings.max_players:
                raise ValueError(f"{args.players} players is outside min_players/max_players")
    except (ValueError, SettingsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    max_cost = None
    if ai is not None:
        max_cost = min(args.max_cost, ai.ledger.remaining) if args.max_cost is not None else ai.ledger.remaining
        n_ai = sum(1 for s in seats if s.split(":")[0] == "ai")
        print(
            f"AI seats: {n_ai} per game, model {ai.software.ai_default_model}. Spent so far: "
            f"{ai.ledger.total:.2f} of {ai.software.ai_total_budget:.2f} USD (ai_total_budget). "
            f"This run stops once it has spent {max_cost:.2f} USD; at most "
            f"{ai.software.ai_max_cost_per_decision:.2f} USD per decision."
        )
        if not args.yes and input("Start? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Not started.")
            return 2

    jobs = []
    for c, overrides in enumerate(combinations):
        for g in range(args.games):
            jobs.append(
                {
                    "index": len(jobs),
                    "combination": c,
                    "overrides": overrides,
                    "seed": game_seed(args.seed, c, g),
                    "seats": seats,
                    "scenario": str(scenario_path),
                    "world": args.world,
                    "max_actions": args.max_actions,
                    "records_dir": str(out / "records") if ai is not None else None,
                }
            )
    config = {
        "scenario": str(scenario_path),
        "world": args.world,
        "players": args.players,
        "seats": seats,
        "seed": args.seed,
        "games_per_combination": args.games,
        "combinations": combinations,
        "max_actions": args.max_actions,
        "games": [{"game": j["index"] + 1, "seed": j["seed"], "combination": j["combination"]} for j in jobs],
    }
    (out / "run.json").write_text(json.dumps(config, indent=1) + "\n", encoding="utf-8")

    started = time.time()
    results: list[dict[str, Any]] = [None] * len(jobs)  # type: ignore[list-item]
    jobs_count = 1 if ai is not None else (args.jobs or os.cpu_count() or 1)  # one ledger: AI games run in turn
    print(f"Running {len(jobs)} game(s) on {jobs_count} process(es)...", flush=True)
    if jobs_count == 1:
        run_start = ai.ledger.total if ai is not None else 0.0
        for done, job in enumerate(jobs, start=1):
            if ai is not None and (ai.ledger.total - run_start >= max_cost or ai.ledger.remaining <= 0):
                print(f"Stopped before game {job['index'] + 1}: the cost limit is reached.")
                jobs, results = jobs[: done - 1], results[: done - 1]
                break
            results[job["index"]] = _job({**job, "ai_context": ai})
            _progress(done, len(jobs))
            if ai is not None:
                print(f"    game {job['index'] + 1}: AI cost {results[job['index']]['report'].game['ai_cost']:.4f} USD; "
                      f"total spent {ai.ledger.total:.4f} USD", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=jobs_count) as pool:
            for done, result in enumerate(pool.map(_job, jobs, chunksize=1), start=1):
                results[result["index"]] = result
                _progress(done, len(jobs))

    games, rounds, theories, predictions, worlds, decisions = [], [], [], [], [], []
    world_rows: dict[str, list] = {}
    if args.world:
        world_file = load_world(Path(args.world))
        header, row = world_summary(scenario, world_file, world_file.screening)
        worlds.append({"world": Path(args.world).stem, **dict(zip(header, row))})
    errors = 0
    for job, result in zip(jobs, results):
        game_number = job["index"] + 1
        settings_text = ", ".join(f"{k}={v}" for k, v in job["overrides"].items())
        base = {"game": game_number}
        if "error" in result:
            errors += 1
            games.append({**base, "seed": job["seed"], "combination": job["combination"], "settings": settings_text,
                          "ending": "error", "error": result["error"], "rounds": 0})
            continue
        report: GameReport = result["report"]
        if report.errors:
            errors += 1
        games.append({**base, "combination": job["combination"], "settings": settings_text, **job["overrides"], **report.game})
        rounds += [{**base, **row} for row in report.rounds]
        theories += [{**base, **row} for row in report.theories]
        predictions += [{**base, **row} for row in report.predictions]
        decisions += [{**base, **{k: (";".join(v) if isinstance(v, list) else v) for k, v in row.items()}}
                      for row in report.ai_decisions]
        if result["world_row"] is not None:
            header, row = result["world_row"]
            world_rows[report.game["world"]] = [report.game["world"], *row]
            worlds_header = ["world", *header]
    for row in world_rows.values():
        worlds.append(dict(zip(worlds_header, row)))
    for name, rows in zip(CSV_FILES, (games, rounds, theories, predictions, worlds, decisions)):
        if rows or name != "ai_decisions.csv":
            _write_csv(out / name, rows)

    print()
    print(summary_text(games))
    print(f"{len(games)} game(s) in {time.time() - started:.0f} s; {errors} with errors. CSV files in {out}")
    if ai is not None:
        total = sum(g.get("ai_cost", 0.0) or 0.0 for g in games)
        print(f"AI cost of this run: {total:.4f} USD ({len(decisions)} decisions); "
              f"total spent: {ai.ledger.total:.4f} of {ai.software.ai_total_budget:.2f} USD")
    return 1 if errors else 0


def _progress(done: int, total: int) -> None:
    if done == total or done % max(1, total // 20) == 0:
        print(f"  {done}/{total} games", flush=True)


def _record(args: argparse.Namespace) -> int:
    """Rebuild one game of a run exactly, as a record the text client can load."""
    out = Path(args.run)
    config = json.loads((out / "run.json").read_text(encoding="utf-8"))
    entry = next((g for g in config["games"] if g["game"] == args.game), None)
    if entry is None:
        print(f"error: the run has no game {args.game}", file=sys.stderr)
        return 2
    saved = out / "records" / f"game{args.game}.json"
    if has_ai(config["seats"]):  # model replies cannot be replayed from a seed: use the saved actions
        if not saved.exists():
            print(f"error: no saved record {saved}", file=sys.stderr)
            return 2
        save = Path(args.save) if args.save else Path("games") / f"{out.name}_game{args.game}.json"
        save.parent.mkdir(parents=True, exist_ok=True)
        save.write_bytes(saved.read_bytes())
        print(f"Game {args.game} copied to {save}")
        print(f"Replay it with: nv-play load {save}")
        return 0
    scenario = load_scenario(Path(config["scenario"]))
    overrides = config["combinations"][entry["combination"]]
    settings = load_settings({**scenario.parameter_overrides, **overrides})
    if config["world"]:
        world = world_data(scenario, load_world(Path(config["world"])), Path(config["world"]).stem)
    else:
        world = world_data(scenario, generate_world(scenario, entry["seed"]), f"generated_seed{entry['seed']}")
    report = play_game(world, settings, entry["seed"], config["seats"], max_actions=config["max_actions"], keep_record=True)
    save = Path(args.save) if args.save else Path("games") / f"{out.name}_game{args.game}.json"
    report.record.save(save)
    print(f"Game {args.game} ({report.game['ending']}, {report.game['rounds']} rounds) saved to {save}")
    print(f"Replay it with: nv-play load {save}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nv-sim", description="Headless balance simulator for Null & Void.")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="play a batch of games and write CSV files")
    run.add_argument("--scenario", default="venus_expedition", help="scenario id or scenario file")
    run.add_argument("--players", type=int, default=4)
    run.add_argument("--seats", help="comma-separated seat types: random, ai or ai:<persona> (default: all random)")
    run.add_argument("--games", type=int, default=100, help="games per settings combination")
    run.add_argument("--seed", type=int, default=1)
    run.add_argument("--world", help="play every game on this world file (default: a fresh world per game)")
    run.add_argument("--set", action="append", metavar="NAME=VALUE", help="change a game setting")
    run.add_argument("--sweep", action="append", metavar="NAME=V1,V2", help="run every combination of these values")
    run.add_argument("--out", required=True, help="folder for the CSV files")
    run.add_argument("--jobs", type=int, help="parallel processes (default: one per CPU)")
    run.add_argument("--max-actions", type=int, default=20000, help="a game with more actions counts as stalled")
    run.add_argument("--max-cost", type=float, help="with AI seats: stop the run once it has spent this many USD")
    run.add_argument("--yes", action="store_true", help="with AI seats: start without asking")
    record = commands.add_parser("record", help="rebuild one game of a run for the text client")
    record.add_argument("run", help="the run's output folder")
    record.add_argument("game", type=int, help="game number (from games.csv)")
    record.add_argument("--save", help="where to save the game (default: games/<run>_game<N>.json)")
    args = parser.parse_args(argv)
    return _run(args) if args.command == "run" else _record(args)


if __name__ == "__main__":
    raise SystemExit(main())

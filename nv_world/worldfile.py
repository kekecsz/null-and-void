"""World files (specification section 4.4): JSON, with fractions stored as exact "n/d" strings."""

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

from nv_world.generate import Interaction, MainEffect, World
from nv_world.scenario import Scenario
from nv_world.screening import Row, ScreeningReport, Theory, TheoryScore

FORMAT_VERSION = 1


def _fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _theory_score_json(score: TheoryScore) -> dict[str, Any]:
    return {
        "inputs": score.theory.inputs,
        "outcomes": score.theory.outcomes,
        "coverage": _fraction_text(score.coverage),
        "accuracy": _fraction_text(score.accuracy),
    }


def _screening_json(report: ScreeningReport) -> dict[str, Any]:
    return {
        "passed": report.passed,
        "failed": report.failed,
        "base_rates": {
            outcome: {state: _fraction_text(rate) for state, rate in states.items()}
            for outcome, states in report.base_rates.items()
        },
        "best_accuracy_by_inputs": {str(n): _fraction_text(a) for n, a in report.best_accuracy_by_inputs.items()},
        "nobel_counts": report.nobel_counts,
        "nobel_grade": [_theory_score_json(s) for s in report.nobel_grade],
    }


def world_to_json(world: World) -> dict[str, Any]:
    return {
        "format_version": FORMAT_VERSION,
        "scenario_id": world.scenario_id,
        "yaml_hash": world.yaml_hash,
        "requested_seed": world.requested_seed,
        "seed": world.seed,
        "tries": world.tries,
        "main_effects": [vars(e) for e in world.main_effects],
        "interactions": [vars(i) for i in world.interactions],
        "rows": [
            {"inputs": r.inputs, "outcomes": r.outcomes, "probabilities": r.probabilities} for r in world.rows
        ],
        "screening": _screening_json(world.screening) if world.screening else None,
    }


def _screening_from_json(data: dict[str, Any]) -> ScreeningReport:
    return ScreeningReport(
        base_rates={
            outcome: {state: Fraction(rate) for state, rate in states.items()}
            for outcome, states in data["base_rates"].items()
        },
        best_accuracy_by_inputs={int(n): Fraction(a) for n, a in data["best_accuracy_by_inputs"].items()},
        nobel_grade=[
            TheoryScore(Theory(s["inputs"], s["outcomes"]), Fraction(s["coverage"]), Fraction(s["accuracy"]))
            for s in data["nobel_grade"]
        ],
        nobel_counts=dict(data["nobel_counts"]),
        failed=list(data["failed"]),
    )


def world_from_json(data: dict[str, Any]) -> World:
    if data.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"unsupported world file format_version {data.get('format_version')!r}")
    return World(
        scenario_id=data["scenario_id"],
        yaml_hash=data["yaml_hash"],
        requested_seed=data["requested_seed"],
        seed=data["seed"],
        tries=data["tries"],
        main_effects=[MainEffect(**e) for e in data["main_effects"]],
        interactions=[Interaction(**i) for i in data["interactions"]],
        rows=[Row(r["inputs"], r["outcomes"], r["probabilities"]) for r in data["rows"]],
        screening=_screening_from_json(data["screening"]) if data["screening"] else None,
    )


def save_world(world: World, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(world_to_json(world), indent=1, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def load_world(path: Path) -> World:
    return world_from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def scenario_changed(world: World, scenario: Scenario) -> bool:
    """True when the scenario's YAML data differs from the data the world was generated from."""
    return world.yaml_hash != scenario.yaml_hash

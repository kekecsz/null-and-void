"""Reading and validating a scenario file (specification section 4.1).

The scenario's values live in the first fenced ``yaml`` block of scenarios/<id>/scenario.md.
The pydantic models below define only the shape of that block; the values come from the file.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, StrictBool, StrictFloat, StrictInt, ValidationError

from nv_core.markdown_text import section_text
from nv_core.paths import PARAMETER_DEFAULTS
from nv_core.settings import Settings, SettingsError, load_settings

_YAML_BLOCK = re.compile(r"^```yaml[ \t]*\r?\n(.*?)^```", re.MULTILINE | re.DOTALL)
_URN_ENTRY = re.compile(r"^([+-])(\w+)$")


class ScenarioError(ValueError):
    """The scenario data is incomplete or inconsistent. The message names the field."""


def _exact_fraction(value: Any) -> Fraction:
    """A number written in the YAML, as the exact fraction of its decimal (0.90 -> 9/10)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Fraction)):
        raise ValueError("must be a number")
    return value if isinstance(value, Fraction) else Fraction(str(value))


def _share(value: Any) -> Fraction:
    fraction = _exact_fraction(value)
    if not 0 <= fraction <= 1:
        raise ValueError("must be between 0 and 1")
    return fraction


Share = Annotated[Fraction, BeforeValidator(_share)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)


class ScenarioInfo(_Strict):
    id: str
    title: str


class _VariableData(_Strict):
    id: str
    name: str
    states: list[str]


class EffectModel(_Strict):
    effect_sizes_logit: dict[str, StrictInt | StrictFloat]
    main_effect_urn: list[str]
    reference_state_per_outcome: StrictBool
    interactions: list[str]
    interaction_sign: Literal["random", "positive", "negative"]
    max_interactions_per_outcome_state: StrictInt
    outcome_realisation: Literal["draw_once"]


class NobelGrade(_Strict):
    min_accuracy: Share
    max_input_parameters: StrictInt
    count: Literal["theories", "input_patterns", "maximal_theories"]
    min_count: StrictInt
    max_count: StrictInt


class AcceptanceCriteria(_Strict):
    max_base_rate: Share
    max_one_input_theory_accuracy: Share
    nobel_grade: NobelGrade
    max_generation_tries: StrictInt


class _ScenarioData(_Strict):
    scenario: ScenarioInfo
    input_parameters: list[_VariableData]
    world_outcomes: list[_VariableData]
    effect_model: EffectModel
    acceptance_criteria: AcceptanceCriteria
    parameter_overrides: dict[str, Any] = {}


@dataclass(frozen=True)
class Variable:
    """An input parameter or a world outcome."""

    id: str
    name: str
    states: list[str]


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    story: str
    input_parameters: list[Variable]
    world_outcomes: list[Variable]
    effect_model: EffectModel
    acceptance_criteria: AcceptanceCriteria
    parameter_overrides: dict[str, Any]
    settings: Settings
    yaml_hash: str
    path: Path | None = None

    def variable(self, variable_id: str) -> Variable:
        for variable in self.input_parameters + self.world_outcomes:
            if variable.id == variable_id:
                return variable
        raise KeyError(variable_id)


def _location(loc: tuple) -> str:
    text = ""
    for item in loc:
        text += f"[{item}]" if isinstance(item, int) else (f".{item}" if text else str(item))
    return text


def yaml_hash(data: Any) -> str:
    """SHA-256 of the parsed YAML data, so comments and layout don't change it."""
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def extract_yaml_block(text: str) -> str:
    match = _YAML_BLOCK.search(text)
    if not match:
        raise ScenarioError("scenario file: no fenced yaml block found")
    return match.group(1)


def _check_variables(data: _ScenarioData) -> None:
    if not data.input_parameters:
        raise ScenarioError("input_parameters: at least one input parameter is needed")
    if not data.world_outcomes:
        raise ScenarioError("world_outcomes: at least one world outcome is needed")
    seen_ids: set[str] = set()
    for group, variables in (("input_parameters", data.input_parameters), ("world_outcomes", data.world_outcomes)):
        for index, variable in enumerate(variables):
            where = f"{group}[{index}]"
            if variable.id in seen_ids:
                raise ScenarioError(f"{where}.id: duplicated id {variable.id!r}")
            seen_ids.add(variable.id)
            if not variable.states:
                raise ScenarioError(f"{where}.states: no states")
            duplicates = sorted({s for s in variable.states if variable.states.count(s) > 1})
            if duplicates:
                raise ScenarioError(f"{where}.states: duplicated state name(s) {duplicates}")


def _check_effect_model(data: _ScenarioData) -> None:
    model = data.effect_model
    sizes = model.effect_sizes_logit
    if not sizes:
        raise ScenarioError("effect_model.effect_sizes_logit: no effect sizes")
    for index, entry in enumerate(model.main_effect_urn):
        match = _URN_ENTRY.match(entry)
        if not match:
            raise ScenarioError(
                f"effect_model.main_effect_urn[{index}]: {entry!r} is not a sign (+/-) followed by a size name"
            )
        if match.group(2) not in sizes:
            raise ScenarioError(f"effect_model.main_effect_urn[{index}]: unknown effect size {match.group(2)!r}")
    n_input_states = sum(len(p.states) for p in data.input_parameters)
    if len(model.main_effect_urn) > n_input_states:
        raise ScenarioError(
            f"effect_model.main_effect_urn: {len(model.main_effect_urn)} entries "
            f"but only {n_input_states} input states"
        )
    for index, size in enumerate(model.interactions):
        if size not in sizes:
            raise ScenarioError(f"effect_model.interactions[{index}]: unknown effect size {size!r}")
    if model.max_interactions_per_outcome_state < 0:
        raise ScenarioError("effect_model.max_interactions_per_outcome_state: must not be negative")
    if model.interactions:
        if len(data.input_parameters) < 2:
            raise ScenarioError("effect_model.interactions: need at least two input parameters")
        skip = 1 if model.reference_state_per_outcome else 0
        eligible = sum(len(o.states) - skip for o in data.world_outcomes)
        capacity = eligible * model.max_interactions_per_outcome_state
        if len(model.interactions) > capacity:
            raise ScenarioError(
                f"effect_model.interactions: {len(model.interactions)} interactions but the outcome states "
                f"can take at most {capacity} (max_interactions_per_outcome_state)"
            )


def _check_acceptance_criteria(data: _ScenarioData) -> None:
    criteria = data.acceptance_criteria
    nobel = criteria.nobel_grade
    if nobel.max_input_parameters < 1:
        raise ScenarioError("acceptance_criteria.nobel_grade.max_input_parameters: must be at least 1")
    if nobel.min_count < 0 or nobel.min_count > nobel.max_count:
        raise ScenarioError("acceptance_criteria.nobel_grade.min_count: must be between 0 and max_count")
    if criteria.max_generation_tries < 1:
        raise ScenarioError("acceptance_criteria.max_generation_tries: must be at least 1")


def _check_deck_divisibility(data: _ScenarioData, settings: Settings) -> None:
    deck = settings.input_parameter_deck_size
    for index, parameter in enumerate(data.input_parameters):
        if deck % len(parameter.states):
            raise ScenarioError(
                f"input_parameters[{index}].states: input_parameter_deck_size ({deck}) is not divisible "
                f"by the {len(parameter.states)} states of {parameter.id}"
            )


def parse_scenario(text: str, parameter_defaults: Path = PARAMETER_DEFAULTS, path: Path | None = None) -> Scenario:
    """Parse and validate the text of a scenario file."""
    try:
        raw = yaml.safe_load(extract_yaml_block(text))
    except yaml.YAMLError as exc:
        raise ScenarioError(f"yaml block: not valid YAML ({exc})") from None
    if not isinstance(raw, dict):
        raise ScenarioError("yaml block: expected a mapping")
    if raw.get("parameter_overrides") is None:
        raw["parameter_overrides"] = {}
    try:
        data = _ScenarioData.model_validate(raw)
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            where = _location(error["loc"])
            message = {"missing": "missing", "extra_forbidden": "unknown field"}.get(error["type"], error["msg"])
            problems.append(f"{where}: {message}")
        raise ScenarioError("; ".join(problems)) from None

    _check_variables(data)
    _check_effect_model(data)
    _check_acceptance_criteria(data)
    try:
        settings = load_settings(data.parameter_overrides, parameter_defaults)
    except SettingsError as exc:
        raise ScenarioError(str(exc)) from None
    _check_deck_divisibility(data, settings)

    input_parameters = [Variable(p.id, p.name, list(p.states)) for p in data.input_parameters]
    world_outcomes = [Variable(o.id, o.name, list(o.states)) for o in data.world_outcomes]
    try:
        story = section_text(text, "Story").strip()
    except KeyError:
        story = ""
    return Scenario(
        id=data.scenario.id,
        title=data.scenario.title,
        story=story,
        input_parameters=input_parameters,
        world_outcomes=world_outcomes,
        effect_model=data.effect_model,
        acceptance_criteria=data.acceptance_criteria,
        parameter_overrides=dict(data.parameter_overrides),
        settings=settings,
        yaml_hash=yaml_hash(raw),
        path=path,
    )


def load_scenario(path: Path, parameter_defaults: Path = PARAMETER_DEFAULTS) -> Scenario:
    """Read and validate scenarios/<id>/scenario.md (or any scenario file)."""
    path = Path(path)
    return parse_scenario(path.read_text(encoding="utf-8"), parameter_defaults, path)

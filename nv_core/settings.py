"""Game settings: docs/parameter_defaults.yaml, then overrides (specification section 11).

The model below is only the *schema* (names and types); every value comes from the YAML file.
What each setting does is in the rulebook.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, ValidationError, model_validator

from nv_core.paths import PARAMETER_DEFAULTS


class SettingsError(ValueError):
    """A setting is missing, unknown or has the wrong type. The message names it."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GrantPosition(_Strict):
    funding: StrictInt
    admin: StrictInt
    expected_to_maintain: StrictInt
    expected_to_increase: StrictInt | None


class JournalTier(_Strict):
    min_records: StrictInt
    min_observations: StrictInt
    min_experiments: StrictInt
    min_elements: StrictInt
    rounds_in_processing: StrictInt
    peer_review: StrictBool
    methods_accepted: StrictBool
    submission_fee: StrictInt
    apc: StrictInt


class Settings(_Strict):
    # Players
    min_players: StrictInt
    max_players: StrictInt
    # Staff
    cost_of_postdoc: StrictInt
    student_base_hire_cap: StrictInt
    student_unassigned_base_threshold: StrictInt
    unpaid_postdoc_penalty: StrictInt
    fired_postdoc_penalty: StrictInt
    unused_staff_penalty: StrictInt
    # Starting positions
    starting_academic_credit: StrictInt
    talent_development_track_starting_position: StrictInt
    grant_track_starting_position: StrictInt
    talent_track_max: StrictInt
    # Game Period Deck
    calm_cards_per_player_top: StrictInt
    calm_cards_per_player_warning: StrictInt
    calm_cards_per_player_crisis: StrictInt
    # Probes and sensors
    probe_deck_copies: StrictInt
    probe_deck_min_rebuild_stacks: StrictInt
    input_parameter_deck_size: StrictInt
    probe_true_input_deck_size: StrictInt
    probe_fake_input_deck_size: StrictInt
    sensor_install_and_upgrade_AC_reward: StrictInt
    # Experiments and methods
    experiment_free_input_parameters: StrictInt
    experiment_method_citation_AC_reward: StrictInt
    # Predictions
    citation_reward: StrictInt
    failed_non_prereg_pred_ac: StrictInt
    failed_prereg_pred_ac: StrictInt
    failed_prereg_pred_ac_crisis: StrictInt
    crisis_failed_pred_citation_penalty: StrictInt
    crisis_pred_base_bonus: StrictInt
    crisis_pred_citation_reward_bonus: StrictInt
    # Nobel Prize and retraction
    nobel_condition: StrictInt
    retraction_threshold: StrictInt
    retraction_ac_penalty: StrictInt
    # Crisis
    crisis_condition: StrictInt
    crisis_length: StrictInt
    # Publication
    submission_portal_positions: StrictInt
    peer_review_random_draws: StrictInt
    min_reviews_for_decision: StrictInt
    OA_publication_AC_reward: StrictInt
    # Funding
    patent_funding: StrictInt
    # Tables
    grant_track: list[GrantPosition]
    journal_tiers: list[JournalTier]

    @model_validator(mode="after")
    def _check_tables(self) -> "Settings":
        if not self.grant_track:
            raise ValueError("grant_track: needs at least one position")
        if not self.journal_tiers:
            raise ValueError("journal_tiers: needs at least one tier")
        # See the grant_track comment in parameter_defaults.yaml.
        for number, position in enumerate(self.grant_track, start=1):
            is_top = number == len(self.grant_track)
            if (position.expected_to_increase is None) != is_top:
                raise ValueError(
                    f"grant_track[{number - 1}].expected_to_increase: must be null only for the top position"
                )
        if not 1 <= self.grant_track_starting_position <= len(self.grant_track):
            raise ValueError("grant_track_starting_position: not a position of grant_track")
        if self.min_players > self.max_players:
            raise ValueError("min_players: larger than max_players")
        return self


def _location(error: dict[str, Any]) -> str:
    parts = []
    for item in error["loc"]:
        if isinstance(item, int):
            parts[-1] = f"{parts[-1]}[{item}]" if parts else f"[{item}]"
        else:
            parts.append(str(item))
    return ".".join(parts)


def _validate(data: dict[str, Any], path: Path, overridden: set[str]) -> Settings:
    """Validate; each problem names its setting and whether it came from the file or an override."""
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            where = _location(error)
            if error["type"] == "missing":
                text = f"{where}: missing"
            elif error["type"] == "extra_forbidden":
                text = f"{where}: unknown setting"
            elif where:
                text = f"{where}: {error['msg']}"
            else:  # raised by a model validator; the message starts with the setting name
                text = error["msg"].removeprefix("Value error, ")
            name = text.split(":", 1)[0].split(".", 1)[0].split("[", 1)[0]
            source = "parameter_overrides" if name in overridden else str(path)
            problems.append(f"{source}: {text}")
        raise SettingsError("; ".join(problems)) from None


def load_settings(overrides: dict[str, Any] | None = None, path: Path = PARAMETER_DEFAULTS) -> Settings:
    """Load the parameter file and apply ``overrides`` (top-level settings replace defaults)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SettingsError(f"{path}: expected a mapping of settings")
    overrides = overrides or {}
    unknown = sorted(set(overrides) - set(data))
    if unknown:
        raise SettingsError(f"parameter_overrides: unknown setting(s) {', '.join(unknown)}")
    return _validate({**data, **overrides}, Path(path), set(overrides))

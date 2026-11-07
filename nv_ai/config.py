"""Software settings for AI players (specification section 11) and API keys.

Values come from settings/software.yaml. API keys come from the environment, or from
settings/api_keys.env (git-ignored); they are never printed or logged.
"""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from nv_core.paths import SETTINGS_DIR

SOFTWARE_SETTINGS = SETTINGS_DIR / "software.yaml"
API_KEYS = SETTINGS_DIR / "api_keys.env"
SPENDING_LEDGER = SETTINGS_DIR / "ai_spending.csv"
KEY_NAMES = {"openai": "OPENAI_API_KEY"}


class Prices(BaseModel):
    """USD per million tokens."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    input: float
    cached_input: float
    cache_write: float
    output: float


class SoftwareSettings(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    ai_provider: str
    ai_default_model: str
    ai_reasoning_effort: str
    ai_max_cost_per_decision: float
    ai_total_budget: float
    ai_max_input_tokens: int
    ai_retry_limit: int
    ai_notes_max_chars: int
    ai_price_table: dict[str, Prices]
    # Scripted strategy bots (specification 9.4)
    bot_confidence_threshold: float
    bot_formulate_threshold: float
    bot_rival_citation_factor: float
    bot_kill_counter: int
    bot_memory_corruption: float
    bot_max_wait_rounds: int

    def prices(self, model: str) -> Prices:
        if model not in self.ai_price_table:
            raise KeyError(f"no prices for model {model!r} in ai_price_table ({SOFTWARE_SETTINGS})")
        return self.ai_price_table[model]


def load_software_settings(path: Path = SOFTWARE_SETTINGS) -> SoftwareSettings:
    return SoftwareSettings.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def load_api_keys(path: Path = API_KEYS) -> None:
    """Put the keys from the key file into the environment (keys already set there win)."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if value and not os.environ.get(name):
            os.environ[name] = value


def require_api_key(provider: str) -> None:
    """Raise a clear error (without the key) when the provider's key is missing."""
    load_api_keys()
    name = KEY_NAMES.get(provider)
    if name is None:
        raise ValueError(f"unknown AI provider {provider!r} (available: {', '.join(KEY_NAMES)})")
    if not os.environ.get(name):
        raise ValueError(f"{name} is not set: paste your key into {API_KEYS}")

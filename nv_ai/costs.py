"""Token use, cost and the spending ledger (specification 8.4)."""

import csv
import threading
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

from nv_ai.config import Prices


@dataclass
class Usage:
    input_tokens: int = 0  # all input, including cached and cache-write tokens
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0  # including reasoning
    reasoning_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(*(getattr(self, f.name) + getattr(other, f.name) for f in fields(self)))


def cost(usage: Usage, prices: Prices) -> float:
    """USD. Each input token is billed at one rate: uncached, cached, or cache write."""
    uncached = max(0, usage.input_tokens - usage.cached_tokens - usage.cache_write_tokens)
    return (
        uncached * prices.input
        + usage.cached_tokens * prices.cached_input
        + usage.cache_write_tokens * prices.cache_write
        + usage.output_tokens * prices.output
    ) / 1_000_000


class Ledger:
    """Every AI call's cost, appended to a CSV file; the total enforces ai_total_budget."""

    COLUMNS = ["time", "game", "seat", "model", *[f.name for f in fields(Usage)], "cost"]

    def __init__(self, path: Path | None, budget: float):
        self.path = Path(path) if path else None
        self.budget = budget
        self._lock = threading.Lock()
        self._total = 0.0
        if self.path and self.path.exists():
            with open(self.path, encoding="utf-8", newline="") as handle:
                self._total = sum(float(row["cost"]) for row in csv.DictReader(handle))

    @property
    def total(self) -> float:
        return self._total

    @property
    def remaining(self) -> float:
        return max(0.0, self.budget - self._total)

    def add(self, game: str, seat: str, model: str, usage: Usage, amount: float) -> None:
        with self._lock:
            self._total += amount
            if not self.path:
                return
            new = not self.path.exists()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                if new:
                    writer.writerow(self.COLUMNS)
                writer.writerow(
                    [datetime.now(timezone.utc).isoformat(timespec="seconds"), game, seat, model,
                     *asdict(usage).values(), f"{amount:.6f}"]
                )

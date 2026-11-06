"""Seeded randomness split into named streams (specification section 5.6).

Each draw seeds a fresh generator from (game seed, stream name, draw number). The game state
only stores the draw counter of each stream, so a state is plain JSON, and replaying the same
seed and actions always gives the same draws, whatever other streams were used in between.
"""

import random
from typing import TypeVar

T = TypeVar("T")

# The named streams. Keeping them separate means that, e.g., an extra experiment does not
# change the next Probe stack that is dealt.
STREAMS = ("setup", "probe_deck", "input_decks", "sensor_noise", "experiments", "dice", "peer_review")


class Rng:
    def __init__(self, seed: int, counters: dict[str, int]):
        self._seed = seed
        self._counters = counters  # the game state's dict, updated in place

    def _generator(self, stream: str) -> random.Random:
        if stream not in STREAMS:
            raise KeyError(f"unknown random stream {stream!r}")
        n = self._counters.get(stream, 0)
        self._counters[stream] = n + 1
        return random.Random(f"{self._seed}/{stream}/{n}")

    def shuffle(self, stream: str, items: list[T]) -> None:
        self._generator(stream).shuffle(items)

    def randint(self, stream: str, low: int, high: int) -> int:
        return self._generator(stream).randint(low, high)

    def dice(self, stream: str, count: int, sides: int = 6) -> list[int]:
        generator = self._generator(stream)
        return [generator.randint(1, sides) for _ in range(count)]

    def choice(self, stream: str, items: list[T]) -> T:
        return self._generator(stream).choice(items)

"""A game's record: its world, settings, seed, players and ordered actions (design principle 3).

The record is all that is saved; the state is rebuilt by replaying it.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nv_core.actions import ACTION_LIST_ADAPTER, Action
from nv_core.engine import replay
from nv_core.settings import Settings
from nv_core.state import GameState
from nv_core.world_data import WorldData

FORMAT_VERSION = 1


class GameRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: int = FORMAT_VERSION
    world: WorldData
    settings: Settings
    seed: int
    players: list[str]
    actions: list[Action] = Field(default_factory=list)

    def replay(self) -> GameState:
        return replay(self.world, self.settings, self.seed, self.players, self.actions)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json")
        data["actions"] = ACTION_LIST_ADAPTER.dump_python(self.actions, mode="json")
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    @classmethod
    def load(cls, path: Path) -> "GameRecord":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("format_version") != FORMAT_VERSION:
            raise ValueError(f"unsupported game record format_version {data.get('format_version')!r}")
        return cls.model_validate(data)

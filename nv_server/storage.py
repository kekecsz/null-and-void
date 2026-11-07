"""Game storage (specification 6.1): one interface, two backends.

The local backend is a SQLite file (milestone 5); Firestore follows in milestone 7 behind the
same interface. A game is stored as:

- its metadata (setup, seats, status, hashed passwords and tokens, AI notes and costs);
- its ordered action log; each action keeps the events it produced, so a game can be loaded
  with its event log without replaying it from the start;
- a state snapshot at the start of each round;
- the AI players' decision log.

An action is stored only under the next sequence number, in a transaction, so the log can never
be corrupted by two writers.
"""

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Protocol


class Storage(Protocol):
    def create_game(self, game_id: str, meta: dict[str, Any]) -> None: ...
    def get_meta(self, game_id: str) -> dict[str, Any] | None: ...
    def update_meta(self, game_id: str, meta: dict[str, Any]) -> None: ...
    def list_games(self) -> list[dict[str, Any]]: ...
    def append_action(self, game_id: str, seq: int, action: dict[str, Any], events: list[dict[str, Any]]) -> bool: ...
    def actions(self, game_id: str) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]: ...
    def save_snapshot(self, game_id: str, seq: int, state: str) -> None: ...
    def latest_snapshot(self, game_id: str) -> tuple[int, str] | None: ...
    def snapshot_before(self, game_id: str, seq: int) -> tuple[int, str] | None: ...
    def add_ai_decision(self, game_id: str, decision: dict[str, Any]) -> None: ...
    def ai_decisions(self, game_id: str) -> list[dict[str, Any]]: ...


SCHEMA = """
CREATE TABLE IF NOT EXISTS games (id TEXT PRIMARY KEY, created REAL NOT NULL, meta TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS actions (
    game_id TEXT NOT NULL, seq INTEGER NOT NULL, action TEXT NOT NULL, events TEXT NOT NULL,
    PRIMARY KEY (game_id, seq)
);
CREATE TABLE IF NOT EXISTS snapshots (
    game_id TEXT NOT NULL, seq INTEGER NOT NULL, state TEXT NOT NULL, PRIMARY KEY (game_id, seq)
);
CREATE TABLE IF NOT EXISTS ai_decisions (
    game_id TEXT NOT NULL, n INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY (game_id, n)
);
"""


class SQLiteStorage:
    """Storage in one SQLite file. Safe to use from several threads of one process."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        if str(path) != ":memory:":
            self._db.execute("PRAGMA journal_mode=WAL")  # readers do not wait for the writer
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # Games ------------------------------------------------------------------------------------
    def create_game(self, game_id: str, meta: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute("INSERT INTO games (id, created, meta) VALUES (?, ?, ?)", (game_id, time.time(), json.dumps(meta)))

    def get_meta(self, game_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT meta FROM games WHERE id = ?", (game_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def update_meta(self, game_id: str, meta: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute("UPDATE games SET meta = ? WHERE id = ?", (json.dumps(meta), game_id))

    def list_games(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT id, created, meta FROM games ORDER BY created DESC").fetchall()
            counts = dict(self._db.execute("SELECT game_id, COUNT(*) FROM actions GROUP BY game_id").fetchall())
        return [{"id": i, "created": c, "meta": json.loads(m), "actions": counts.get(i, 0)} for i, c, m in rows]

    # Action log ---------------------------------------------------------------------------------
    def append_action(self, game_id: str, seq: int, action: dict[str, Any], events: list[dict[str, Any]]) -> bool:
        """Store ``action`` as number ``seq`` (0-based); False if that is not the next number."""
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                (count,) = self._db.execute("SELECT COUNT(*) FROM actions WHERE game_id = ?", (game_id,)).fetchone()
                if count != seq:
                    self._db.execute("ROLLBACK")
                    return False
                self._db.execute(
                    "INSERT INTO actions (game_id, seq, action, events) VALUES (?, ?, ?, ?)",
                    (game_id, seq, json.dumps(action), json.dumps(events)),
                )
                self._db.execute("COMMIT")
                return True
            except sqlite3.Error:
                self._db.execute("ROLLBACK")
                raise

    def actions(self, game_id: str) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
        with self._lock:
            rows = self._db.execute("SELECT action, events FROM actions WHERE game_id = ? ORDER BY seq", (game_id,)).fetchall()
        return [(json.loads(a), json.loads(e)) for a, e in rows]

    # Snapshots ----------------------------------------------------------------------------------
    def save_snapshot(self, game_id: str, seq: int, state: str) -> None:
        """``state`` after ``seq`` actions, as JSON."""
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO snapshots (game_id, seq, state) VALUES (?, ?, ?)", (game_id, seq, state))

    def latest_snapshot(self, game_id: str) -> tuple[int, str] | None:
        with self._lock:
            return self._db.execute(
                "SELECT seq, state FROM snapshots WHERE game_id = ? ORDER BY seq DESC LIMIT 1", (game_id,)
            ).fetchone()

    def snapshot_before(self, game_id: str, seq: int) -> tuple[int, str] | None:
        """The latest snapshot taken after at most ``seq`` actions (for replays)."""
        with self._lock:
            return self._db.execute(
                "SELECT seq, state FROM snapshots WHERE game_id = ? AND seq <= ? ORDER BY seq DESC LIMIT 1", (game_id, seq)
            ).fetchone()

    # AI decisions -------------------------------------------------------------------------------
    def add_ai_decision(self, game_id: str, decision: dict[str, Any]) -> None:
        with self._lock:
            (n,) = self._db.execute("SELECT COUNT(*) FROM ai_decisions WHERE game_id = ?", (game_id,)).fetchone()
            self._db.execute("INSERT INTO ai_decisions (game_id, n, data) VALUES (?, ?, ?)", (game_id, n, json.dumps(decision)))

    def ai_decisions(self, game_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM ai_decisions WHERE game_id = ? ORDER BY n", (game_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

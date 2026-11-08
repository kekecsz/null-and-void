"""Game storage in Firestore (specification 6.1): the deployed backend, same interface as SQLite.

The layout mirrors the SQLite tables. State, metadata and events are kept as JSON text, as in
SQLite, because Firestore cannot store every shape they take (e.g. lists of lists).

Only this module needs the Firestore client library (the ``cloud`` extra of the project).
"""

import json
import threading
import time
from typing import Any, Callable

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

GAMES = "games"
SPENDING = "ai_spending"
TOTAL = "total"


def _number(n: int) -> str:
    """A document name that sorts like the number."""
    return f"{n:010d}"


class FirestoreStorage:
    """Storage in Firestore; also keeps the AI spending total that ``ai_total_budget`` limits, because
    the disk of a Cloud Run instance does not outlive it."""

    def __init__(self, client: Any = None, project: str | None = None):
        self.client = client if client is not None else firestore.Client(project=project)
        self._lock = threading.Lock()
        self._actions: dict[str, list[tuple[dict[str, Any], list[dict[str, Any]]]]] = {}  # append-only, so cacheable

    def _atomic(self, work: Callable[[Any], Any]) -> Any:
        """Run ``work(transaction)`` in a transaction (retried by Firestore on a conflict)."""
        return firestore.transactional(work)(self.client.transaction())

    def _game(self, game_id: str) -> Any:
        return self.client.collection(GAMES).document(game_id)

    def close(self) -> None:
        self.client.close()

    # Games ------------------------------------------------------------------------------------
    def create_game(self, game_id: str, meta: dict[str, Any]) -> None:
        self._game(game_id).set({"created": time.time(), "meta": json.dumps(meta), "actions": 0, "decisions": 0})

    def get_meta(self, game_id: str) -> dict[str, Any] | None:
        snapshot = self._game(game_id).get()
        return json.loads(snapshot.get("meta")) if snapshot.exists else None

    def update_meta(self, game_id: str, meta: dict[str, Any]) -> None:
        self._game(game_id).update({"meta": json.dumps(meta)})

    def list_games(self) -> list[dict[str, Any]]:
        rows = self.client.collection(GAMES).order_by("created", direction=firestore.Query.DESCENDING).stream()
        return [{"id": r.id, "created": r.get("created"), "meta": json.loads(r.get("meta")), "actions": r.get("actions")} for r in rows]

    # Action log ---------------------------------------------------------------------------------
    def append_action(self, game_id: str, seq: int, action: dict[str, Any], events: list[dict[str, Any]]) -> bool:
        """Store ``action`` as number ``seq`` (0-based); False if that is not the next number."""
        game = self._game(game_id)

        def work(transaction: Any) -> bool:
            if game.get(transaction=transaction).get("actions") != seq:
                return False
            transaction.set(game.collection("actions").document(_number(seq)),
                            {"seq": seq, "action": json.dumps(action), "events": json.dumps(events)})
            transaction.update(game, {"actions": seq + 1})
            return True

        return self._atomic(work)

    def actions(self, game_id: str) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
        """Reads only the actions it has not seen yet: replays ask for the whole log at every step."""
        with self._lock:
            known = self._actions.setdefault(game_id, [])
            query = self._game(game_id).collection("actions").where(filter=FieldFilter("seq", ">=", len(known))).order_by("seq")
            known.extend((json.loads(r.get("action")), json.loads(r.get("events"))) for r in query.stream())
            return list(known)

    # Snapshots ----------------------------------------------------------------------------------
    def save_snapshot(self, game_id: str, seq: int, state: str) -> None:
        """``state`` after ``seq`` actions, as JSON."""
        self._game(game_id).collection("snapshots").document(_number(seq)).set({"seq": seq, "state": state})

    def _snapshot(self, query: Any) -> tuple[int, str] | None:
        for row in query.order_by("seq", direction=firestore.Query.DESCENDING).limit(1).stream():
            return row.get("seq"), row.get("state")
        return None

    def latest_snapshot(self, game_id: str) -> tuple[int, str] | None:
        return self._snapshot(self._game(game_id).collection("snapshots"))

    def snapshot_before(self, game_id: str, seq: int) -> tuple[int, str] | None:
        """The latest snapshot taken after at most ``seq`` actions (for replays)."""
        return self._snapshot(self._game(game_id).collection("snapshots").where(filter=FieldFilter("seq", "<=", seq)))

    # AI decisions -------------------------------------------------------------------------------
    def add_ai_decision(self, game_id: str, decision: dict[str, Any]) -> None:
        game = self._game(game_id)

        def work(transaction: Any) -> None:
            n = game.get(transaction=transaction).get("decisions")
            transaction.set(game.collection("ai_decisions").document(_number(n)), {"n": n, "data": json.dumps(decision)})
            transaction.update(game, {"decisions": n + 1})

        self._atomic(work)

    def ai_decisions(self, game_id: str) -> list[dict[str, Any]]:
        return [json.loads(r.get("data")) for r in self._game(game_id).collection("ai_decisions").order_by("n").stream()]

    # AI spending --------------------------------------------------------------------------------
    def spending_total(self) -> float:
        snapshot = self.client.collection(SPENDING).document(TOTAL).get()
        return snapshot.get("cost") if snapshot.exists else 0.0

    def add_spending(self, entry: dict[str, Any], amount: float) -> None:
        total = self.client.collection(SPENDING).document(TOTAL)

        def work(transaction: Any) -> None:
            snapshot = total.get(transaction=transaction)
            transaction.set(total, {"cost": (snapshot.get("cost") if snapshot.exists else 0.0) + amount})
            transaction.set(total.collection("entries").document(), entry)

        self._atomic(work)

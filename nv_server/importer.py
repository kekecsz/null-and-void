"""Import a finished game (e.g. a simulated one, ``nv-sim import``) into the server's storage, so it
opens like any finished game: spectator replay (specification 7.3) and debrief (section 10)."""

import secrets
from typing import Any

from nv_core.actions import ACTION_LIST_ADAPTER
from nv_core.engine import apply, new_game
from nv_core.record import GameRecord
from nv_server.session import GameSetup, new_meta, new_token
from nv_server.storage import Storage


def import_record(record: GameRecord, storage: Storage, title: str, world_model: dict[str, Any] | None = None) -> tuple[str, str]:
    """Replay ``record`` into ``storage`` with its events and a snapshot at every round, as the
    server stores live games. Returns (game id, host token): the host link opens the replay."""
    kinds = list(record.seats) or ["random"] * len(record.players)
    setup = GameSetup(record.world, record.settings, [], record.seed, title, world_model=world_model)
    host = new_token()
    state = new_game(record.world, record.settings, record.seed, record.players)
    game_id = secrets.token_urlsafe(6)
    meta = new_meta(setup, list(record.players), kinds, host, status="finished")
    storage.create_game(game_id, meta)
    storage.save_snapshot(game_id, 0, state.model_dump_json())
    actions = ACTION_LIST_ADAPTER.dump_python(record.actions, mode="json")
    for seq, (action, data) in enumerate(zip(record.actions, actions)):
        before = state.round
        state, events = apply(state, action)
        storage.append_action(game_id, seq, data, [e.model_dump(mode="json") for e in events])
        if state.round != before:
            storage.save_snapshot(game_id, seq + 1, state.model_dump_json())
    if state.result is None:
        meta["status"] = "ended"
        storage.update_meta(game_id, meta)
    return game_id, host

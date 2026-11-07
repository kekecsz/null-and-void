"""Live games on the server (specification 6): lobby, seats, actions, automated seats, views.

Storage (``nv_server.storage``) is the source of truth: every accepted action is stored before
anyone sees its effect, and a game is rebuilt from storage after a restart. The server keeps the
games it is serving in memory (the first version runs as a single instance, specification 6.2).

Each automated seat (scripted bot, random bot or AI) has its own background worker that acts
whenever the seat must decide, so AI seats think in parallel while humans play.
"""

import asyncio
import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from functools import cache

from nv_core.actions import ACTION_ADAPTER
from nv_core.debrief import build_debrief
from nv_core.engine import IllegalAction, apply, legal_actions, new_game
from nv_core.engine.context import Event
from nv_core.settings import Settings
from nv_core.state import GameState
from nv_core.text import render_text
from nv_core.views import player_view, spectator_view, visible_events
from nv_core.world_data import WorldData
from nv_server.storage import Storage
from nv_sim.game import RECENT_EVENTS, check_seat_types, make_player

log = logging.getLogger("nv_server")

HUMAN = "human"
MAX_REFUSALS = 20  # an automated seat refused this often in a row commits or passes instead
EVENTS_SENT = 400  # event log entries sent with each view
COLOURS = ["red", "blue", "green", "orange", "purple", "teal"]
META_VERSION = 1


class GameError(ValueError):
    """A request that cannot be done; the message says why."""


# Secrets ----------------------------------------------------------------------------------------
def new_token() -> str:
    return secrets.token_urlsafe(24)


def token_hash(token: str) -> str:
    """Tokens are long and random, so a plain hash is enough to store them."""
    return hashlib.sha256(token.encode()).hexdigest()


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
    return f"{salt}${digest}"


def password_ok(password: str, stored: str | None) -> bool:
    if not stored:
        return True
    salt, digest = stored.split("$")
    check = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
    return hmac.compare_digest(check, digest)


# Connections ------------------------------------------------------------------------------------
@dataclass(eq=False)
class Connection:
    """One browser: ``seat`` is None for a spectator (specification 7.3)."""

    socket: Any  # has async send_json(data)
    seat: int | None
    host: bool
    spectator: bool = False


@dataclass
class _SeatWorker:
    player: Any
    task: asyncio.Task | None = None
    refusals: int = 0
    stored_decisions: int = 0


class GameSession:
    def __init__(self, game_id: str, meta: dict[str, Any], storage: Storage, ai_context):
        self.id = game_id
        self.meta = meta
        self.storage = storage
        self._ai_context = ai_context  # () -> AIContext, called only when an AI seat needs it
        self.world = WorldData.model_validate(meta["world"])
        self.settings = Settings.model_validate(meta["settings"])
        self.state: GameState | None = None
        self.events: list[Event] = []
        self.seq = 0
        self.cond = asyncio.Condition()
        self.connections: list[Connection] = []
        self.workers: dict[int, _SeatWorker] = {}
        self.closed = False
        self._debrief: tuple[int, dict[str, Any]] | None = None  # (seq, debrief) cache

    # Setup and loading --------------------------------------------------------------------------
    @property
    def status(self) -> str:
        return self.meta["status"]

    def _save_meta(self) -> None:
        self.storage.update_meta(self.id, self.meta)

    def rebuild(self) -> None:
        """Rebuild the state from storage: the latest snapshot, then the actions after it."""
        if self.status == "lobby":
            return
        stored = self.storage.actions(self.id)
        snapshot = self.storage.latest_snapshot(self.id)
        if snapshot and snapshot[0] <= len(stored):
            start, state = snapshot[0], GameState.model_validate_json(snapshot[1])
        else:
            start, state = 0, new_game(self.world, self.settings, self.meta["seed"], self.meta["players"])
        for action, _ in stored[start:]:
            state, _ = apply(state, ACTION_ADAPTER.validate_python(action))
        self.state = state
        self.events = [Event.model_validate(e) for _, events in stored for e in events]
        self.seq = len(stored)

    def _make_player(self, seat: int):
        kind = self.meta["seats"][seat]
        ai = self._ai_context() if kind.split(":")[0] == "ai" else None
        player = make_player(kind, seat, self.meta["seed"], self.world, ai, self.settings, name=self.meta["players"][seat])
        if hasattr(player, "observe"):  # a scripted bot remembers what it has seen so far
            player.observe(visible_events(self.events, seat))
        if hasattr(player, "notes"):
            player.notes = self.meta["ai_notes"].get(str(seat), "")
        return player

    def start_workers(self) -> None:
        if self.state is None or self.closed or self.status in ("finished", "ended"):
            return
        for seat, kind in enumerate(self.meta["seats"]):
            if kind != HUMAN and seat not in self.workers:
                worker = _SeatWorker(self._make_player(seat))
                self.workers[seat] = worker
                worker.task = asyncio.create_task(self._run_seat(seat), name=f"{self.id}/seat{seat}")

    def stop_worker(self, seat: int) -> None:
        worker = self.workers.pop(seat, None)
        if worker and worker.task:
            worker.task.cancel()

    async def close(self) -> None:
        self.closed = True
        for seat in list(self.workers):
            self.stop_worker(seat)
        async with self.cond:
            self.cond.notify_all()

    # Seats ------------------------------------------------------------------------------------
    def seat_for_token(self, token: str | None) -> int | None:
        if not token:
            return None
        wanted = token_hash(token)
        for seat, stored in self.meta["seat_tokens"].items():
            if hmac.compare_digest(stored, wanted):
                return int(seat)
        return None

    def is_host(self, token: str | None) -> bool:
        return bool(token) and hmac.compare_digest(self.meta["host_token"], token_hash(token))

    def can_spectate(self, host_token: str | None, password: str | None) -> bool:
        """Specification 7.3: the host always; others with the spectator password, if one is set."""
        if self.is_host(host_token):
            return True
        stored = self.meta.get("spectator_password")
        return bool(stored and password and password_ok(password, stored))

    def debrief_allowed(self, seat_token: str | None, host_token: str | None, spectator_password: str | None,
                        join_password: str | None) -> bool:
        """Specification 10: every player once the game is over (anyone who could join it);
        spectators at any time."""
        if self.can_spectate(host_token, spectator_password):
            return True
        if self.status not in ("finished", "ended") or self.state is None:
            return False
        if self.seat_for_token(seat_token) is not None:
            return True
        stored = self.meta.get("join_password")
        return not stored or bool(join_password and password_ok(join_password, stored))

    def world_model(self) -> dict[str, Any] | None:
        """The world file's effects, interactions and row probabilities: kept with games created
        since milestone 6; for older games, from the world file of the same name, if there is one."""
        if self.meta.get("world_model") is not None:
            return self.meta["world_model"]
        from nv_core.paths import SCENARIOS_DIR
        from nv_world.worldfile import load_world, world_to_json

        path = SCENARIOS_DIR / self.world.scenario_id / "worlds" / f"{self.meta['world_id']}.json"
        try:
            return world_to_json(load_world(path))
        except (OSError, ValueError, KeyError):
            return None

    def debrief(self) -> dict[str, Any]:
        if self._debrief is None or self._debrief[0] != self.seq:
            notes = {int(s): text for s, text in self.meta.get("ai_notes", {}).items()}
            data = build_debrief(self._bookkept_state(), self.events, _low_chance(), self.world_model(), notes)
            self._debrief = (self.seq, to_jsonable_python(data))
        return self._debrief[1]

    def _bookkept_state(self) -> GameState:
        """The current state with the debrief's hidden bookkeeping (5.1) from round 1. A game begun
        before the bookkeeping existed (milestone 6) only has it from the round it was last loaded
        in; it is then replayed from its first action with today's engine, which records all of it.
        The replay is used only if it gives every stored event exactly, i.e. the same game;
        otherwise the stored state is used and the debrief says its history is incomplete."""
        state = self.state
        if state is None or (state.round_log and state.round_log[0].round == 1) or (not state.round_log and state.round == 1):
            return state
        stored = self.storage.actions(self.id)
        if len(stored) != self.seq:
            return state
        snapshot = self.storage.snapshot_before(self.id, 0)
        rebuilt = (GameState.model_validate_json(snapshot[1]) if snapshot
                   else new_game(self.world, self.settings, self.meta["seed"], self.meta["players"]))
        for action, events in stored:
            try:
                rebuilt, new_events = apply(rebuilt, ACTION_ADAPTER.validate_python(action))
            except Exception:  # played under older rules
                return state
            if [e.text for e in new_events] != [e["text"] for e in events]:
                return state
        return rebuilt

    def replay(self, at: int) -> dict[str, Any]:
        """The spectator view after ``at`` actions (specification 7.3): from the latest snapshot
        before it, then the actions after that snapshot."""
        stored = self.storage.actions(self.id)
        at = max(0, min(at, len(stored)))
        snapshot = self.storage.snapshot_before(self.id, at)
        if snapshot:
            start, state = snapshot[0], GameState.model_validate_json(snapshot[1])
        else:
            start, state = 0, new_game(self.world, self.settings, self.meta["seed"], self.meta["players"])
        problem = ""
        for i in range(start, at):
            try:
                state, _ = apply(state, ACTION_ADAPTER.validate_python(stored[i][0]))
            except Exception as exc:  # a game played under older rules
                problem = f"action {i + 1} cannot be replayed with the current rules ({exc}); showing action {i}"
                at = i
                break
        rounds = [{"round": 1, "seq": 0}]
        for i, (_, events) in enumerate(stored):
            rounds += [{"round": e["round"], "seq": i + 1} for e in events if e["kind"] == "round"]
        view = spectator_view(state)
        return {
            "type": "replay",
            "at": at,
            "total": len(stored),
            "rounds": rounds,
            "problem": problem,
            "view": to_jsonable_python(view),
            "text": render_text(view),
            "events": [e["text"] for _, events in stored[:at] for e in events][-EVENTS_SENT:],
        }

    def public_seats(self) -> list[dict[str, Any]]:
        connected = {c.seat for c in self.connections if c.seat is not None}
        seats = []
        for seat, kind in enumerate(self.meta["seats"]):
            human = self.meta["original_seats"][seat] == HUMAN
            seats.append(
                {
                    "seat": seat,
                    "name": self.meta["players"][seat],
                    "kind": kind,
                    "human_seat": human,
                    "taken": str(seat) in self.meta["seat_tokens"],
                    "connected": seat in connected,
                    "colour": self.meta["colours"][seat],
                }
            )
        return seats

    async def join(self, seat: int, nickname: str, password: str, colour: str | None) -> str:
        async with self.cond:
            if self.status in ("ended", "finished"):
                raise GameError("this game is over")
            if not password_ok(password, self.meta.get("join_password")):
                raise GameError("wrong join password")
            if not 0 <= seat < len(self.meta["seats"]) or self.meta["original_seats"][seat] != HUMAN:
                raise GameError("that is not a seat for a person")
            if str(seat) in self.meta["seat_tokens"]:
                raise GameError("that seat is taken")
            nickname = nickname.strip()[:30]
            if self.status == "lobby":
                if not nickname:
                    raise GameError("enter a nickname")
                if nickname in [p for i, p in enumerate(self.meta["players"]) if i != seat]:
                    raise GameError("that nickname is taken")
                self.meta["players"][seat] = nickname
                if colour in COLOURS and colour not in self.meta["colours"]:
                    self.meta["colours"][seat] = colour
            token = new_token()
            self.meta["seat_tokens"][str(seat)] = token_hash(token)
            self._save_meta()
        await self.broadcast()
        return token

    # Host controls (specification 6.4) -----------------------------------------------------------
    async def host(self, command: str, seat: int | None = None, kind: str | None = None) -> None:
        async with self.cond:
            if command == "start":
                if self.status != "lobby":
                    raise GameError("the game has already started")
                free = [s for s, k in enumerate(self.meta["seats"]) if k == HUMAN and str(s) not in self.meta["seat_tokens"]]
                if free:
                    raise GameError(f"seat(s) {', '.join(str(s + 1) for s in free)} still need a player")
                self.state = new_game(self.world, self.settings, self.meta["seed"], self.meta["players"])
                self.meta["status"] = "running"
                self.meta["started"] = time.time()
                self.storage.save_snapshot(self.id, 0, self.state.model_dump_json())
            elif command == "pause":
                self._require("running")
                self.meta["status"] = "paused"
            elif command == "resume":
                self._require("paused")
                self.meta["status"] = "running"
            elif command == "end":
                if self.status not in ("running", "paused"):
                    raise GameError("only a game in progress can be ended")
                self.meta["status"] = "ended"
            elif command == "automate":
                self._check_seat(seat)
                check_seat_types([kind or ""])
                self.meta["seats"][seat] = kind
                self.stop_worker(seat)
            elif command == "release":
                self._check_seat(seat)
                self.meta["seats"][seat] = self.meta["original_seats"][seat]
                self.stop_worker(seat)
            elif command == "remove":
                self._check_seat(seat)
                self.meta["seat_tokens"].pop(str(seat), None)
                for c in [c for c in self.connections if c.seat == seat]:
                    c.seat = None
            else:
                raise GameError(f"unknown host command {command!r}")
            self._save_meta()
            self.start_workers()
            self.cond.notify_all()
        await self.broadcast()

    def _require(self, status: str) -> None:
        if self.status != status:
            raise GameError(f"the game is {self.status}, not {status}")

    def _check_seat(self, seat: int | None) -> None:
        if seat is None or not 0 <= seat < len(self.meta["seats"]):
            raise GameError("no such seat")
        if self.meta["original_seats"][seat] != HUMAN:
            raise GameError("only a person's seat can be handed over")

    # Actions ----------------------------------------------------------------------------------
    def must_act(self, seat: int) -> bool:
        s = self.state
        return (
            s is not None and s.result is None and self.status == "running"
            and (s.current == seat or seat in s.waiting)
        )

    async def act(self, seat: int, action: BaseModel) -> tuple[str | None, int]:
        """Apply one action of ``seat``: (the reason it was refused or None, the sequence number after it)."""
        async with self.cond:
            problem = self._apply_locked(seat, action)
            seq = self.seq
        if problem is None:
            await self.broadcast()
        return problem, seq

    def _apply_locked(self, seat: int, action: BaseModel) -> str | None:
        if self.status != "running":
            return f"the game is {self.status}"
        if self.state is None or self.state.result is not None:
            return "the game is over"
        if getattr(action, "seat", None) != seat:
            return "that action belongs to another seat"
        try:
            new_state, events = apply(self.state, action)
        except IllegalAction as exc:
            return str(exc)
        data = ACTION_ADAPTER.dump_python(action, mode="json")
        if not self.storage.append_action(self.id, self.seq, data, [e.model_dump(mode="json") for e in events]):
            return "the game changed in the meantime; try again"
        old_round = self.state.round
        self.state, self.seq = new_state, self.seq + 1
        self.events += events
        if new_state.round != old_round:
            self.storage.save_snapshot(self.id, self.seq, new_state.model_dump_json())
        for watcher, worker in self.workers.items():
            if hasattr(worker.player, "observe"):
                worker.player.observe(visible_events(events, watcher))
        if new_state.result is not None:
            self.meta["status"] = "finished"
            self._save_meta()
        self.cond.notify_all()
        return None

    async def _run_seat(self, seat: int) -> None:
        """Background worker of one automated seat."""
        worker = self.workers[seat]
        player = worker.player
        try:
            while True:
                async with self.cond:
                    await self.cond.wait_for(lambda: self.closed or self.workers.get(seat) is not worker or self.must_act(seat)
                                             or (self.state is not None and self.state.result is not None))
                    if self.closed or self.workers.get(seat) is not worker or self.state.result is not None:
                        return
                    state, seq = self.state, self.seq
                    options = legal_actions(state, seat)
                    view = self._decision_view(state, seat) if player.needs_view else {
                        "round": state.round, "phase": state.phase.value, "seat": seat}
                if getattr(player, "provider", None) is not None:  # an AI: think without blocking anyone
                    action = await asyncio.to_thread(player.choose, view, options)
                else:
                    action = player.choose(view, options)
                async with self.cond:
                    stale = self.seq != seq
                    problem = self._apply_locked(seat, action)
                    if problem and not stale and self.status == "running":
                        worker.refusals += 1
                        if hasattr(player, "refused"):
                            player.refused(action, problem)
                        if worker.refusals >= MAX_REFUSALS:
                            fallback = next((o.actions[0] for o in options if o.type in ("commit", "pass")), None)
                            if fallback is not None and self._apply_locked(seat, fallback) is None:
                                problem = None
                            worker.refusals = 0
                    elif problem is None:
                        worker.refusals = 0
                    self._store_ai(seat, worker)
                if problem is None:
                    await self.broadcast()
                else:
                    await asyncio.sleep(0)  # let others act before trying again
        except asyncio.CancelledError:
            raise
        except Exception:  # a crash in one seat must not take the server down
            log.exception("automated seat %s of game %s stopped", seat, self.id)

    def _store_ai(self, seat: int, worker: _SeatWorker) -> None:
        decisions = getattr(worker.player, "decisions", None)
        if decisions is None:
            return
        for d in decisions[worker.stored_decisions:]:
            self.storage.add_ai_decision(self.id, {**d, "seat": seat})
        if len(decisions) > worker.stored_decisions:
            worker.stored_decisions = len(decisions)
            self.meta["ai_notes"][str(seat)] = worker.player.notes
            self.meta["ai_cost"][str(seat)] = round(
                self.meta["ai_cost_base"].get(str(seat), 0.0) + worker.player.cost, 6
            )
            self._save_meta()

    def _decision_view(self, state: GameState, seat: int) -> dict[str, Any]:
        view = player_view(state, seat)
        view["recent_events"] = [e.text for e in visible_events(self.events, seat)[-RECENT_EVENTS:]]
        return view

    # Views ------------------------------------------------------------------------------------
    def payload(self, conn: Connection) -> dict[str, Any]:
        seat = conn.seat
        data: dict[str, Any] = {
            "type": "state",
            "game": self.id,
            "seq": self.seq,
            "status": self.status,
            "title": self.meta["title"],
            "you": seat,
            "host": conn.host,
            "spectator": conn.spectator,
            "seats": self.public_seats(),
            "ai_cost": self.meta["ai_cost"],
            "view": None,
            "text": "",
            "options": [],
            "events": [],
        }
        if self.state is not None and seat is not None:
            view = player_view(self.state, seat)
            data["view"] = to_jsonable_python(view)
            data["text"] = render_text(view)
            if self.status == "running" and self.meta["seats"][seat] == HUMAN:
                data["options"] = [o.model_dump(mode="json") for o in legal_actions(self.state, seat)]
            data["events"] = [e.text for e in visible_events(self.events, seat)[-EVENTS_SENT:]]
        elif self.state is not None and conn.spectator:  # everything (specification 7.3)
            view = spectator_view(self.state)
            data["view"] = to_jsonable_python(view)
            data["text"] = render_text(view)
            data["events"] = [e.text for e in self.events][-EVENTS_SENT:]
            data["ai_notes"] = {self.meta["players"][int(s)]: text for s, text in self.meta.get("ai_notes", {}).items() if text}
        return data

    async def connect(self, conn: Connection) -> None:
        self.connections.append(conn)
        await self.broadcast()

    async def disconnect(self, conn: Connection) -> None:
        if conn in self.connections:
            self.connections.remove(conn)
            await self.broadcast()

    async def broadcast(self) -> None:
        for conn in list(self.connections):
            try:
                await conn.socket.send_json(self.payload(conn))
            except Exception:  # a closed browser: forget it
                if conn in self.connections:
                    self.connections.remove(conn)


# The games of one server ------------------------------------------------------------------------
@cache
def _low_chance() -> float:
    from nv_ai.config import load_software_settings

    return load_software_settings().debrief_low_chance


@dataclass
class GameSetup:
    """What the host chooses in the lobby (specification 6.3)."""

    world: WorldData
    settings: Settings
    seats: list[dict[str, str]]  # {"name", "kind"}
    seed: int
    title: str
    join_password: str = ""
    spectator_password: str = ""
    world_model: dict[str, Any] | None = None  # the world file's effects and probabilities (debrief)


def new_meta(setup: GameSetup, names: list[str], kinds: list[str], host_token: str, status: str = "lobby") -> dict[str, Any]:
    """A game's stored metadata (specification 6.1)."""
    return {
        "version": META_VERSION,
        "title": setup.title,
        "world_id": setup.world.world_id,
        "world": setup.world.model_dump(mode="json"),
        "world_model": setup.world_model,
        "settings": setup.settings.model_dump(mode="json"),
        "seed": setup.seed,
        "players": names,
        "seats": kinds,
        "original_seats": list(kinds),
        "colours": COLOURS[: len(kinds)],
        "status": status,
        "created": time.time(),
        "host_token": token_hash(host_token),
        "join_password": password_hash(setup.join_password) if setup.join_password else None,
        "spectator_password": password_hash(setup.spectator_password) if setup.spectator_password else None,
        "seat_tokens": {},
        "ai_notes": {},
        "ai_cost": {},
        "ai_cost_base": {},
    }


@dataclass
class GameManager:
    storage: Storage
    ai_context: Any = None  # () -> AIContext; created when the first AI seat needs it
    sessions: dict[str, GameSession] = field(default_factory=dict)

    def create(self, setup: GameSetup) -> tuple[str, str]:
        """Create a game in the lobby; returns (game id, host token)."""
        s = setup.settings
        if not s.min_players <= len(setup.seats) <= s.max_players:
            raise GameError(f"a game needs {s.min_players} to {s.max_players} seats")
        kinds = [seat["kind"] for seat in setup.seats]
        try:
            check_seat_types([k for k in kinds if k != HUMAN])
        except ValueError as exc:
            raise GameError(str(exc)) from None
        if any(k.split(":")[0] == "ai" for k in kinds):
            if self.ai_context is None:
                raise GameError("AI seats are not available on this server")
            try:
                self.ai_context()
            except ValueError as exc:  # e.g. the API key is missing
                raise GameError(str(exc)) from None
        names = [
            (seat.get("name") or "").strip()[:30]
            or (f"Seat {i + 1}" if seat["kind"] == HUMAN else f"{seat['kind'].replace(':', ' ').capitalize()} {i + 1}")
            for i, seat in enumerate(setup.seats)
        ]
        if len(set(names)) != len(names):
            raise GameError("seat names must differ")
        game_id = secrets.token_urlsafe(6)
        host = new_token()
        self.storage.create_game(game_id, new_meta(setup, names, kinds, host))
        return game_id, host

    async def get(self, game_id: str) -> GameSession:
        session = self.sessions.get(game_id)
        if session is None:
            meta = self.storage.get_meta(game_id)
            if meta is None:
                raise GameError("no such game")
            meta["ai_cost_base"] = dict(meta.get("ai_cost", {}))  # AI costs so far, before this load
            session = GameSession(game_id, meta, self.storage, self._ai)
            session.rebuild()
            self.sessions[game_id] = session
            session.start_workers()
        return session

    def _ai(self):
        if self.ai_context is None:
            raise GameError("AI seats are not available on this server")
        return self.ai_context()

    async def close(self) -> None:
        for session in self.sessions.values():
            await session.close()
        self.sessions.clear()

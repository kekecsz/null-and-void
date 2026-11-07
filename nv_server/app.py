"""The multiplayer server (specification 6): a FastAPI app with a lobby, joining, host controls
and one WebSocket per browser.

    nv-server                      # this computer only: http://127.0.0.1:8000
    nv-server --host 0.0.0.0       # also other devices on the same network (Wi-Fi)

Games are stored in a SQLite file (default ``games/nv_games.sqlite``) and survive a restart.
"""

import argparse
import asyncio
import random
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from nv_core.actions import ACTION_ADAPTER
from nv_core.paths import REPO_ROOT, SCENARIOS_DIR
from nv_core.settings import Settings
from nv_server.session import COLOURS, HUMAN, Connection, GameError, GameManager, GameSetup
from nv_server.storage import SQLiteStorage, Storage

WEB_DIR = REPO_ROOT / "web"
DEFAULT_DB = Path("games") / "nv_games.sqlite"


class SeatSpec(BaseModel):
    name: str = ""
    kind: str = HUMAN


class CreateGame(BaseModel):
    world: str | None = None  # a world file, relative to the scenarios folder
    scenario: str | None = None  # or: generate a new world for this scenario...
    world_seed: int | None = None  # ...with this seed
    seats: list[SeatSpec]
    seed: int | None = None
    overrides: str = ""  # YAML: setting: value
    join_password: str = ""
    spectator_password: str = ""


class JoinGame(BaseModel):
    seat: int
    nickname: str = ""
    password: str = ""
    colour: str | None = None


class HostCommand(BaseModel):
    host_token: str
    seat: int | None = None
    kind: str | None = None


def _worlds() -> list[dict[str, Any]]:
    import json

    found = []
    for path in sorted(SCENARIOS_DIR.glob("*/worlds/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found.append({"file": path.relative_to(SCENARIOS_DIR).as_posix(), "scenario": data.get("scenario_id", path.parts[-3]),
                      "id": path.stem})
    return found


def _scenarios() -> list[str]:
    return sorted(p.parent.name for p in SCENARIOS_DIR.glob("*/scenario.md"))


def _setup(request: CreateGame):
    """The world and settings the host chose (runs in a thread: generating a world takes a moment)."""
    from nv_world.game import load_game_world, world_data
    from nv_world.generate import GenerationFailed, generate_world
    from nv_world.scenario import load_scenario

    if request.world:
        path = (SCENARIOS_DIR / request.world).resolve()
        if SCENARIOS_DIR.resolve() not in path.parents or not path.is_file():
            raise GameError("no such world file")
        world, settings, _ = load_game_world(path)
    elif request.scenario:
        if request.scenario not in _scenarios():
            raise GameError("no such scenario")
        scenario = load_scenario(SCENARIOS_DIR / request.scenario / "scenario.md")
        seed = request.world_seed if request.world_seed is not None else random.SystemRandom().randrange(1_000_000)
        try:
            world = world_data(scenario, generate_world(scenario, seed), f"generated_seed{seed}")
        except GenerationFailed as exc:
            raise GameError(f"no acceptable world found: {exc}") from None
        settings = scenario.settings
    else:
        raise GameError("choose a world or a scenario")
    if request.overrides.strip():
        try:
            overrides = yaml.safe_load(request.overrides)
        except yaml.YAMLError as exc:
            raise GameError(f"settings overrides are not valid YAML: {exc}") from None
        if not isinstance(overrides, dict):
            raise GameError("settings overrides must be lines of the form  setting: value")
        unknown = sorted(set(overrides) - set(Settings.model_fields))
        if unknown:
            raise GameError(f"unknown setting(s): {', '.join(unknown)}")
        try:
            settings = Settings.model_validate({**settings.model_dump(), **overrides})
        except ValidationError as exc:
            raise GameError("; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])) from None
    return world, settings


def _cached_ai_context():
    cache: dict[str, Any] = {}

    def get():
        if "ai" not in cache:
            from nv_sim.run import ai_context

            cache["ai"] = ai_context()  # raises ValueError when the API key is missing
        return cache["ai"]

    return get


def create_app(storage: Storage | None = None, ai_context=None, db: Path | str = DEFAULT_DB) -> FastAPI:
    """``ai_context``: () -> AIContext for AI seats (default: the real provider and ledger)."""
    manager = GameManager(storage or SQLiteStorage(db), ai_context or _cached_ai_context())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await manager.close()

    app = FastAPI(title="Null & Void", lifespan=lifespan)
    app.state.manager = manager
    app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")

    async def session(game_id: str):
        try:
            return await manager.get(game_id)
        except GameError as exc:
            raise HTTPException(404, str(exc)) from None

    # Pages ----------------------------------------------------------------------------------
    @app.get("/")
    async def lobby_page():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/game/{game_id}")
    async def game_page(game_id: str):
        return FileResponse(WEB_DIR / "game.html")

    # Lobby API ------------------------------------------------------------------------------
    @app.get("/api/options")
    async def lobby_options():
        from nv_ai.prompt import PERSONAS
        from nv_sim.bots import BOTS
        from nv_sim.strategy import SEAT_TYPES

        kinds = [HUMAN, *SEAT_TYPES, *BOTS, "ai", *[f"ai:{p}" for p in PERSONAS if p != "neutral"]]
        settings = Settings.model_fields
        return {"worlds": _worlds(), "scenarios": _scenarios(), "seat_kinds": kinds, "colours": COLOURS,
                "settings": sorted(settings)}

    @app.get("/api/games")
    async def list_games():
        games = []
        for g in manager.storage.list_games():
            m = g["meta"]
            games.append({"id": g["id"], "title": m["title"], "world": m["world_id"], "status": m["status"],
                          "created": g["created"], "actions": g["actions"], "players": m["players"], "seats": m["seats"]})
        return games

    @app.post("/api/games")
    async def create_game(request: CreateGame):
        try:
            world, settings = await asyncio.to_thread(_setup, request)
            seed = request.seed if request.seed is not None else random.SystemRandom().randrange(1_000_000_000)
            setup = GameSetup(world, settings, [s.model_dump() for s in request.seats], seed, world.title,
                              request.join_password, request.spectator_password)
            game_id, host_token = manager.create(setup)
        except GameError as exc:
            raise HTTPException(400, str(exc)) from None
        return {"game": game_id, "host_token": host_token}

    @app.get("/api/games/{game_id}")
    async def game_info(game_id: str):
        s = await session(game_id)
        return {"game": game_id, "title": s.meta["title"], "world": s.meta["world_id"], "status": s.status,
                "seats": s.public_seats(), "join_password": bool(s.meta.get("join_password")), "colours": COLOURS}

    @app.post("/api/games/{game_id}/join")
    async def join_game(game_id: str, request: JoinGame):
        s = await session(game_id)
        try:
            token = await s.join(request.seat, request.nickname, request.password, request.colour)
        except GameError as exc:
            raise HTTPException(400, str(exc)) from None
        return {"seat": request.seat, "seat_token": token}

    @app.post("/api/games/{game_id}/host/{command}")
    async def host_command(game_id: str, command: str, request: HostCommand):
        s = await session(game_id)
        if not s.is_host(request.host_token):
            raise HTTPException(403, "only the host can do that")
        try:
            await s.host(command, request.seat, request.kind)
        except (GameError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from None
        return {"status": s.status}

    # Live game ------------------------------------------------------------------------------
    @app.websocket("/ws/{game_id}")
    async def live(socket_: WebSocket, game_id: str, seat_token: str = "", host_token: str = ""):
        await socket_.accept()
        try:
            s = await manager.get(game_id)
        except GameError as exc:
            await socket_.send_json({"type": "error", "message": str(exc)})
            await socket_.close()
            return
        seat = s.seat_for_token(seat_token)
        host = s.is_host(host_token)
        if seat is None and not host:
            await socket_.send_json({"type": "error", "message": "join a seat first (or open the host link)"})
            await socket_.close()
            return
        conn = Connection(socket_, seat, host)
        await s.connect(conn)
        try:
            while True:
                message = await socket_.receive_json()
                if message.get("type") != "action":
                    continue
                if conn.seat is None:
                    await socket_.send_json({"type": "error", "message": "you have no seat in this game"})
                    continue
                try:
                    action = ACTION_ADAPTER.validate_python({**message.get("action", {}), "seat": conn.seat})
                except ValidationError as exc:
                    problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:3])
                    await socket_.send_json({"type": "error", "message": f"not a valid action: {problems}"})
                    continue
                if s.meta["seats"][conn.seat] != HUMAN:
                    await socket_.send_json({"type": "error", "message": "your seat is played by an automated player now"})
                    continue
                problem, seq = await s.act(conn.seat, action)
                if problem:
                    await socket_.send_json({"type": "error", "message": problem})
                else:  # views sent before this one may still be on their way: they are older than seq
                    await socket_.send_json({"type": "accepted", "seq": seq})
        except WebSocketDisconnect:
            pass
        finally:
            await s.disconnect(conn)

    return app


def _lan_address() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 80))  # no packet is sent; this finds the outgoing interface
            return probe.getsockname()[0]
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    parser = argparse.ArgumentParser(prog="nv-server", description="Null & Void multiplayer server")
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 lets other devices on your network join")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite file the games are stored in")
    args = parser.parse_args(argv)
    print(f"Null & Void server: open http://127.0.0.1:{args.port}/ in your browser")
    if args.host == "0.0.0.0":
        address = _lan_address()
        if address:
            print(f"Other devices on this network: http://{address}:{args.port}/")
    uvicorn.run(create_app(db=args.db), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

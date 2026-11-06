"""Text client (specification section 7.1): a local game with all seats on one machine.

    nv-play new scenarios/venus_expedition/worlds/world_seed1.json --players Anna,Ben,Cleo
    nv-play load games/my_game.json

The game is saved after every accepted action (as its record: setup plus actions), so it can
be stopped at any time and resumed with ``load``. A file of commands can be played with
``--script`` (one command per line, ``as NAME`` to switch seats).
"""

import argparse
import random
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from nv_core.engine import IllegalAction, apply
from nv_core.engine.context import Event
from nv_core.record import GameRecord
from nv_core.state import GameState
from nv_core.text import render_text
from nv_core.views import player_view, visible_events
from nv_server.commands import HELP, CommandError, parse, _seat
from nv_world.game import load_game_world

DEFAULT_SAVE_DIR = Path("games")


class TextClient:
    def __init__(self, record: GameRecord, save_path: Path | None, out: Callable[[str], None] = print):
        self.record = record
        self.save_path = save_path
        self.out = out
        self.state: GameState = record.replay()
        self.events: list[Event] = []
        self.seat = self._default_seat()

    # Seats --------------------------------------------------------------------------------
    def _default_seat(self) -> int:
        if self.state.current is not None:
            return self.state.current
        if self.state.waiting:
            return self.state.waiting[0]
        return 0

    def _must_act(self, seat: int) -> bool:
        return self.state.current == seat or seat in self.state.waiting

    def show(self) -> None:
        self.out(render_text(player_view(self.state, self.seat)))
        self.prompt_line()

    def prompt_line(self) -> None:
        if self.state.result:
            self.out("The game is over. Type quit to leave, or view / log to look back.")
            return
        task = "your turn" if self.state.current == self.seat else (
            "decide, then commit" if self.seat in self.state.waiting else "nothing to decide now"
        )
        self.out(f"--- {self.state.players[self.seat]} | {self.state.phase.value} | {task} (type help for commands)")

    # Commands -----------------------------------------------------------------------------
    def handle(self, line: str) -> bool:
        """Run one command; return False to quit."""
        line = line.strip()
        if not line or line.startswith("#"):
            return True
        verb = line.split()[0].lower()
        if verb in ("quit", "exit"):
            return False
        if verb == "help":
            self.out(HELP)
            return True
        if verb == "view":
            self.show()
            return True
        if verb == "log":
            parts = line.split()
            n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 30
            for event in visible_events(self.events, self.seat)[-n:]:
                self.out(f"  [r{event.round}] {event.text}")
            return True
        if verb == "as":
            try:
                self.seat = _seat(self.state, line.split(maxsplit=1)[1])
            except (CommandError, IndexError) as exc:
                self.out(f"! {exc}")
                return True
            self.show()
            return True
        try:
            action = parse(self.state, self.seat, line)
            new_state, events = apply(self.state, action)
        except (CommandError, IllegalAction) as exc:
            self.out(f"! {exc}")
            return True
        except ValueError as exc:  # e.g. a malformed number in a command
            self.out(f"! {exc}")
            return True
        self.state = new_state
        self.record.actions.append(action)
        self.events += events
        if self.save_path:
            self.record.save(self.save_path)
        actor = self.seat
        for event in visible_events(events, actor):
            self.out(f"  {event.text}")
        if not self._must_act(actor) and not self.state.result:
            self.seat = self._default_seat()
            if self.seat != actor:
                self.out("")
                self.out(f"=== {self.state.players[self.seat]}'s turn: hand over the screen ===")
                self.show()
                return True
        self.prompt_line()
        return True

    def run(self, lines: Iterable[str], echo: bool = False) -> None:
        for line in lines:
            if echo:
                self.out(f"> {line.rstrip()}")
            if not self.handle(line):
                return


def _new_record(args: argparse.Namespace) -> tuple[GameRecord, Path]:
    world, settings, warnings = load_game_world(Path(args.world), Path(args.scenario) if args.scenario else None)
    for warning in warnings:
        print(f"Warning: {warning}")
    players = [p.strip() for p in args.players.split(",") if p.strip()]
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1_000_000)
    record = GameRecord(world=world, settings=settings, seed=seed, players=players)
    save = Path(args.save) if args.save else DEFAULT_SAVE_DIR / f"{world.world_id}_game{seed}.json"
    return record, save


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nv-play", description="Play Null & Void in the terminal (all seats on one machine).")
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="start a new game")
    new.add_argument("world", help="world file (JSON)")
    new.add_argument("--players", required=True, help="comma-separated names, in seat order")
    new.add_argument("--seed", type=int, help="game seed (default: random; it is saved with the game)")
    new.add_argument("--scenario", help="scenario file (default: scenarios/<id>/scenario.md)")
    new.add_argument("--save", help=f"save file (default: {DEFAULT_SAVE_DIR}/<world>_game<seed>.json)")
    new.add_argument("--script", help="file of commands to play first")
    load = commands.add_parser("load", help="resume a saved game")
    load.add_argument("save", help="save file")
    load.add_argument("--script", help="file of commands to play first")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # state names may hold characters the console lacks

    try:
        if args.command == "new":
            record, save = _new_record(args)
        else:
            save = Path(args.save)
            record = GameRecord.load(save)
        client = TextClient(record, save)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    record.save(save)
    print(f"Game saved to {save} after every action (seed {record.seed}).")
    client.show()
    if args.script:
        client.run(Path(args.script).read_text(encoding="utf-8").splitlines(), echo=True)
        if client.state.result:
            return 0
    while True:
        try:
            line = input("> ")
        except EOFError:
            return 0
        if not client.handle(line):
            return 0


if __name__ == "__main__":
    raise SystemExit(main())

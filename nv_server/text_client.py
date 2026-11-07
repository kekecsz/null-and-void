"""Text client (specification section 7.1): a local game with all seats on one machine.

    nv-play new scenarios/venus_expedition/worlds/world_seed1.json --players Anna,Ben,Cleo
    nv-play new ... --players Anna,Ben,Cleo --seat Ben=ai --seat Cleo=random
    nv-play load games/my_game.json

Seats are played by people at the keyboard unless ``--seat NAME=TYPE`` makes them automated:
``random`` (the random bot), ``ai`` or ``ai:<persona>`` (an AI player, specification 8).
Automated seats act on their own whenever it is their turn. A game without human seats plays
itself to the end.

The game is saved after every accepted action (as its record: setup plus actions), so it can
be stopped at any time and resumed with ``load``. A file of commands can be played with
``--script`` (one command per line, ``as NAME`` to switch seats).
"""

import argparse
import random
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from nv_core.engine import IllegalAction, apply, legal_actions
from nv_core.engine.context import Event
from nv_core.record import GameRecord
from nv_core.state import GameState
from nv_core.text import render_text
from nv_core.views import player_view, visible_events
from nv_server.commands import HELP, CommandError, _seat, parse
from nv_world.game import load_game_world

DEFAULT_SAVE_DIR = Path("games")
MAX_REFUSALS = 20
RECENT_EVENTS = 25


def _automated_players(record: GameRecord, ai=None) -> list:
    """One player object per automated seat, None for human seats."""
    from nv_sim.game import make_players

    seats = record.seats or ["human"] * len(record.players)
    players = []
    for seat, kind in enumerate(seats):
        if kind == "human":
            players.append(None)
            continue
        if kind.split(":")[0] == "ai" and ai is None:
            from nv_sim.run import ai_context

            ai = ai_context()
        player = make_players([kind], record.seed, record.world, ai, record.settings)[0]
        if hasattr(player, "name"):
            player.name = record.players[seat]
        players.append(player)
    return players


class TextClient:
    def __init__(self, record: GameRecord, save_path: Path | None, out: Callable[[str], None] = print, ai=None):
        self.record = record
        self.save_path = save_path
        self.out = out
        self.state: GameState = record.replay()
        self.events: list[Event] = []
        self.players = _automated_players(record, ai)
        self.seat = self._default_seat()

    # Seats --------------------------------------------------------------------------------
    def _human(self, seat: int) -> bool:
        return self.players[seat] is None

    def _default_seat(self) -> int:
        candidates = ([self.state.current] if self.state.current is not None else []) + list(self.state.waiting)
        humans = [s for s in candidates if self._human(s)]
        if humans:
            return humans[0]
        if candidates:
            return candidates[0]
        human_seats = [s for s in range(len(self.players)) if self._human(s)]
        return human_seats[0] if human_seats else 0

    def _must_act(self, seat: int) -> bool:
        return self.state.current == seat or seat in self.state.waiting

    @property
    def ai_cost(self) -> float:
        return sum(getattr(p, "cost", 0.0) for p in self.players if p is not None)

    def show(self) -> None:
        self.out(render_text(player_view(self.state, self.seat)))
        self.prompt_line()

    def prompt_line(self) -> None:
        if self.state.result:
            cost = f" AI cost: {self.ai_cost:.4f} USD." if self.ai_cost else ""
            self.out(f"The game is over.{cost} Type quit to leave, or view / log to look back.")
            return
        task = "your turn" if self.state.current == self.seat else (
            "decide, then commit" if self.seat in self.state.waiting else "nothing to decide now"
        )
        self.out(f"--- {self.state.players[self.seat]} | {self.state.phase.value} | {task} (type help for commands)")

    # Automated seats ----------------------------------------------------------------------
    def _next_automated(self) -> int | None:
        if self.state.result:
            return None
        if self.state.current is not None:
            return None if self._human(self.state.current) else self.state.current
        return next((s for s in self.state.waiting if not self._human(s)), None)

    def play_automated(self) -> None:
        """Let automated seats act until a human seat must decide or the game ends."""
        while (seat := self._next_automated()) is not None:
            player = self.players[seat]
            options = legal_actions(self.state, seat)
            if player.needs_view:
                view = player_view(self.state, seat)
                view["recent_events"] = [e.text for e in visible_events(self.events, seat)[-RECENT_EVENTS:]]
            else:
                view = {"round": self.state.round, "phase": self.state.phase.value, "seat": seat}
            result = None
            for _ in range(MAX_REFUSALS):
                action = player.choose(view, options)
                try:
                    result = apply(self.state, action)
                    break
                except IllegalAction as exc:
                    if hasattr(player, "refused"):
                        player.refused(action, str(exc))
            if result is None:  # the same safe default as the simulator
                fallback = next((o.actions[0] for o in options if o.type in ("commit", "pass")), None)
                if fallback is None:
                    self.out(f"! {self.state.players[seat]} found no legal action; the game cannot go on")
                    return
                action, result = fallback, apply(self.state, fallback)
            self._accept(action, result, seat)
            self._report_automated(seat, player, action)

    def _report_automated(self, seat: int, player, action) -> None:
        decisions = getattr(player, "decisions", None)
        if not decisions:
            return
        d = decisions[-1]
        how = f" [fallback: {d['fallback']}]" if d["fallback"] else ""
        reason = f" - {d['reason']}" if d["reason"] else ""
        self.out(
            f"  ({self.state.players[seat]}, AI: {action.type}{reason}{how}; "
            f"{d['input_tokens']} in ({d['cached_tokens']} cached), {d['output_tokens']} out "
            f"({d['reasoning_tokens']} reasoning), {d['cost']:.4f} USD; total {self.ai_cost:.4f} USD)"
        )

    def _accept(self, action, result, actor: int) -> None:
        self.state, events = result
        self.record.actions.append(action)
        self.events += events
        for watcher, player in enumerate(self.players):  # scripted bots watch the board
            if hasattr(player, "observe"):
                player.observe(visible_events(events, watcher))
        if self.save_path:
            self.record.save(self.save_path)
        humans = [s for s in range(len(self.players)) if self._human(s)]
        watcher = actor if self._human(actor) else (self.seat if humans else None)
        for event in visible_events(events, watcher):
            self.out(f"  {event.text}")

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
        if not self._human(self.seat):
            self.out(f"! {self.state.players[self.seat]} is an automated seat; switch with: as NAME")
            return True
        try:
            action = parse(self.state, self.seat, line)
            result = apply(self.state, action)
        except (CommandError, IllegalAction) as exc:
            self.out(f"! {exc}")
            return True
        except ValueError as exc:  # e.g. a malformed number in a command
            self.out(f"! {exc}")
            return True
        actor = self.seat
        self._accept(action, result, actor)
        self.play_automated()
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


def _seat_types(players: list[str], specs: list[str]) -> list[str]:
    types = ["human"] * len(players)
    for spec in specs:
        name, _, kind = spec.partition("=")
        if name not in players or not kind:
            raise ValueError(f"--seat {spec!r}: write NAME=TYPE with a name from --players")
        types[players.index(name)] = kind
    from nv_sim.game import check_seat_types

    check_seat_types([t for t in types if t != "human"])
    return types


def _new_record(args: argparse.Namespace) -> tuple[GameRecord, Path]:
    world, settings, warnings = load_game_world(Path(args.world), Path(args.scenario) if args.scenario else None)
    for warning in warnings:
        print(f"Warning: {warning}")
    players = [p.strip() for p in args.players.split(",") if p.strip()]
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1_000_000)
    seats = _seat_types(players, args.seat or [])
    record = GameRecord(world=world, settings=settings, seed=seed, players=players, seats=seats)
    save = Path(args.save) if args.save else DEFAULT_SAVE_DIR / f"{world.world_id}_game{seed}.json"
    return record, save


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nv-play", description="Play Null & Void in the terminal (all seats on one machine).")
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="start a new game")
    new.add_argument("world", help="world file (JSON)")
    new.add_argument("--players", required=True, help="comma-separated names, in seat order")
    new.add_argument("--seat", action="append", metavar="NAME=TYPE", help="automate a seat: random, ai or ai:<persona>")
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
    client.play_automated()
    client.seat = client._default_seat()
    client.show()
    if client.state.result or all(p is not None for p in client.players):
        return 0
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

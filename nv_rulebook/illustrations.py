"""The rulebook's pictures of the web client (the "[Figure: <name>.png]" markers in
docs/rules.md): screenshots of game situations, taken in a browser.

Each scene finds its situation in a game played by the scripted bots (nv_sim), adjusts it where
the bots rarely get there by themselves, opens it in the web client as one of the players (light
theme, tall tiles) and saves one panel as web/images/<name>.png. Run it again whenever the screens
change, and every picture follows:

    .venv/Scripts/nv-rulebook-illustrations                      # every scene
    .venv/Scripts/nv-rulebook-illustrations --only example_theory_formation  # some of them

Needs Playwright (pip install -e ".[illustrations]") and Microsoft Edge or Google Chrome, which
Playwright drives, so no browser download is needed.
"""

import argparse
import json
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from nv_core.engine import legal_actions
from nv_core.engine.context import Ctx, stack_cards
from nv_core.state import Card, GameState, Phase, Researcher
from nv_server.session import GameSetup, new_meta, token_hash
from nv_server.storage import SQLiteStorage
from nv_sim.game import play_game
from nv_world.game import load_game_world

REPO_ROOT = Path(__file__).resolve().parents[1]
IMAGES = REPO_ROOT / "web" / "images"
WORLD_FILE = REPO_ROOT / "scenarios" / "venus_expedition" / "worlds" / "world_seed1.json"
SEATS = ["cooperative", "selfish", "cooperative"]
NAMES = ["Ada", "Ben", "Cleo"]
SEEDS = range(1, 30)  # the first game that has every situation is used
SCALE = 2  # screen pixels per CSS pixel: sharp enough to print

# Every panel as narrow as its content, so the picture fits a column of the printed rulebook.
PAGE_STYLE = """
.top { position: static !important; }
#board { grid-template-columns: max-content 330px !important; }
#board .board-main .panel { width: max-content !important; min-width: 0 !important; max-width: 1000px; }
.cols { grid-template-columns: var(--head) repeat(var(--ni), var(--cell)) 16px repeat(var(--no), var(--cell)) minmax(120px, max-content) !important; }
"""


# Finding situations -------------------------------------------------------------------------------
def _options(state: GameState, seat: int, kind: str) -> list:
    return [o for o in legal_actions(state, seat) if o.type == kind]


def _experiments(r: Researcher) -> int:
    return len({c.experiment for c in r.records.cards})


def _slips(r: Researcher) -> int:  # record slips in record positions (Archiving records)
    return len(r.records.observations) + _experiments(r) - len(r.archived)


def _first(seats, test) -> int | None:
    return next((s for s in seats if test(s)), None)


def _waiting(state: GameState, phase: Phase, test) -> int | None:
    return _first(state.waiting, test) if state.phase == phase else None


def _all(state: GameState) -> range:
    return range(len(state.researchers))


def find_experiment(state):
    if state.phase != Phase.EXPERIMENTATION or state.current is None:
        return None
    methods = {p.idea.parameter for p in state.published if p.idea.kind == "method"}
    return state.current if len(methods) >= 2 and _options(state, state.current, "run_experiment") else None


def find_records(state):
    if state.phase != Phase.HIRING:
        return None
    capacity = state.settings.records_capacity
    return _first(_all(state), lambda s: _experiments(r := state.researchers[s]) >= 2 and _slips(r) >= 3 and _slips(r) <= capacity)


def find_grid_experimentation(state):
    return state.current if state.phase == Phase.EXPERIMENTATION and state.round >= 3 and state.current is not None else None


def find_grid_observation(state):
    if state.phase != Phase.PREDICTION or state.round < 3:
        return None
    filled = sum(1 for p in state.probes for c in p.readings.values() if c.state)
    return state.waiting[0] if state.waiting and filled >= 6 else None


def find_prediction_panel(state):
    def theories(s):
        options = _options(state, s, "make_prediction")
        return options and len({a.theory for a in options[0].actions}) >= 2
    return _waiting(state, Phase.PREDICTION, theories)


def find_prediction_report(state):
    report = state.prediction_report
    if state.phase != Phase.DEVELOPMENT or not report:
        return None
    outcomes = {p["outcome"] for p in report["predictions"]}
    if len(report["predictions"]) < 3 or not {"success", "failed"} <= outcomes:
        return None
    return report["predictions"][0]["seat"]


def find_theory(state):
    return _waiting(state, Phase.DEVELOPMENT,
                    lambda s: _experiments(state.researchers[s]) >= 2 and _options(state, s, "formulate_theory"))


def find_overflow(state):
    capacity = state.settings.records_capacity
    return _waiting(state, Phase.DEVELOPMENT,
                    lambda s: _slips(state.researchers[s]) > capacity and _options(state, s, "archive_records"))


def find_tier2(state):
    def tier2(s):
        options = _options(state, s, "submit")
        theories = {i.id for i in state.researchers[s].ideas if i.kind == "theory"}
        return options and any(a.tier == 2 and len(a.records) >= 2 and a.manuscript in theories for a in options[0].actions)
    return _waiting(state, Phase.SUBMISSION, tier2)


def find_portal(state):
    """Peer review with theories awaiting it; shown to the researcher with the most manuscripts
    (their own are face up)."""
    if state.phase != Phase.PEER_REVIEW or state.round < 4:
        return None
    areas = [m.area for m in state.manuscripts]
    missing = ("revise" not in areas) + ("accept" not in areas)
    theories = [m for m in state.manuscripts if m.idea.kind == "theory"]
    if not 2 + missing <= areas.count("review") <= 4 + missing or len(theories) < 3:
        return None
    authors = [m.author for m in theories]
    return max(set(authors), key=authors.count)


def find_literature(state):
    theories = [p for p in state.published if p.idea.kind == "theory"]
    if state.phase != Phase.HIRING or state.round < 6 or len(theories) < 4 or len({p.author for p in theories}) < 2:
        return None
    return max(theories, key=lambda p: (p.nobel, -p.id)).author


def find_cleanup(state):
    report = state.reports.get("cleanup") if state.phase == Phase.HIRING else None
    if not report or len({i["kind"] for i in report["items"]}) < 3 or len(report["credits"]) < 2:
        return None
    return 0


# Adjusting situations the bots rarely reach -------------------------------------------------------------
def add_sensors(state: GameState, seat: int) -> None:
    """Sensors of levels 1, 2 and 3 on different Probes, as if installed in earlier rounds (the bots
    rarely install them). Each shows a true reading, as the sensor deck's top card may
    (Revealing input parameters)."""
    slots = [(p, var) for p in state.probes for var in state.world.input_ids if var not in p.specialty]  # not a Specialty slot
    used: set[int] = set()
    for level in (1, 2, 3):
        probe, var = next(((p, v) for p, v in slots if p.index not in used), slots[0])
        slots.remove((probe, var))
        used.add(probe.index)
        probe.sensors[var] = level
        probe.readings[var] = Card(var=var, state=stack_cards(Ctx(state), probe.stack)[var].state, origin="supply")


def fill_portal(state: GameState, seat: int) -> None:
    """A manuscript in each area of the Submission Portal: one of those awaiting peer review goes
    to the Revise area, another to the Accept area (the viewer's own theories first, which are
    face up)."""
    areas = [m.area for m in state.manuscripts]
    review = sorted((m for m in state.manuscripts if m.area == "review"), key=lambda m: (m.author == seat, m.idea.kind == "theory"))
    if "revise" not in areas:
        m = review.pop()
        m.area, m.position, m.votes = "revise", None, ["revise", "revise"]
    if "accept" not in areas:
        m = review.pop()
        m.area, m.position, m.votes, m.tokens = "accept", None, ["accept", "accept"], 1


def near_nobel_and_retraction(state: GameState, seat: int) -> None:
    """One theory a step from the Nobel Prize, another a step from retraction."""
    theories = sorted((p for p in state.published if p.idea.kind == "theory"), key=lambda p: (-p.nobel, p.id))
    leader = theories[0]
    leader.nobel = state.settings.nobel_condition - 1
    other = next((p for p in theories[1:] if p.author != leader.author), theories[1])
    other.nobel, other.retraction = 0, state.settings.retraction_threshold - 1


# What each picture shows ----------------------------------------------------------------------------
# Reports not shown are closed, as if read ("Next"), so the task panel shows the task.
CLOSE_REPORTS = """(keep) => {
  latestReports().filter((x) => x.kind !== keep).forEach(markSeen);
  actionsShown = null; renderActions();
}"""


# The strip after the first n, and everything after it in its list, is removed.
KEEP_ROWS = """([panel, n]) => {
  const extra = document.querySelectorAll(`${panel} .strip`)[n];
  if (!extra) return;
  for (let x = extra; x;) { const next = x.nextSibling; x.remove(); x = next; }
}"""


@dataclass(frozen=True)
class Scene:
    name: str
    find: Callable[[GameState], int | None]  # the seat it is shown to, when the situation is there
    panel: str  # the element saved: a CSS selector
    prepare: str = ""  # JavaScript run in the page first (drafts in the task panel, etc.)
    adjust: Callable[[GameState, int], None] | None = None
    keep_rows: int | None = None  # only the first strips of the panel (and what belongs to them)
    report: str | None = None  # the report shown in the task panel (reports.js)


TASK = "#actions-panel"
SCENES = [
    Scene("example_experiment_specification", find_experiment, TASK, prepare="""() => {
      const tpl = optionOf('run_experiment').template;
      const withMethod = [...new Set(tpl.methods.map((m) => m.parameter))];
      const ids = [...new Set([...withMethod, ...Object.keys(tpl.states)])].slice(0, tpl.free_input_parameters + 1);
      for (const id of ids) task.picks[id] = tpl.states[id][0];
      redraw();
    }"""),
    Scene("records_are_with_example_experiment_slips", find_records, "#records-panel"),
    Scene("world_grid_exp_with_different_sensor_levels", find_grid_experimentation, "section[data-panel=grid]", adjust=add_sensors),
    Scene("world_grid_obs_before_prediction_reveal", find_grid_observation, "section[data-panel=grid]", adjust=add_sensors),
    Scene("prediction_formulation_task_panel", find_prediction_panel, TASK, keep_rows=3),
    Scene("example_predictions_report_page", find_prediction_report, TASK, report="prediction"),
    Scene("example_theory_formation", find_theory, TASK, prepare="""() => {
      copyToTheory(view().lab.records.experiments[0].cards);
      for (const id of [...inputVars().slice(2), ...outcomeVars().slice(1)].map((x) => x.id)) delete task.picks[id];  // a few blanks
      redraw();
    }"""),
    Scene("overflowing_records_area_with_archive_buttons", find_overflow, "#records-panel"),
    Scene("example_tier2_submission_with_supporting_records", find_tier2, TASK, prepare="""() => {
      const theories = view().lab.ideas.filter((i) => i.kind === 'theory').map((i) => i.id);
      const a = optionOf('submit').actions.find((x) => x.tier === 2 && x.records.length >= 2 && theories.includes(x.manuscript));
      const box = emptyBox(); box.manuscript = a.manuscript; chooseTier(box, 2);
      task.boxes = [box]; task.target = 0; task.open.add('box0'); redraw();
    }"""),
    Scene("submission_portal_all_three_areas_containing_submissions", find_portal, "section[data-panel=portal]", adjust=fill_portal),
    Scene("literature_theory_close_to_nobel_another_close_to_retraction", find_literature, "section[data-panel=literature]",
          adjust=near_nobel_and_retraction, keep_rows=4),
    Scene("example_cleanup_report", find_cleanup, TASK, report="cleanup"),
]


def find_situations(scenes: list[Scene]) -> dict[str, tuple[GameState, int]]:
    """The first state of a bot game for each scene, with the seat it is shown to."""
    world, settings, _ = load_game_world(WORLD_FILE)
    for seed in SEEDS:
        found: dict[str, tuple[GameState, int]] = {}

        def watch(state, seat, action, events):
            for scene in scenes:
                if scene.name not in found and (shown := scene.find(state)) is not None:
                    found[scene.name] = (state.clone(), shown)

        play_game(world, settings, seed, SEATS, on_action=watch)
        if len(found) == len(scenes):
            print(f"situations from the bot game with seed {seed}")
            return found
    missing = [s.name for s in scenes if s.name not in found]
    raise SystemExit(f"no bot game reached: {', '.join(missing)}")


# Taking the pictures ----------------------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def store_games(db: Path, situations: dict[str, tuple[GameState, int]], scenes: list[Scene]) -> dict[str, str]:
    """Each situation as a running game of human seats (nobody moves), seen from its seat."""
    storage = SQLiteStorage(db)
    try:
        return _store(storage, situations, scenes)
    finally:
        storage.close()


def _store(storage: SQLiteStorage, situations: dict[str, tuple[GameState, int]], scenes: list[Scene]) -> dict[str, str]:
    tokens = {}
    for scene in scenes:
        state, seat = situations[scene.name]
        state = state.clone()
        if scene.adjust:
            scene.adjust(state, seat)
        state.players = NAMES[: len(state.players)]
        for r in state.researchers:
            r.name = state.players[r.seat]
        setup = GameSetup(state.world, state.settings, [], state.seed, scene.name)
        meta = new_meta(setup, state.players, ["human"] * len(state.players), secrets.token_urlsafe(16), status="running")
        tokens[scene.name] = secrets.token_urlsafe(16)
        meta["seat_tokens"] = {str(seat): token_hash(tokens[scene.name])}
        storage.create_game(scene.name, meta)
        storage.save_snapshot(scene.name, 0, state.model_dump_json())
    return tokens


def take_pictures(base: str, tokens: dict[str, str], scenes: list[Scene], out: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge", headless=True)
        except Exception:
            browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 2400}, device_scale_factor=SCALE)
        board = {"theme": "light", "tiles": "tall", "pinTask": False, "pinSelection": False}
        context.add_init_script(f"localStorage.setItem('nv:board', {json.dumps(json.dumps(board))}); localStorage.setItem('nv:lang', 'en');")
        for scene in scenes:
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{base}/game/{scene.name}#seat={tokens[scene.name]}")
            page.wait_for_function("typeof msg !== 'undefined' && msg && msg.view")
            page.wait_for_timeout(500)  # the icons
            page.add_style_tag(content=PAGE_STYLE)
            page.evaluate(CLOSE_REPORTS, scene.report)
            if scene.prepare:
                page.evaluate(scene.prepare)
            if scene.keep_rows:
                page.evaluate(KEEP_ROWS, [scene.panel, scene.keep_rows])
            page.wait_for_timeout(300)
            if errors:
                raise SystemExit(f"{scene.name}: the page failed: {errors[0]}")
            page.locator(scene.panel).first.screenshot(path=str(out / f"{scene.name}.png"), animations="disabled")
            print(f"  {scene.name}.png")
            page.close()
        browser.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nv-rulebook-illustrations", description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", nargs="+", metavar="NAME", help="only these pictures (names without .png)")
    parser.add_argument("--out", type=Path, default=IMAGES, help="folder the pictures are saved in")
    args = parser.parse_args(argv)
    scenes = [s for s in SCENES if not args.only or s.name in args.only]
    unknown = set(args.only or []) - {s.name for s in SCENES}
    if unknown:
        parser.error(f"no such picture: {', '.join(sorted(unknown))}")
    situations = find_situations(SCENES)  # every scene, so that --only makes the same pictures
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        db = Path(folder) / "illustrations.sqlite"
        tokens = store_games(db, situations, scenes)
        port = _free_port()
        server = subprocess.Popen([sys.executable, "-m", "nv_server.app", "--port", str(port), "--db", str(db)],
                                  cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(200):
                try:
                    urllib.request.urlopen(f"{base}/api/options").read()
                    break
                except OSError:
                    time.sleep(0.1)
            take_pictures(base, tokens, scenes, args.out)
        finally:
            server.terminate()
            server.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

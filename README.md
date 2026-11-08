# Null & Void

*Null & Void* is a board game about the replication crisis and questionable research practices, designed by
Zoltan Kekecs to teach graduate students and postdocs (and to play with friends).

Players are researchers studying a hidden world whose rules they don't know. They observe it through noisy
probes, run experiments, publish theories in journals of different prestige, and use published theories to
make predictions. Credit, grants and the Nobel Prize reward success, while the hidden lab work leaves room
for questionable research practices. And a crisis is coming that only a field which really understands
its world can contain.

This repository is the software version: a Python implementation that will become a multiplayer web game
with AI opponents, a balance simulator, and an end-of-game debrief that compares the published literature with the
true world.

## Status

| Milestone | | |
| --- | --- | --- |
| 1 | World generator and report | done |
| 2 | Rules engine and text client | done |
| 3 | Random bot and simulator | done |
| 4 | AI player and scripted bots | done |
| 5 | Server, persistence and web UI | done |
| 6 | Spectator mode and debrief | done |
| 7 | Deployment | done |
| 8 | Board design with icons | in the game, waiting for acceptance (specification 7.4) |

The milestones and their acceptance criteria are in the specification, section 13.

## Deployment (milestone 7)

The project, region and limits are in `settings/cloud.yaml`. With the Google Cloud CLI signed in:

```sh
.venv/Scripts/python deploy/cloud_run.py setup     # once: services, Firestore database, server identity
.venv/Scripts/python deploy/cloud_run.py secrets   # the API key (from settings/api_keys.env) and an organiser password
.venv/Scripts/python deploy/cloud_run.py deploy    # build and publish; prints the address (also after every code change)
```

On the deployed server the organiser password is needed to create games and to see the list of games.
Players only need their join link. The AI budget (`ai_total_budget`) counts deployed spending separately
from the local ledger.

## The documents

The game and the software are defined by four documents. The code reads its values from them rather than
repeating them.

| Document | Holds |
| --- | --- |
| [`docs/rules.md`](docs/rules.md) | The rulebook: every game rule, in phase order (exported from Google Docs) |
| [`docs/parameter_defaults.yaml`](docs/parameter_defaults.yaml) | Every numeric game setting |
| [`scenarios/venus_expedition/scenario.md`](scenarios/venus_expedition/scenario.md) | The Venus Expedition scenario: story, input parameters and world outcomes, effect model, world acceptance criteria |
| [`docs/specification.md`](docs/specification.md) | The software specification: architecture, world generator, rules engine, server, clients, AI players, simulator, debrief |

Unresolved design questions are tracked in [`docs/open_questions.md`](docs/open_questions.md).

## Getting started

You need Python 3.14 or newer.

```sh
git clone https://github.com/kekecsz/null-and-void.git
cd null-and-void
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # on macOS/Linux: .venv/bin/python
git config core.hooksPath .githooks                 # run the document consistency check on every commit
```

Run the tests:

```sh
.venv/Scripts/python -m pytest
```

## Generating worlds

A *world* is the hidden World Table of a game: which world outcomes each combination of input states
produces. The generator builds one from a scenario's effect model and screens it against the scenario's
acceptance criteria, retrying until a world passes (specification, section 4).

```sh
# Generate and screen a world; writes scenarios/venus_expedition/worlds/world_seed7.json
.venv/Scripts/nv-world generate scenarios/venus_expedition/scenario.md --seed 7

# Report on a world: base rates, the best theories by number of inputs, Nobel-grade theories (text and CSV)
.venv/Scripts/nv-world report scenarios/venus_expedition/worlds/world_seed7.json
```

The same scenario and seed always give the same world. Worlds for seeds 1–5 are already in
[`scenarios/venus_expedition/worlds/`](scenarios/venus_expedition/worlds/).

## Playing in the browser

The server (specification, section 6) runs games in the browser, with any mix of people, scripted bots and
AI players. Games are saved after every action in `games/nv_games.sqlite`, so they survive a restart.

```sh
.venv/Scripts/nv-server                  # then open http://127.0.0.1:8000/
.venv/Scripts/nv-server --host 0.0.0.0   # also lets other devices on the same Wi-Fi join (it prints the address)
```

1. On the start page, choose a world and the seats: `human` for a person, or an automated player (the scripted
   bots, the random bot, or an AI model).
2. Create the game. You get a **join link** for the players and a **host link** (keep it private: it starts,
   pauses and ends the game, and can hand a seat to an automated player and back).
3. Each person opens the join link, picks a seat and a nickname. The host starts the game once every
   person's seat is taken.

A browser remembers its seat, so a refresh rejoins it. To play the same seat from another device, open the game
link with `#seat=<token>`; on your first device the token is in the browser's local storage under
`nv:<game>:seat`. With `--host 0.0.0.0`, Windows may ask once whether to allow Python through the firewall.

**Spectating and replay** (specification 7.3). The host link always opens the spectator view: every lab, the true
Probe states, every hidden prediction, the World Table and the AI players' notes. A host who also plays a seat in
the same browser can switch with "Watch as spectator" in the host controls. Anyone else can watch with the
spectator password, if the host set one when creating the game. The replay bar steps through the game one action
at a time, jumps to the start of a round or to an action number, and returns to the live game.

**Debrief** (specification 10). When a game ends, the banner links to the debrief: how it ended, the published
literature against the true world, luck, possible sabotage, fabrication and file-drawer totals, scores by round,
and the hidden world itself. It can be reopened later from the game list, printed, or downloaded as CSV tables.

## Playing in the terminal

The text client runs a whole game on one computer, with every seat at the same keyboard (specification,
section 7.1). It saves the game after every action, so you can stop at any time and resume later.

```sh
# Start a game on world 1 with three researchers (the save goes to games/)
.venv/Scripts/nv-play new scenarios/venus_expedition/worlds/world_seed1.json --players Anna,Ben,Cleo

# Resume a saved game
.venv/Scripts/nv-play load games/world_seed1_game123456.json
```

Type `help` in the game for the commands. The client shows the screen of the researcher who must act next;
`as NAME` switches to another researcher (in steps where everyone decides in secret, each researcher enters
their choices and then `commit`).

## AI players

Seats can be played by an AI model (specification, section 8); the provider, model, budget and prices are
in [`settings/software.yaml`](settings/software.yaml). Put your API key in `settings/api_keys.env` (copy
[`settings/api_keys.env.example`](settings/api_keys.env.example); git ignores the real file). Every AI call is
added to `settings/ai_spending.csv`, and no calls are made once `ai_total_budget` is spent.

```sh
# Watch an AI play against two random bots (the game plays itself; costs are printed)
.venv/Scripts/nv-play new scenarios/venus_expedition/worlds/world_seed1.json --players Ada,Bot1,Bot2 --seat Ada=ai --seat Bot1=random --seat Bot2=random

# Play yourself against an AI (seat types: random, selfish, cooperative, patient-selfish, patient-cooperative, ai, ai:cooperative, ai:selfish)
.venv/Scripts/nv-play new scenarios/venus_expedition/worlds/world_seed1.json --players Zoltan,Ada --seat Ada=ai

# Simulate games with AI seats (asks before starting; --max-cost caps this run)
.venv/Scripts/nv-sim run --players 3 --seats ai,random,random --games 2 --max-cost 1.00 --out results/ai01
```

## Simulating games

The simulator plays many games with automated players and writes CSV files for analysis in R or Python
(specification, section 9). Seats can be random bots, AI players (section 8) or scripted strategy bots
(section 9.4): `selfish`, `cooperative`, `patient-selfish` and `patient-cooperative`. The scripted bots' settings
are in [`settings/software.yaml`](settings/software.yaml).

```sh
# 100 games with 4 random bots, each on a freshly generated world
.venv/Scripts/nv-sim run --players 4 --games 100 --seed 42 --out results/run01

# Does a selfish field crash more often than a cooperative one? (100 games each)
.venv/Scripts/nv-sim run --players 3 --seats selfish,selfish,selfish --games 100 --out results/selfish
.venv/Scripts/nv-sim run --players 3 --seats cooperative,cooperative,cooperative --games 100 --out results/cooperative

# All games on one world, comparing three values of a setting
.venv/Scripts/nv-sim run --world scenarios/venus_expedition/worlds/world_seed1.json --sweep nobel_condition=4,5,6 --games 100 --out results/run02

# Rebuild game 17 of a run and step through it in the text client
.venv/Scripts/nv-sim record results/run01 17
.venv/Scripts/nv-play load games/run01_game17.json

# ... or open it in the browser, with spectator replay and debrief (it prints the link)
.venv/Scripts/nv-sim import results/run01 17
```

A run writes `games.csv`, `rounds.csv`, `theories.csv`, `predictions.csv` and `worlds.csv`, and prints the
share of each ending with 95% confidence intervals. Every action is checked against the game's invariants
(no negative staff or money, counters in range, every card accounted for); a game that breaks one is
reported as an error.

## Repository layout

| Path | Contents |
| --- | --- |
| `nv_core/` | Rules engine: settings, game state, actions, the phases of a round, player views and text rendering, game records |
| `nv_world/` | World generator: scenario reader, World Table generation, screening, world files, `nv-world` command |
| `nv_server/` | The multiplayer server (`nv-server`: lobby, storage, live games) and the `nv-play` text client |
| `nv_sim/` | Simulator: random bot, scripted strategy bots, invariant checks, the `nv-sim` command |
| `nv_ai/` | AI player: prompt and tools, model provider, costs and the spending ledger |
| `web/` | Browser client: lobby and game page (plain HTML, CSS and JavaScript) |
| `scenarios/` | One folder per scenario, with its scenario file and generated worlds |
| `docs/` | The rulebook, parameter file, specification and open questions |
| `tests/` | pytest tests, named after the document sections they check |

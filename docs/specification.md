# Null & Void — Software Specification

Nov 1, 2026 · @Zoltan Kekecs

## 1. Purpose and scope

This spec defines how the board game *Null & Void* is implemented in Python: a multiplayer game played together from different computers, with AI opponents able to fill any seat. It covers software only. Everything about the game itself lives in three other documents, which the software reads rather than restates:

| Document | Holds | Used by the software as |
| --- | --- | --- |
| Rulebook (`docs/rules.md`, exported from Google Docs) | every game rule, in phase order | the behaviour the rules engine implements and the tests check |
| `docs/parameter_defaults.yaml` | every numeric game setting, including the grant track and journal tier tables; top-level settings are named in the rulebook as `[name]` | data loaded at game start |
| Scenario file (`scenarios/<id>/scenario.md`) | story, input parameters and world outcomes, effect model, world acceptance criteria | data read by the world generator and shown to players |

Where this spec seems to disagree with one of them, that document is right and the spec needs fixing. Open issues are in section 12.

The project has three deliverables built on one shared rules engine:

1. **Playable game** — a multiplayer web game hosted on Google Cloud Run, with a text-first core, a simple visual interface, AI opponents, a spectator mode and an end-of-game debrief.
2. **Headless balance simulator** — runs many games without a user interface, with any mix of player types (random bots by default, AI players optionally), and writes results as CSV files for analysis.
3. **World generator** — builds a scenario's World Table from its effect model, screens it against acceptance criteria and cuts the Probe deck.

**Primary use:** teaching and demonstrating research-culture problems (replication crisis, questionable research practices) to graduate students and postdocs. Non-commercial, small scale: a handful of concurrent games at most.

**Out of scope for the first version:** in-game chat, rule-based strategic bots, a scenario editor, a polished visual design, languages other than English, user accounts.

## 2. Design principles

Five principles govern every later section; when a detail is unclear, the option that best fits them wins.

1. **Text-first, structured core.** The rules engine knows nothing about screens. It exposes a game state, a list of legal actions per player, and a text view per player. Humans and AI players act through the same action schema; the web UI is a rendering of the same views.
2. **One pure rules engine.** All game logic lives in one deterministic Python package: `apply(state, action) -> new state + events`. The server, the simulator and the tests all call this package; no rule is implemented twice.
3. **Event log is the source of truth.** A game is its scenario, its settings, its random seed and its ordered list of actions. Saving, resuming, reconnecting, replays and the debrief are all built from replaying that log.
4. **Secrets stay on the server.** The World Table, true Probe states, other players' hands and hidden actions never reach a player's browser. Each client receives only its own filtered view.
5. **Everything numeric is configurable.** Game settings are read from parameter\_defaults.yaml and scenario data from the scenario file; the code never hard-codes a value those files define. The game mirrors the physical design (decks, cards, dice) so a tabletop version stays possible.

## 3. Architecture

The system is one Python repository with a rules engine at its centre and four consumers around it: the game server, the AI player, the simulator and the world generator's tools.

&#91;embedded content: system architecture · 9 components\]

Every path runs through `nv_core`: the server, the AI player and the simulator never implement a rule themselves.

| Package | Responsibility | Depends on |
| --- | --- | --- |
| `nv_core` | Rules engine: state, actions, phases, scoring, views, text rendering | nothing (pure Python) |
| `nv_world` | Scenario loading, World Table generation, screening, Probe deck building | `nv_core` data types |
| `nv_server` | FastAPI app: lobby, joining, WebSocket updates, persistence, host controls | `nv_core`, `nv_ai` |
| `nv_ai` | AI player: prompt building, tool-call action choice, token and cost tracking | `nv_core`, Anthropic SDK |
| `nv_sim` | Headless batch simulator and random bot | `nv_core`, `nv_world`, `nv_ai` |
| `web/` | Browser client: plain HTML/JS, renders views, sends actions | server API only |
| `scenarios/` | One folder per scenario: its scenario.md and generated world files | — |
| docs/ | rules.md (exported from Google Docs), specification.md and parameter\_defaults.yaml | — |

**Technology:** Python 3.12, FastAPI, Pydantic models for every action and view, WebSockets for live updates, Firestore for persistence, Google Cloud Run for hosting, pytest for tests. The web client stays dependency-light (no build step in the first version).

## 4. World generator (`nv_world`)

The world generator turns a scenario file into a World Table, screens it against the scenario's acceptance criteria and saves it as a world file. The values it uses (states, effect sizes, urn, interactions, criteria) are in the scenario file; this section defines only the procedure.

### 4.1 Reading the scenario file

- The generator reads the first fenced `yaml` block of the scenario file and validates it against a schema. The Story section is passed as text to the interface and to the AI players.
- It stops with an error naming the field when the data is incomplete or inconsistent, e.g. a duplicated state name, an unknown effect size in the urn, or an Input Parameter Deck size (from `parameter_defaults.yaml`) that is not divisible by a parameter's state count.

### 4.2 Generating the World Table

1. **Main effects.** For each world outcome state (except one reference state per outcome when `reference_state_per_outcome` is true), pad `main_effect_urn` with zeros to the number of input states, shuffle it, and assign one value to each input state.
2. **Interactions.** For each entry in `interactions`, pick a world outcome state that has fewer than `max_interactions_per_outcome_state` interactions and two input states from different input parameters; set the sign according to `interaction_sign`.
3. **Rows.** For every input combination, give each world outcome state a score: the sum of its main effects for the input states present, plus every interaction whose two input states are both present, using `effect_sizes_logit`. Convert the scores of each world outcome to probabilities (softmax) and realise the outcome as `outcome_realisation` says.
4. **Record** the seed, the effect assignments, the interactions and the table.

### 4.3 Screening

- List every possible theory: any non-empty choice of at most one state per input parameter, combined with any non-empty choice of at most one state per world outcome. For each, compute its true accuracy (weighted by state weights) and coverage.
- A state's base rate is its weighted share of rows. A theory is Nobel-grade when it has at most `nobel_grade.max_input_parameters` input parameters and at least `nobel_grade.min_accuracy` accuracy.
- Check `acceptance_criteria`. If the world fails, regenerate with the next seed, up to `max_generation_tries`. The report states how many tries were needed.

### 4.4 World files

- A world file (JSON) holds the scenario id, a hash of the scenario's YAML block, the seed, the effect assignments, the interactions, the World Table and the screening report. The hash lets the software warn when a scenario was edited after a world was generated.
- During play the engine builds the Probe deck, Input Parameter Decks and sensor noise as the rulebook describes, from the world file and the game settings; all shuffles use the game seed (5.6). Experiment outcomes are looked up in the World Table.

### 4.5 Command-line tools

- `nv-world generate <scenario.md> --seed <n>` → a world file plus its screening report.
- `nv-world report <world file>` → base rates, the best theories by number of input parameters and the count of Nobel-grade theories, as text and CSV.

## 5. Rules engine (`nv_core`)

The engine is a pure, deterministic state machine: given a state and a legal action it returns the next state and a list of events, and it never touches the network, the clock or a database.

### 5.1 State model

The `GameState` (Pydantic, serialisable to JSON) contains:

- **Setup:** scenario id, world id, settings, seed, player seats and turn order, alliance list.
- **Clock:** round number, period (Calm or Crisis), current phase and step, Game Period Deck, crisis tracker (rounds in crisis, unsuccessful predictions).
- **World Grid:** per Probe column — specialty parameters, sensor level per non-specialty parameter, the current Probe stack (true inputs and outcomes), the readings shown, Probe time owner, Hot topic marker.
- **Per researcher:** academic credit, money, Grant funding and Talent development track positions, staff (postdocs and students, each with a task), unpublished theories and methods, experiment card pool, records (Fresh and Stale), predictions, patents owned.
- **Submission Portal:** awaiting-review positions, Revise area, Accept area with rounds-in-processing tokens.
- **Published papers:** each theory or method with its author, journal tier, open-access flag, Nobel Prize and Retraction counters, Fresh-out-of-print marker, sideways (cited this round) flag and attached patents.
- **Hidden bookkeeping for the debrief:** e.g. which records were fabricated, which predictions were made against experiment knowledge. Never shown in player views.

### 5.2 Round structure

The engine runs the phases in the order, and with the steps, that the rulebook gives. This spec adds only how each step takes player input: **simultaneous secret** (every player commits, then all commits are revealed together), **sequential** (in turn order, until everyone passes) or **automatic** (no decisions).

| Rulebook section | Input mode |
| --- | --- |
| Hiring and task allocation phase | simultaneous secret |
| Student task check phase | automatic dice, then simultaneous choice of which students leave |
| Experimentation and equipment phase | sequential |
| Probe time | sequential, in the order the rulebook sets |
| Observation and prediction phase: revealing input parameters, pruning, outcome reveal, scoring, recording observations | automatic |
| Observation and prediction phase: formulating predictions and preregistration; prediction reveal | simultaneous secret |
| Development phase | simultaneous secret |
| Publication: submission and revisions | simultaneous |
| Publication: peer review votes | simultaneous secret (allocation, random draws and tally automatic) |
| Publication: article processing and publication | automatic |
| Talent development phase, Clean-up phase | automatic |
| Alliance actions | any time the rulebook allows |

Win and loss checks (Nobel Prize, Crisis Crash, end of the Crisis period) run after every event that can trigger them, so the game ends at exactly the moment the rules say.

### 5.3 Actions

Every action is a typed Pydantic model in one discriminated union, so the server, the AI player and the simulator all validate the same way. Illustrative examples (the action union in the code is authoritative): `AllocateStaff`, `HirePostdocs`, `FirePostdoc`, `HireStudents`, `ChooseLeavingStudents`, `RunExperiment(specified_states, cited_methods)`, `InstallSensor(probe, parameter, cited_methods)`, `Pass`, `ClaimProbeTime(probe)`, `BuildRecord(cards)`, `MakePrediction(theory, probe)`, `Preregister(predictions)`, `RevealPredictions(predictions)`, `FormulateTheory(inputs, outcomes)`, `DevelopMethod(parameter)`, `Submit(manuscript, tier, records, pay_apc)`, `Revise(manuscript)`, `ReviewVote(position, vote)`, `ProposeAlliance`, `AcceptAlliance`, `LeaveAlliance`, `CommitPhase`.

- `legal_actions(state, player)` returns what the player may do now. Where the option space is large (theories, records, predictions), it returns templates with their constraints, and `validate(state, action)` gives a clear reason when an action is refused.
- In simultaneous phases, a player's choices stay editable until they send `CommitPhase`; other players only see "committed" or "still deciding".

### 5.4 Views and text rendering

- `player_view(state, player)` — everything public plus that player's own hidden material (lab shield, hand, records, unrevealed predictions).
- `spectator_view(state)` — everything, including the World Table, true Probe states and all hands.
- `render_text(view)` — a compact, stable text rendering with short ids (`P1`–`P4` for Probes, `IP1`–`IP4`, `WO1`–`WO2`, `T7` for theory 7, `M3`, `R12` for records). The text client and the AI player use it directly; the web UI renders the same view as JSON.
- The event log has a public part (what everyone saw happen) and a full part (for spectators, replays and the debrief).

### 5.5 Records

Records follow the rulebook. The engine adds one thing the rules do not need: each experiment record is silently flagged as fabricated when its cards do not match a single experiment the player actually ran. The flag never appears in player views; it feeds the debrief (section 10).

### 5.6 Randomness

All randomness comes from one seeded generator per game, split into named streams (Probe deck, sensor noise, experiment draws, dice, peer-review allocation). Replaying the same seed and the same actions always reproduces the same game.

## 6. Multiplayer server (`nv_server`)

The server is a stateless FastAPI app on Google Cloud Run: every request rebuilds the game from Firestore, applies one action through the engine, stores it, and pushes fresh views to everyone connected.

### 6.1 Persistence

- **Firestore layout:** `games/{id}` holds metadata (scenario, world, settings, seed, seats, status, hashed join and spectator passwords); `games/{id}/actions/{seq}` holds the ordered action log; `games/{id}/snapshots/{seq}` holds a state snapshot at the start of each round, so loading never replays a whole game.
- **Writes:** an action is accepted only if its sequence number is the next one, checked in a Firestore transaction. Two players acting at once can never corrupt the log; the loser simply retries against the new state.
- **Saving is automatic.** Every action is stored the moment it is accepted, so a game can stop at any point and resume days later from the host's link.

### 6.2 Live updates

- Each browser holds a WebSocket. After every accepted action, the server sends each connection its own filtered view (player, spectator or lobby).
- Cloud Run closes WebSockets after its request timeout (up to 60 minutes); the client reconnects automatically and receives the current view, so this is invisible to players.
- The first version runs with a maximum of one Cloud Run instance, which is plenty for a few concurrent games and keeps live updates simple. If more instances are ever needed, each instance subscribes to Firestore changes for the games it serves.

### 6.3 Creating and joining games

1. The host opens the lobby, chooses a scenario and world (or generates a new one), a settings preset, and the seats (within the player limits in parameter\_defaults.yaml), each marked human or AI (with its model).
2. The host gets a **join link** and an optional password, and a separate **spectator password**.
3. A player opens the link, enters a nickname and picks a free seat and colour. The browser keeps a seat token, so a refresh or a dropped connection rejoins the same seat.
4. The host starts the game when all human seats are filled. Settings are locked from then on.

### 6.4 Host controls

- Start, pause and resume the game; end it early (it still gets a debrief).
- Hand a disconnected player's seat to an AI and back again.
- Remove a player or reassign a seat.
- See who the game is waiting for in each simultaneous phase. There are no turn timers.

### 6.5 Security and data

- Hidden information never leaves the server except in the view of the player entitled to it.
- The Anthropic API key lives in Google Secret Manager and is used only server-side.
- No accounts and no personal data beyond nicknames. If logged games are ever used as research data, consent and ethics approval are needed first; that is outside this spec.

## 7. Clients

There are two clients, a text client and a simple web UI, and both show the same view the engine produces; neither contains game logic.

### 7.1 Text client

- A terminal program that connects to the server (or runs a local game in-process) and prints `render_text` views.
- Actions are typed as short commands (`experiment IP1=fat_blue IP3=sugar cite M3`, `predict T7 P2`, `commit`), parsed into the same action models.
- Main uses: developing and testing the engine, debugging, and checking that what an AI player sees is complete and readable.

### 7.2 Web UI (first version)

Plain and functional, desktop-first, English only. One page with these areas:

| Area | Shows | Player can |
| --- | --- | --- |
| World Grid | Probe columns: readings, sensor levels, Probe time, Hot topic; outcomes once revealed | claim Probe time, install sensors |
| Lab (behind the shield) | staff and tasks, money, hand of theories and methods, experiment pool, records, predictions | allocate staff, run experiments, build records, formulate, predict, preregister |
| Literature | published theories and methods with counters, authors, tiers, patents | cite, inspect |
| Submission Portal | manuscripts by position, tier and author; Revise and Accept areas | submit, revise, vote in peer review |
| Tracks | academic credit, Grant funding, Talent development, Game Period Deck count, crisis tracker | — |
| Status bar | round, phase, who is still deciding, AI cost so far | commit the phase |
| Event log | public events in order, filterable | — |

- Theories, predictions and records are built by picking a state per row from dropdowns that mirror the card layout (a blank option for unspecified rows).
- Each panel has a "show as text" toggle that displays the same `render_text` output the AI sees.
- Each player uses their own device, so their lab is always open on their screen and never sent to anyone else's. Players at the same table are trusted not to look at each other's screens, as with a physical lab shield.

### 7.3 Spectator mode

- Opened with the spectator password; read-only.
- Shows everything: the World Table, true Probe states and outcomes before reveal, every lab, every hidden prediction and record (fabricated ones marked), the effect model behind the table.
- Intended for the teacher or facilitator, and for replaying finished games step by step (forward, back, jump to a round).

## 8. AI opponents (`nv_ai`)

An AI seat is a Claude model that reads the same text view a human could and answers each decision with a tool call naming one legal action. It never sees hidden information it isn't entitled to.

### 8.1 One decision

1. The engine signals that an AI seat must act (a sequential turn, or its commit in a simultaneous phase).
2. `nv_ai` builds the request:
   - **System prompt** (cached): a condensed rules summary kept as a file in the repo, the scenario story, and the seat's persona (section 8.3).
   - **Context:** the seat's `render_text` view, the recent public event log, and the seat's own notes (8.2).
   - **Tools:** one tool per action type that is legal now, with JSON schemas generated from the action models.
3. The model replies with a tool call and a one-line reason. The engine validates it; if it is refused, the error goes back to the model for up to `ai_retry_limit` attempts.
4. If the model still fails, goes over its token limit, or the API errors, the seat takes a safe default action (pass, or commit with no further choices), and the log records why.

In simultaneous phases, AI seats decide in parallel in the background while humans play, so they rarely hold up the table.

### 8.2 Memory

The API is stateless, so each AI seat keeps a private notes field in the game state (plans, which theories it is working towards, what it has learned from experiments). The model can update its notes as part of any decision, within a set length. The notes are hidden from other players and shown in spectator mode and the debrief.

### 8.3 Personas

Each AI seat can be given a persona in the lobby: **neutral** (default: play to win), **cooperative** (share knowledge, avoid sabotage) or **selfish** (sabotage rivals' Nobel candidates when it can). This lets the simulator test your target outcome rates for cooperative and selfish play with AI players.

### 8.4 Token limits and cost display

- **Per-decision limits:** `ai_max_output_tokens` caps each reply; `ai_max_input_tokens` caps the context, trimming the oldest log entries first.
- **Cost tracking:** token counts come from each API response's usage report and are multiplied by a price table in the settings file (per model, per million input, output and cached tokens). The table is editable, because prices change.
- **Display:** the status bar shows the running cost per AI seat and in total; the host can open a per-decision breakdown. The debrief and the simulator report the total too.
- There is no hard cost cap per game, as agreed; the simulator has one (section 9).

### 8.5 Table talk

AI seats cannot hear spoken conversation. They see only in-game actions: alliance proposals and acceptances, preregistrations, revealed predictions, publications. Players at the table should know this. Text chat that AI seats can read is a possible later addition.

## 9. Headless balance simulator (`nv_sim`)

The simulator plays complete games in-process, without the server, with any mix of player types, and writes CSV files for analysis in R or Python.

### 9.1 Player interface

Every automated player implements one method, `choose(view, legal_actions) -> action`. The first version ships two:

- **Random bot** (default): picks uniformly among legal actions, sampling sensibly where the option space is large (e.g. a random valid theory or record), and always commits eventually. Optional weights (e.g. how often to pass) keep games from stalling.
- **AI player:** the same `nv_ai` player used in live games, with its persona.

Strategic rule-based bots can be added later through the same interface, without changing anything else.

### 9.2 Running batches

```
nv-sim run --scenario venus_expedition --players 4 \
  --seats random,random,random,ai:selfish \
  --games 1000 --seed 42 --set nobel_condition=5 --out results/run01
```

- `--world` fixes one world; without it, each game generates and screens a fresh world, so results average over worlds.
- `--sweep nobel_condition=4,5,6` runs every combination of the listed settings.
- Games run in parallel processes; each game's seed is recorded, so any single game can be replayed in the text client or in spectator mode.
- **AI cost guard:** before a batch with AI seats starts, the simulator estimates its cost from a short pilot and asks for confirmation; `--max-cost` stops the batch when reached.

### 9.3 Output files

| File | One row per | Key columns |
| --- | --- | --- |
| `games.csv` | game | seed, settings, world id, seat types, rounds, crisis start round, ending (Nobel, Crisis Crash, credit), winners, final credit per seat, AI cost |
| `rounds.csv` | game × round | staff, money, credit per seat, papers published, predictions made and revealed |
| `theories.csv` | published theory | author, tier, true accuracy, coverage, successes, failures, highest Nobel counter, retracted |
| `predictions.csv` | prediction | theory, Probe, preregistered, revealed, success, whether the predictor had experiment knowledge of failure |
| `worlds.csv` | world | base rates, best theory accuracy by number of inputs, count of Nobel-grade theories |

A short text summary prints at the end: the share of each ending with 95% confidence intervals, and the median game length.

## 10. End-of-game debrief

When a game ends, every player sees a debrief that reveals the hidden world and shows how the published literature compared with the truth; this is the main teaching moment.

It is built entirely from the full event log and the World Table, so it can also be opened later for any finished game, and exported as a printable page plus CSV.

| Panel | What it shows | Linked to players? |
| --- | --- | --- |
| How it ended | Nobel Prize (which theory, its streak), Crisis Crash (which failures), or final credit ranking; alliances | yes |
| The real world | the World Table, the designed effects and interactions, base rates | — |
| The literature vs. the truth | every published theory: author, tier, observed success rate in the game, true accuracy, retracted or not | yes |
| Luck | successful predictions that had a low true chance of success, failures of highly accurate theories, the chance of the Nobel streak | yes |
| Sabotage | revealed predictions that failed although the predictor's own experiments showed the theory would fail there; whose theory it hit and its Nobel counter at the time | yes |
| Fabrication | number of fabricated records, how many published papers relied on them, and those papers' true accuracy | no, totals only |
| File drawer | predictions made but never revealed, and their success rate compared with revealed ones | no, totals only |
| Peer review | acceptance rate by tier; papers accepted with fabricated or mismatched support | no, totals only |
| Over time | academic credit per researcher by round, and the Nobel counters of leading theories | yes |

Sabotage is inferred, not certain: the debrief labels it "failed despite contrary evidence the predictor held". AI seats' notes and reasons can be shown alongside, which helps explain their play.

## 11. Configuration

Game settings come from `docs/parameter_defaults.yaml`, then the scenario's `parameter_overrides`, then any changes the host makes in the lobby before the game starts. Every game stores the full settings it was played with. The settings loader:

- reads the YAML file and validates it against a schema: value types, required settings, and the shape of `grant_track` and `journal_tiers`;
- stops with an error naming any setting that is missing or has the wrong type.

The software's own settings live in `settings/software.yaml`:

| Setting | Default |
| --- | --- |
| `ai_default_model` | a mid-priced Claude model, chosen per seat in the lobby |
| `ai_max_output_tokens` | 2,000 per decision |
| `ai_max_input_tokens` | 30,000 per decision |
| `ai_retry_limit` | 2 |
| `ai_notes_max_chars` | 2,000 |
| `ai_price_table` | per model: input, output and cached-input price per million tokens |
| `snapshot_every` | each round |
| `max_instances` (Cloud Run) | 1 |

The AI defaults are starting points to tune with the simulator, not tested values.

## 12. Open issues

All earlier rule questions are settled in rulebook v4; these items remain open.

- [ ] **Condensed rules summary for AI players.** Written at the end of the project from the final rulebook, so only one rules document needs maintaining until then.
- [ ] **Balance check:** whether `[nobel_condition]` consecutive successes fit within the Calm period (about 15 rounds). To be tested with the simulator.

## 13. Milestones and acceptance criteria

Build in this order, so the rules and numbers are mostly tuned before anyone plays in a browser; each milestone is done when its acceptance check passes.

| # | Milestone | Done when |
| --- | --- | --- |
| 1 | World generator and report | The same scenario and seed always give the same World Table; the report lists base rates and Nobel-grade theories; accuracy calculations are unit-tested against a hand-checked small world. |
| 2 | Rules engine and text client (local, all seats on one machine) | A full game can be played by hand in the text client; replaying the action log reproduces the final state exactly. |
| 3 | Random bot and simulator | 1,000 random-bot games finish without errors or broken invariants (e.g. no negative staff, one Probe time per Probe, counters within range); CSV outputs are written. |
| 4 | AI player | An AI seat finishes complete games in the text client; invalid moves fall back safely; token use and cost are reported. |
| 5 | Server, persistence and web UI | 2–5 people on separate computers finish a game; a refreshed browser rejoins its seat; a paused game resumes after a server restart. |
| 6 | Spectator mode and debrief | A spectator sees the hidden World Table; the debrief appears at game end and can be reopened later; fabrication and file-drawer panels show totals only. |
| 7 | Deployment | Runs on Google Cloud Run with Firestore and Secret Manager; a game with an AI seat works end to end from outside the local network. |

**Testing throughout:**

- One or more unit tests per rule section of the rulebook, named after the section, so a rules change points to the tests to update.
- A consistency check on every commit: every `[parameter]` named in the rulebook exists in `parameter_defaults.yaml`, every top-level setting there is used, and every scenario file passes its schema.
- Saved "golden" games whose replays must not change unless a rule changes on purpose.
- Invariant checks run after every action in tests and in the simulator.
- A test that no player view contains hidden information belonging to someone else.

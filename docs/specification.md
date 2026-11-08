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
2. **Headless balance simulator** — runs many games without a user interface, with any mix of player types (random bots by default, scripted strategy bots and AI players optionally), and writes results as CSV files for analysis.
3. **World generator** — builds a scenario's World Table from its effect model, screens it against acceptance criteria and saves it as a world file.

**Primary use:** teaching and demonstrating research-culture problems (replication crisis, questionable research practices) to graduate students and postdocs. Non-commercial, small scale: a handful of concurrent games at most.

**Out of scope for the first version:** in-game chat, a scenario editor, a polished visual design, languages other than English, user accounts.

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
| `nv_core` | Rules engine: settings loading, state, actions, phases, scoring, views, text rendering; builds the Probe deck, Input Parameter Decks and sensor noise from a world file; the evidence tally of what a player has seen (9.4) | no other project package; Pydantic and PyYAML only (no network, clock or database) |
| `nv_world` | Scenario loading, World Table generation, screening, world files | `nv_core` data types and settings |
| `nv_server` | FastAPI app: lobby, joining, WebSocket updates, persistence, host controls | `nv_core`, `nv_ai`, `nv_sim` (scripted bot seats) |
| `nv_ai` | AI player: prompt building, tool-call action choice, token and cost tracking | `nv_core`, the model provider's SDK (OpenAI first, Anthropic later) |
| `nv_sim` | Headless batch simulator, random bot and scripted strategy bots | `nv_core`, `nv_world`, `nv_ai` |
| `web/` | Browser client: plain HTML/JS, renders views, sends actions | server API only |
| `scenarios/` | One folder per scenario: its scenario.md and generated world files | — |
| docs/ | rules.md (exported from Google Docs), specification.md and parameter\_defaults.yaml | — |

**Technology:** the latest stable Python (3.14 when this was written; the project requires at least that version), FastAPI, Pydantic models for every action and view, PyYAML for the settings and scenario files, WebSockets for live updates, SQLite (local) and Firestore (deployed) for persistence, Google Cloud Run for hosting, pytest for tests. The web client stays dependency-light (no build step in the first version).

## 4. World generator (`nv_world`)

The world generator turns a scenario file into a World Table, screens it against the scenario's acceptance criteria and saves it as a world file. The values it uses (states, effect sizes, urn, interactions, criteria) are in the scenario file; this section defines only the procedure.

### 4.1 Reading the scenario file

- The generator reads the first fenced `yaml` block of the scenario file and validates it against a schema. The Story section is passed as text to the interface and to the AI players (a scenario without a Story section has an empty story).
- It stops with an error naming the field when the data is incomplete or inconsistent, e.g. a state name repeated within one input parameter or world outcome (the same name in different ones is fine), an unknown effect size in the urn, or an Input Parameter Deck size (from `parameter_defaults.yaml`, after the scenario's overrides) that is not divisible by a parameter's state count.
- Every state of an input parameter is equally common: the World Table has one row per input combination, and each row counts once (scenarios have no state weights, so the Probe deck and the Input Parameter Decks the rulebook describes match the table).

### 4.2 Generating the World Table

1. **Main effects.** For each world outcome state (except one reference state per outcome when `reference_state_per_outcome` is true; the reference state is the first listed state, and it gets neither main effects nor interactions), pad `main_effect_urn` with zeros to the number of input states, shuffle it, and assign one value to each input state.
2. **Interactions.** For each entry in `interactions`, pick a world outcome state uniformly from those that have fewer than `max_interactions_per_outcome_state` interactions, and a pair of input states uniformly from all pairs whose two states belong to different input parameters (the pair is drawn independently, so different outcome states, or one outcome state allowed several interactions, may get the same pair; repeated interactions add up); set the sign according to `interaction_sign`: `random` (positive or negative with equal probability, drawn per interaction), `positive` or `negative`.
3. **Rows.** For every input combination (rows in input-parameter order: the first input parameter changes slowest, states in the order the scenario lists them), give each world outcome state a score: the sum of its main effects for the input states present, plus every interaction whose two input states are both present, using `effect_sizes_logit`. Convert the scores of each world outcome to probabilities (softmax) and realise the outcome as `outcome_realisation` says.
4. **Record** the seed, the effect assignments, the interactions and the table.

### 4.3 Screening

- List every possible theory: any non-empty choice of at most one state per input parameter, combined with any non-empty choice of at most one state per world outcome.
- A theory's **coverage** is the share of World Table rows whose input states match all of the theory's input states. Its **accuracy** is the share of those covered rows in which every world outcome state of the theory matches the row's realised outcome. Both are computed from the realised table, not from the softmax probabilities.
- A state's **base rate** is the share of rows in which it is the realised outcome.
- A theory is **Nobel-grade** when it has at most `nobel_grade.max_input_parameters` input parameters and at least `nobel_grade.min_accuracy` accuracy. The report gives three counts: every Nobel-grade theory; distinct **input patterns** (input-state combinations with at least one Nobel-grade theory); and **maximal** theories (Nobel-grade theories not implied by another Nobel-grade theory with the same input states and more world outcome states). `nobel_grade.count` in the scenario names the count that `min_count` and `max_count` apply to.
- `max_one_input_theory_accuracy` applies to every theory with exactly one input parameter, whatever its world outcomes.
- **Comparisons:** a `max_…` criterion passes when the value is at or below the limit (≤), a `min_…` criterion when it is at or above it (≥). Shares are computed and compared as exact fractions, so a value on the limit is never misjudged because of floating-point rounding; reports print them as decimals.
- Check `acceptance_criteria`. If the world fails, generate again, up to `max_generation_tries` tries in total. Try *k* (counting from 0) of a requested seed *s* uses the seed *s* × `max_generation_tries` + *k*, so the tries of different requested seeds never overlap and different requested seeds give different worlds. The world file records both the requested and the accepted seed, and the report states how many tries were needed. If every try fails, the generator stops with an error that says how often each criterion failed.

### 4.4 World files

- A world file (JSON) holds the scenario id, a hash of the scenario's YAML block, the requested and accepted seeds, the number of tries, the effect assignments, the interactions, the World Table and the screening report. The hash is taken of the parsed YAML data, so editing comments or layout does not change it; it lets the software warn when a scenario's data was edited after a world was generated.
- The world file holds no decks. During play `nv_core` builds the Probe deck, Input Parameter Decks and sensor noise as the rulebook describes, from the world file and the game settings; all shuffles use the game seed (5.6). Experiment outcomes are looked up in the World Table.

### 4.5 Command-line tools

- `nv-world generate <scenario.md> --seed <n> [--out <path>]` → a world file (default `scenarios/<id>/worlds/world_seed<n>.json`) plus its screening report, including the number of tries. Exit code 0, or 1 with the failure tally when no world passes.
- `nv-world report <world file> [--scenario <path>] [--csv-dir <dir>] [--top <n>]` → base rates, the best theories by number of input parameters and the count of Nobel-grade theories, as text and CSV. The report recomputes these from the world's table with the current scenario file (for names and criteria), warns when the scenario's data changed since generation, and stops with an error when the table no longer fits the scenario. The CSV files are `base_rates.csv`, `best_theories.csv` (the `--top` best per number of input parameters), `nobel_grade.csv` and `summary.csv` (one row, in the shape of the simulator's `worlds.csv`); shares are printed as decimals.

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
- **Hidden bookkeeping for the debrief:** every prediction of the game with the visible readings of its Probe (so the debrief can tell which predictions were made against the predictor's own experiment knowledge); every published paper, kept after its supporting records are discarded and after a retraction, with how many of its records were fabricated; every peer review decision; the academic credit and Nobel Prize counters at the end of each round. Never shown in player views.

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
| Scoring predictions: the order of one researcher's predictions on the same Probe | simultaneous secret, asked only when the order decides who wins the Nobel Prize (otherwise automatic) |
| Development phase | simultaneous secret |
| Publication: submission and revisions | open: any researcher acts at any time, each action is applied the moment it arrives (so the first to submit gets the free Submission Portal position), until everyone has committed. Before committing, a researcher can withdraw a submission or revision they made in this step: the submission fee and APC are refunded, the development stack and supporting records go back to where they were, the write-up staff member is free again, and a freed Portal position goes to the next submission (other manuscripts keep their positions) |
| Publication: peer review votes | simultaneous secret (allocation, random draws and tally automatic) |
| Publication: article processing and publication | automatic |
| Talent development phase, Clean-up phase | automatic |
| Alliance actions | any time the rulebook allows |
| Alliance: "last chance to leave" stage | simultaneous secret |

Win and loss checks (Nobel Prize, Crisis Crash, end of the Crisis period) run after every event that can trigger them, so the game ends at exactly the moment the rules say.

### 5.3 Actions

Every action is a typed Pydantic model in one discriminated union, so the server, the AI player and the simulator all validate the same way. Illustrative examples (the action union in the code is authoritative): `AllocateStaff`, `HirePostdocs`, `FirePostdoc`, `HireStudents`, `ChooseLeavingStudents`, `RunExperiment(specified_states, cited_methods)`, `InstallSensor(probe, parameter, cited_methods)`, `Pass`, `ClaimProbeTime(probe)`, `BuildRecord(cards)`, `MakePrediction(theory, probe)`, `Preregister(predictions)`, `RevealPredictions(predictions)`, `FormulateTheory(inputs, outcomes)`, `DevelopMethod(parameter)`, `Submit(manuscript, tier, records, pay_apc)`, `Revise(manuscript)`, `WithdrawSubmission(manuscript)`, `ReviewVote(position, vote)`, `ProposeAlliance`, `AcceptAlliance`, `LeaveAlliance`, `CommitPhase`.

- `legal_actions(state, player)` returns what the player may do now. Where the option space is large (theories, records, predictions), it returns templates with their constraints, and `validate(state, action)` gives a clear reason when an action is refused.
- In simultaneous phases, a player's choices stay editable until they send `CommitPhase`; other players only see "committed" or "still deciding".

### 5.4 Views and text rendering

- `player_view(state, player)` — everything public plus that player's own hidden material (lab shield, hand, records, unrevealed predictions).
- `spectator_view(state)` — everything, including the World Table, true Probe states and all hands.
- `render_text(view)` — a compact, stable text rendering with short ids (`P1`–`P4` for Probes, `IP1`–`IP4`, `WO1`–`WO2`, `T7` for published theory 7, `M3` for a published method, `D5` for a development stack and its manuscript, `O12` for an observation record, `E9` for an experiment, `Q4` for a prediction). The text client and the AI player use it directly; the web UI renders the same view as JSON.
- The event log has a public part (what everyone saw happen) and a full part (for spectators, replays and the debrief).

### 5.5 Records

Records follow the rulebook. The engine refuses supporting records that mismatch the theory they support. (A tabletop game could let players submit mismatching records and leave it to reviewers to catch them; the software does not, so that no one has to stop and check for cheating.) Fabrication in the software therefore means one thing: an experiment record whose cards do not come from a single experiment the player actually ran. The engine silently flags such records. The flag never appears in player views; it feeds the debrief (section 10).

### 5.6 Randomness

All randomness comes from one seeded generator per game, split into named streams (Probe deck, sensor noise, experiment draws, dice, peer-review allocation). Replaying the same seed and the same actions always reproduces the same game.

### 5.7 Rule clarifications

The rulebook is written for human readers and leaves some details to common sense. The designer's answers on those details are listed here, by rulebook section, so the engine and its tests read them the same way. The rulebook still wins where it says otherwise.

- **Preregistration pruning (identical theories).** Only theories the predictor may use are candidates (not someone else's theory with a Fresh out of print marker). When the rulebook's preferences still leave a tie (theories published in the same round), the one whose author is earlier in turn order is cited.
- **Outcome and Prediction Reveal (one researcher, one theory twice).** A researcher must discard all but one of their own revealed predictions that are based on the same theory. The engine applies this when the choice is made: it does not let a researcher preregister or reveal a second prediction based on a theory they already preregistered or revealed that round.
- **Supporting observational and experimental records.** Every record stack has exactly one card per input parameter and world outcome. An observation record is always a full, intact Probe column. An experiment record is built from the experiment cards of one record area. Observation and experiment cards are never mixed in one stack.
- **Supporting records for methods.** A method manuscript must meet the tier's record minimums (`min_records`, `min_observations`, `min_experiments`), with any full record stacks. `min_elements` does not apply to methods.
- **Peer review.** A researcher can be dealt, and vote on, their own manuscript. Every allocation card a researcher receives gives one vote, so a researcher dealt two cards for the same manuscript votes twice. Votes on a manuscript that has not yet reached `[min_reviews_for_decision]` votes stay with it into later rounds.
- **Research grants (staff used).** The number of Grants staff counted as used is the admin requirement of the position held before that round's grant check moves the marker.
- **Crisis (missed Probes).** A Probe whose only predictions were pruned counts as a Probe where no one made a prediction.
- **Revealing input parameters (rebuilding the Probe deck).** When the Probe deck is exhausted and the discard pile holds fewer than `[probe_deck_min_rebuild_stacks]` complete Probe stacks, the full Probe deck is rebuilt and reshuffled instead. Likewise, when an Input Parameter Deck is exhausted and its discard pile is empty (every card is held in records or manuscripts), a fresh full Input Parameter Deck is built and shuffled.
- **Academic credit rules (at 0 academic credit).** A researcher at 0 academic credit cannot fire a postdoc other than the un-fundable ones the rulebook makes them fire, must use every staff member that can still be used at the steps where staff are used (experiments and sensors, prediction reveal, development, write-up; they need not make predictions, and their staff allocation is not restricted), and cannot reveal a non-preregistered prediction that failed.

## 6. Multiplayer server (`nv_server`)

The server is a stateless FastAPI app: every request rebuilds the game from storage, applies one action through the engine, stores it, and pushes fresh views to everyone connected. It runs locally first (milestone 5) and on Google Cloud Run later (milestone 7).

### 6.1 Persistence

- **One storage interface, two backends:** a local SQLite file (milestone 5) and Firestore (milestone 7) store the same data, so the server does not care which one it runs on.
- **Layout** (Firestore paths; the SQLite tables mirror them): `games/{id}` holds metadata (scenario, world, settings, seed, seats, status, hashed join and spectator passwords); `games/{id}/actions/{seq}` holds the ordered action log, each action with the events it produced; `games/{id}/snapshots/{seq}` holds a state snapshot at the start of each round (also used to replay any action: 7.3); `games/{id}/ai_decisions/{n}` holds the AI decision log. Loading starts from the latest snapshot and applies the actions after it; the stored events give the event log and the scripted bots' memory, so loading never replays a whole game. Metadata also holds the AI seats' notes and costs, and the world file's drawn effects, interactions and row probabilities (for the debrief).
- **AI spending:** on the deployed server the ledger's total and entries are in Firestore (`ai_spending/total`), because a Cloud Run instance's disk does not last; `ai_total_budget` therefore holds across restarts. It counts deployed spending only; local runs keep their own ledger file.
- **Writes:** an action is accepted only if its sequence number is the next one, checked in a transaction. Two players acting at once can never corrupt the log; the loser simply retries against the new state.
- **Saving is automatic.** Every action is stored the moment it is accepted, so a game can stop at any point and resume days later from the host's link.

### 6.2 Live updates

- Each browser holds a WebSocket. After every accepted action, the server sends each connection its own filtered view (player, spectator or lobby), numbered with the action's sequence number; the browser that acted also gets an `accepted` message with that number, so it knows which views are newer than its own action. A refused action gets an `error` message with the engine's reason.
- Each automated seat (scripted bot, random bot or AI) has a background worker that acts whenever the seat must decide; AI seats think in a separate thread, so they never hold up anyone else.
- Cloud Run closes WebSockets after its request timeout (up to 60 minutes); the client reconnects automatically and receives the current view, so this is invisible to players.
- The first version runs with a maximum of one Cloud Run instance, which is plenty for a few concurrent games and keeps live updates simple. If more instances are ever needed, each instance subscribes to Firestore changes for the games it serves.

### 6.3 Creating and joining games

1. The host opens the lobby (on a server with an **organiser password**, which the deployed server must have, entering it is needed to create a game or see the list of games; players only need their link), chooses a scenario and world (or generates a new one), a settings preset, and the seats (within the player limits in parameter\_defaults.yaml), each marked human, AI (with its model and persona) or scripted bot (9.4).
2. The host gets a **join link** and an optional password, and an optional **spectator password**. Without a spectator password, only the host link can spectate.
3. A player opens the link, enters a nickname and picks a free seat and a colour from a fixed list. The browser keeps a seat token, so a refresh or a dropped connection rejoins the same seat; a link with the token (`#seat=...`) takes the seat to another device.
4. The host starts the game when all human seats are filled. Settings are locked from then on.

### 6.4 Host controls

- Start, pause and resume the game; end it early (it still gets a debrief).
- Hand a disconnected player's seat to an AI and back again.
- Remove a player or reassign a seat.
- See who the game is waiting for in each simultaneous phase. There are no turn timers.
- Spectate at any time (7.3), also while playing a seat in the same browser: the host is trusted, like a facilitator who knows the hidden world.

### 6.5 Security and data

- Hidden information never leaves the server except in the view of the player entitled to it.
- The model provider's API key lives in Google Secret Manager and is used only server-side. For local runs it is read from `settings/api_keys.env`, which git ignores and is never committed.
- No accounts and no personal data beyond nicknames. If logged games are ever used as research data, consent and ethics approval are needed first; that is outside this spec.
- The organiser password (6.3) is what stops strangers from spending the AI budget. It lives in Secret Manager, and the server refuses to start on Firestore without one.

### 6.6 Deployment

- `deploy/cloud_run.py` does the work; the project, region and service limits are in `settings/cloud.yaml`.
- The image is built from the `Dockerfile`, which names each folder it copies, so local keys, the local ledger and saved games cannot end up in it; `.gcloudignore` also keeps them out of the upload.
- The server runs as its own service account, which may use Firestore and read its two secrets.

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
- A "show as text" toggle replaces the board with the same `render_text` output the AI sees.
- Each player uses their own device, so their lab is always open on their screen and never sent to anyone else's. Players at the same table are trusted not to look at each other's screens, as with a physical lab shield.

Every page's top row links to the **credits** page (`/credits`), which opens in a new tab and shows `docs/credits.md`.

### 7.3 Spectator mode

- Opened with the host link, or by anyone with the spectator password (if the host set one); read-only.
- Shows everything: the World Table, true Probe states and outcomes before reveal, every lab, every hidden prediction and record (fabricated ones marked), the AI seats' notes. The effect model behind the table is in the debrief.
- Intended for the teacher or facilitator, and for replaying games step by step: one action forward or back, to the start of any round, or to any action number (out of the total so far), and back to the live game. A replay is rebuilt from the latest round snapshot before that action. A game played under older rules may not replay past the point where the rules changed; the replay then says so and stops there.
- Simulated games can be opened the same way: `nv-sim import` (9.2) stores one in the server's database as a finished game.

### 7.4 Board design (milestone 8)

The web UI's world states become icons in strips. This section records the design agreed with the prototype; where a detail is not listed here, the prototype shows the intent.

**Strips and columns.** Every thing that holds world states is one horizontal strip: Probes, records, theories (unpublished and published), manuscripts, and whatever is being formulated (a theory, an experiment, a prediction, a submission). All strips share one column order, input parameters then world outcomes, so that the panels line up above each other and each state's column can be scanned downwards. The World Grid, experimentation and theory formulation are horizontal like the rest. A blank slot is an empty dashed box and a hidden outcome a "?". Every state has its icon (`web/icons/<scenario>/`, made by `asset_generation/make_icons.py`) with its name.

**Tile style** is a player setting: *tall* (icon with the name under it) or *compact* (a coloured pill with the name on it). Both are the same layout and behaviour; only the styling differs.

**Selecting and highlighting.** Clicking a strip selects it for comparison. Every other strip that has no mismatch with it is highlighted in a light blue, and every identical strip in a rich, darker blue; the rest fade. A mismatch is a slot where both strips have a state and the states differ. Identical means the same state in every slot, blanks included. The strip being formulated can be selected too, and the highlights follow it as it changes.

**The top of the board.** The topmost panel is always the current task (the only panel that changes by phase). Directly under it is the labelled selection panel, showing the selected strip. Both are pinned to the top while scrolling by default, and each has a pin icon on its right to unpin it. Unpinning is remembered for each player, so an unpinned selection panel stays unpinned when a new strip is selected, and is re-pinned by scrolling up to it.

**Panels** can be minimised to their title; this is remembered too.

**Tasks.**

- *Predictions:* the task lists only the eligible theory strips, with a choice for each Probe. Which theories fit a Probe is shown by selecting the Probe.
- *Experiments:* the experiment being specified is a selectable strip. A "use" button on the selected strip copies its input states into it.
- *Citations:* while an experiment is not valid for lack of citations, its button reads "Auto-cite and run"; once the player's own citations make it valid, "Run". The methods auto-cite would choose are highlighted in light blue. Auto-cite picks only from eligible methods and prefers, in order: the player's own methods; the methods of the author with the lowest academic credit; the method published first.
- *Sensors:* "+" fills an eligible sensor slot, for installing and upgrading alike, and is transparent so what is under it stays visible. Pressing it opens the same citation choice, with auto-cite.
- *Theory formulation:* "use" on a record or on the selected strip copies its states into the theory being formulated.
- *Submission:* a submission is a box. Its top row is the theory (placed with "use"); the supporting records go below it. A box minimises to a strip showing the theory and expands back to show the records. The article processing charge is offered under the same condition as today.
- *Peer review:* the same strips that expand to boxes, in the task panel, with the vote buttons.

## 8. AI opponents (`nv_ai`)

An AI seat is a language model that reads the same text view a human could and answers each decision with a tool call naming one legal action. It never sees hidden information it isn't entitled to. The provider and model are settings (section 11): the first version uses OpenAI's GPT-6 Luna, which is cheap enough for testing; Claude models can be added through the same interface.

### 8.1 One decision

1. The engine signals that an AI seat must act (a sequential turn, or its commit in a simultaneous phase).
2. `nv_ai` builds the request:
   - **Tools** (cached): the full, fixed list of action types, one tool each, with JSON schemas generated from the action models and a short description naming the rulebook section. The list never changes between decisions, because the tools come first in a request and any change would invalidate the cache for everything after them.
   - **System prompt** (cached): the rulebook itself (`docs/rules.md` with its Markdown escapes removed, leaving out the sections a player does not need, such as Pieces and the designer's tabletop notes), then the scenario story, then the seat's persona (section 8.3). The rulebook stays the only rules document; no separate summary is maintained. The rulebook comes before the persona, so every AI seat shares the same cached prefix.
   - **Context:** the seat's `render_text` view, the actions legal now (from `legal_actions`: complete actions, or templates with their limits), the recent public event log, the seat's own notes (8.2), and the choices the engine has already accepted from it in the current step, with a reminder to commit when they are final (each decision is a fresh conversation, so without them a model repeats its choice instead of committing).
3. The model replies with a tool call and a one-line reason. The engine validates it; if it is refused, the error goes back to the model for up to `ai_retry_limit` attempts.
4. If the model still fails, goes over its token limit, or the API errors, the seat takes a safe default action (pass, or commit with no further choices), and the log records why.

In simultaneous phases, AI seats decide in parallel in the background while humans play, so they rarely hold up the table.

### 8.2 Memory

The API is stateless, so each AI seat keeps a private notes field in the game state (plans, which theories it is working towards, what it has learned from experiments). The model can update its notes as part of any decision, within a set length. The notes are hidden from other players and shown in spectator mode and the debrief. The server stores them with the game, so a resumed game keeps them. The text client and the simulator do not store games: there the notes are kept by the AI player and written to the decision log, so a game resumed from its record starts with empty notes.

### 8.3 Personas

Each AI seat can be given a persona in the lobby: **neutral** (default: play to win), **cooperative** (share knowledge, avoid sabotage) or **selfish** (sabotage rivals' Nobel candidates when it can). This lets the simulator test your target outcome rates for cooperative and selfish play with AI players.

### 8.4 Token limits and cost display

- **Per-decision limits:** `ai_max_cost_per_decision` caps what one decision may cost, reasoning included: the reply's output-token limit is set from it and the input already sent. `ai_max_input_tokens` caps the context, trimming the oldest log entries first.
- **Total budget:** every AI call is added to a local spending ledger; once `ai_total_budget` is reached, no further AI calls are made (the seat takes the safe default action, and the simulator stops).
- **Cost tracking:** token counts come from each API response's usage report and are multiplied by a price table in the settings file (per model, per million input, output and cached tokens). The table is editable, because prices change.
- **Display:** the status bar shows the running cost per AI seat and in total; the host can open a per-decision breakdown. The debrief and the simulator report the total too.
- There is no separate cost cap per game; the total budget and the simulator's `--max-cost` (section 9) cover it.

### 8.5 Table talk

AI seats cannot hear spoken conversation. They see only in-game actions: alliance proposals and acceptances, preregistrations, revealed predictions, publications. Players at the table should know this. Text chat that AI seats can read is a possible later addition.

## 9. Headless balance simulator (`nv_sim`)

The simulator plays complete games in-process, without the server, with any mix of player types, and writes CSV files for analysis in R or Python.

### 9.1 Player interface

Every automated player implements one method, `choose(view, legal_actions) -> action`. The first version ships two:

- **Random bot** (default): picks uniformly among legal actions, sampling sensibly where the option space is large (e.g. a random valid theory or record), and always commits eventually. Optional weights (e.g. how often to pass) keep games from stalling.
- **AI player:** the same `nv_ai` player used in live games, with its persona.

- **Scripted strategy bots** (9.4): rule-based players with a fixed strategy, free to run in large numbers.

The random bot and the scripted bots never withdraw a submission or revision (5.2): taking back a choice is for people who change their mind, and for a bot it could only loop.

### 9.2 Running batches

```
nv-sim run --scenario venus_expedition --players 4 \
  --seats random,random,random,ai:selfish \
  --games 1000 --seed 42 --set nobel_condition=5 --out results/run01
```

- `--world` fixes one world; without it, each game generates and screens a fresh world, so results average over worlds.
- `--sweep nobel_condition=4,5,6` runs every combination of the listed settings.
- Games run in parallel processes; each game's seed is recorded, so any single game can be replayed in the text client or in spectator mode: `nv-sim record <run folder> <game>` rebuilds it as a game record that `nv-play load` opens, and `nv-sim import <run folder> <game>` stores it in the server's database as a finished game, with a host link for its replay and debrief.
- **AI cost guard:** before a batch with AI seats starts, the simulator estimates its cost from a short pilot and asks for confirmation; `--max-cost` stops the batch when reached.

### 9.3 Output files

| File | One row per | Key columns |
| --- | --- | --- |
| `games.csv` | game | seed, settings, world id, seat types, rounds, crisis start round, ending (Nobel, Crisis Crash, credit), winners, final credit per seat, AI cost |
| `rounds.csv` | game × round | staff, money, credit per seat, papers published, predictions made and revealed |
| `theories.csv` | published theory | author, tier, true accuracy, coverage, successes, failures, highest Nobel counter, retracted |
| `predictions.csv` | prediction | theory, Probe, preregistered, revealed, success, whether the predictor had experiment knowledge of failure |
| `worlds.csv` | world | base rates, best theory accuracy by number of inputs, count of Nobel-grade theories |

In `predictions.csv`, the predictor "had experiment knowledge of failure" when one of their own experiments, that round or earlier, matched every input state of the theory and every visible reading of the Probe, and showed an outcome that contradicts the theory.

A short text summary prints at the end: the share of each ending with 95% confidence intervals, and the median game length.

### 9.4 Scripted strategy bots

Scripted bots test the designer's intuitions about strategies cheaply, over hundreds of games: does waiting pay, does a field of selfish players crash more often than a cooperative one, and how do rule changes shift that. They only play the strategies written here; discovering new ones is the AI players' job. They live in `nv_sim/strategy.py`; the tally is in `nv_core/evidence.py`, so it can later serve as a player aid.

There are two motives, **selfish** and **cooperative**, and an optional **patient** modifier, giving the seat types `selfish`, `cooperative`, `patient-selfish` and `patient-cooperative`. An **aggressive** modifier (scooping rivals' theories seen in peer review with a fast tier-0 copy, to dilute their citations and Nobel chances) is planned for later.

**What every scripted bot knows.** A bot uses only what a human player sees: its player view when it decides, and every event visible to it as the game goes on (Probe readings and world outcomes of every round, its own experiment results), whether or not it has to decide. It remembers everything it has seen (but see memory below).

**Tally and confidence.** The bot keeps a tally for every possible theory of the scenario (every combination of input and outcome states, blanks included, with at least one input and one outcome). A *case* is a Probe whose visible readings have no mismatch with the theory's inputs (so a prediction with it would have been allowed there) or one of the bot's own experiments whose inputs include the theory's inputs; the case is a *success* when the world outcomes match the theory's outcomes. The bot is **confident** in a theory when the lower bound of the 95% Wilson interval of its success rate is at least `bot_confidence_threshold` (with the default, about ten successes without a failure). It is **confident that a theory fails** when the same holds for the failure rate. A theory is **promising** when the same lower bound is at least `bot_formulate_threshold`: enough to formulate and publish it, not yet enough to preregister with it. Because cases come from visible readings, sensor noise is already included: the tally estimates the success rate that predictions with the theory will actually get. Its estimate of a success rate is (successes + 1) / (cases + 2).

**Expected value.** A prediction is worth making when its expected credit is positive: the estimated success rate times the reward for a success, plus the failure rate times the (zero or negative) credit for a failure, both from the rulebook's Scoring predictions and Failed predictions sections and the current settings.

**Memory.** Every round, each remembered Probe reading is replaced by a random state of its row with probability `bot_memory_corruption`, so older memories are noisier (intact after *a* rounds with probability (1 − rate)^*a*). At 0, memory is perfect. Records are cards and are never affected.

**Patient modifier.** While waiting, the bot hires no staff, takes Probe time when the rules give it a turn, and keeps its tally. It wakes up when it is confident in any theory, or when the Warning shot is revealed, whichever comes first, and from then on plays its motive. It also wakes after round `bot_max_wait_rounds`: without staff the Game Period Deck does not move, so a table of patient bots that never becomes confident would play forever.

**When the Crisis is near.** The Crisis card is in the last part of the Game Period Deck (Game setup), and the deck count is public, so from the Warning shot on a bot can tell when the Crisis can come in the coming round.

**Each phase**

| Phase | Selfish | Cooperative |
| --- | --- | --- |
| Hiring and task allocation | Plans the round's tasks, then hires to fill them within its money and student cap: postdocs for Development (only when it can pay them), Grants for the admin requirement of its position, Write-up for its ideas and manuscripts to revise, Data collection for its own theories worth predicting with (plus one if a rival's theory is a kill target, below), one Experimentation staff member. Spare postdocs go to these needs, then to Experimentation. Students who may leave in the Student task check are covered by extra students in Experimentation, who leave first. | The same planning, with Data collection for the theories it can confirm or refute, Peer-review staff for half the manuscripts awaiting review (at most 2), and one more Experimentation staff member while a sensor can be installed or upgraded. When the Crisis is near, Data collection for every Probe, filled first. |
| Student task check | Students leave from the least needed tasks first: Experimentation, Peer-review, Data collection, Write-up, Grants; in the Crisis, Data collection last. | The same; Data collection last when the Crisis is near. |
| Experimentation | Never installs sensors (they help everyone). Confirmatory experiments: specifies the inputs of the theory it plans to publish (citing methods for inputs beyond the free ones); keeps the records that fit and ignores the rest. With no such theory, experiments like the cooperative bot. | Installs and upgrades sensors when it can, preferring the Hot topic and the Probes with the most hidden rows. Otherwise, with a theory waiting in its lab, a confirmatory experiment for it (like the selfish bot), so the theory gets a fitting record and can reach a journal with peer review. Otherwise discriminating experiments: specifies the inputs where its most likely theories disagree most about the outcome, or, with no disagreement, the least observed combination. |
| Probe time | Readings are not dealt yet, so: the Probe where most rows of its planned theory will be blank (a record is then unlikely to mismatch). | The Probe with the most visible rows (Specialty rows and sensors). |
| Prediction and preregistration | Cites rivals' theories only as a last resort: when one is worth `bot_rival_citation_factor` times its best own prediction, or to kill it (below). Preregisters confident predictions with its own theories whose Nobel counter is still 0 (a preregistered failure would reset it). Makes hidden predictions with all its other theories on every eligible Probe, and with rivals' theories whose Nobel counter is at least `bot_kill_counter`. | Always preregisters, up to its Data collection staff, one prediction per theory. Refutes first (published theories it is confident fail, highest Nobel counter first; a preregistered failure costs `failed_prereg_pred_ac` in the Calm period), then confirms the theories it is confident in. Uses the best theory, whoever wrote it. |
| Outcome and Prediction Reveal | Reveals failures of rivals' kill targets first (resetting their Nobel counters), then its successes, best first; never its own failures (selective reporting). | Nothing to reveal: it makes no hidden predictions. |
| Development | Formulates the promising theory worth the most per Probe: its *reach* (how often its input states occur, judged from the visible readings: the product of each state's share) × its success rate (the Wilson lower bound, so thin evidence loses) × (credit for a successful prediction + its citation). Each input cuts the reach, so broad theories of one or two inputs usually win: they can be used often, which brings citations and Nobel Prize progress. | Formulates the promising theory that covers the most new ground: its success rate (as for the selfish bot) × every combination of input states it fits, weighted by how often the combination occurs and divided by 1 + the number of theories of the field (published, or in its lab and manuscripts) that fit it already. So once theories for some states exist, it turns to Probes no theory fits yet, which matters in the Crisis, when every input is visible. From the Warning shot on, with no promising theory, the best-supported theory (estimated success rate above one half) for input combinations that too few published theories cover: a theory backs only one revealed prediction a round, so each combination wants as many different theories as there are Probes. Also develops a method for the input parameter most Probes do not show, while fewer methods than the highest sensor level exist for it. Both motives choose at random among the theories scoring at least 90% of the best, so bots with the same evidence do not all formulate the same theory, and formulate no new theory while two of theirs wait unpublished (their Development postdocs would cost the money that submission fees need). |
| Submission and revisions | Revises its manuscripts in the Revise area. Submits each idea to the highest tier its records reach, with every spare record (each extra record shortens processing), mixing experiment cards across experiments where the engine has to (allowed by the rulebook's Supporting observational and experimental records). Pays the article processing charge when money is spare after keeping the postdocs' pay. | Revises its manuscripts. Submits to the tier that publishes soonest (no peer review first, then the fewest rounds in processing, higher tier on ties), with records from single experiments only. Pays the article processing charge when affordable. |
| Peer review | Accepts its own manuscripts, votes revise on everyone else's. Reviews at all (one student) only when at least half the manuscripts awaiting review are its own: a lone revise vote rarely blocks anything, since a manuscript is accepted unless most of its votes say revise. | Accepts unless its tally shows the theory failing more often than succeeding. |
| Grants | Staffs the admin requirement of its current position. | The same. |
| Alliances | Proposes to, and accepts, only the current credit leader; at the last chance to leave, leaves allies behind it in credit. | Proposes once to everyone and accepts every proposal; never leaves. |
| Crisis | Predicts only where the expected value is positive (failed predictions cost `failed_prereg_pred_ac_crisis`), so it may leave Probes without a prediction. | Follows a plan the cooperative researchers would agree on at the table, computed from public information only (published theories, Probe readings, everyone's Data collection staff, and a tally of the Probe readings): a different theory for each Probe, covering as many Probes as possible with the best-supported theories, shared out in turn order (a fresh-out-of-print theory goes to its author). |

Where the table leaves a choice open (several equally good theories, records or Probes), the bot chooses at random with its seeded generator, so games stay reproducible.

## 10. End-of-game debrief

When a game ends, every player sees a debrief that reveals the hidden world and shows how the published literature compared with the truth; this is the main teaching moment.

It is built entirely from the final game state (with its hidden bookkeeping, 5.1), the full event log and the World Table, so it can also be opened later for any finished game, and exported as a printable page plus CSV (one file per table). A game begun before the hidden bookkeeping existed is replayed from its first action with the current engine to recover it; if the replay does not give exactly the stored events, the debrief uses what was recorded and says the history is incomplete. Players can open it once the game is over (a game with a join password asks for it); spectators can open it at any time.

| Panel | What it shows | Linked to players? |
| --- | --- | --- |
| How it ended | Nobel Prize (which theory, its streak), Crisis Crash (which failures), or final credit ranking; alliances | yes |
| The real world | the World Table, the designed effects and interactions, base rates | — |
| The literature vs. the truth | every published theory: author, tier, observed success rate in the game, true accuracy, retracted or not | yes |
| Luck | successful predictions that had a low true chance of success, failures of highly accurate theories, the chance of the Nobel streak | yes |
| Sabotage | revealed predictions that failed although the predictor's own experiments showed the theory would fail there; whose theory it hit and its Nobel counter at the time | yes |
| Fabrication | number of fabricated records, how many published papers relied on them, and those papers' true accuracy | no, totals only |
| File drawer | predictions made but never revealed, and their success rate compared with revealed ones | no, totals only |
| Peer review | acceptance rate by tier; papers accepted with fabricated (mixed) experiment records | no, totals only |
| Over time | academic credit per researcher by round, and the Nobel counters of leading theories | yes |

Sabotage is inferred, not certain: the debrief labels it "failed despite contrary evidence the predictor held". Contrary evidence: one of the predictor's own experiments, run by then, whose inputs match the theory's inputs and the Probe's visible readings, showed an outcome that contradicts the theory. AI seats' notes are shown alongside, which helps explain their play.

**Luck.** The true chance of a prediction is the true accuracy of its theory: the share of the World Table rows the theory covers where its outcomes are right (as in 4.3). Lucky successes are successful predictions whose true chance is below `debrief_low_chance`; unlucky failures are failed predictions whose true chance is above 1 − `debrief_low_chance`. The chance of a Nobel Prize streak is the theory's true accuracy to the power of the number of successes in the streak.

## 11. Configuration

Game settings come from `docs/parameter_defaults.yaml`, then the scenario's `parameter_overrides`, then any changes the host makes in the lobby before the game starts. Every game stores the full settings it was played with. The settings loader:

- reads the YAML file and validates it against a schema: value types (whole-number settings must be written as integers, e.g. `4`, not `4.0`), required settings, and the shape of `grant_track` and `journal_tiers`;
- applies overrides by replacing whole top-level settings (an override of `grant_track` or `journal_tiers` replaces the entire table);
- stops with an error naming any setting that is missing, unknown (e.g. a misspelled override) or has the wrong type.

The software's own settings live in `settings/software.yaml`:

| Setting | Default |
| --- | --- |
| `ai_provider` | `openai` (Anthropic later) |
| `ai_default_model` | `gpt-6-luna`, chosen per seat in the lobby |
| `ai_reasoning_effort` | the model's default (`medium` for GPT-6 Luna) |
| `ai_max_cost_per_decision` | 0.50 USD, reasoning included |
| `ai_total_budget` | 10.00 USD for all AI calls, across runs (testing in milestones 4 and 5) |
| `ai_max_input_tokens` | 30,000 per decision |
| `ai_retry_limit` | 2 |
| `ai_notes_max_chars` | 2,000 |
| `ai_price_table` | per model: input, cached-input, cache-write and output price per million tokens |
| `debrief_low_chance` | 0.5 (debrief, Luck panel, section 10) |
| `bot_confidence_threshold` | 0.7 (scripted bots, 9.4: lower bound of the success rate) |
| `bot_formulate_threshold` | 0.5 (scripted bots, 9.4: the same lower bound for a promising theory, to formulate) |
| `bot_rival_citation_factor` | 2 (scripted selfish bots cite a rival's theory only when it is worth this many times their best own prediction) |
| `bot_kill_counter` | 2 (scripted selfish bots reveal failures of rivals' theories with at least this Nobel counter) |
| `bot_memory_corruption` | 0 (scripted bots: chance per round that a remembered reading changes) |
| `bot_max_wait_rounds` | 20 (patient scripted bots wake up after this round at the latest) |
| `snapshot_every` | each round |
| `max_instances` (Cloud Run) | see `settings/cloud.yaml` |

The AI defaults are starting points to tune with the simulator, not tested values.

## 12. Open issues

All earlier rule questions are settled in rulebook v4; these items remain open.

- [ ] **Balance check:** whether `[nobel_condition]` consecutive successes fit within the Calm period (about 15 rounds). To be tested with the simulator.
- [ ] **Later idea, garden of forking paths** (not planned yet; probably only for a solo or cooperative game mode): an expandable page that shows every possible experiment strip (no blanks) and which of them the player has already covered, from which an uncovered one can be chosen.
- [ ] **Later:** optimise the board for phones (milestone 8 is designed for laptop screens).

## 13. Milestones and acceptance criteria

Build in this order, so the rules and numbers are mostly tuned before anyone plays in a browser; each milestone is done when its acceptance check passes.

| # | Milestone | Done when |
| --- | --- | --- |
| 1 | World generator and report | The same scenario and seed always give the same World Table; the report lists base rates and Nobel-grade theories; accuracy calculations are unit-tested against a hand-checked small world. |
| 2 | Rules engine and text client (local, all seats on one machine) | Full games can be played in the text client (by scripted players; playing a whole game by hand is too slow with typed commands, so hand play is tested with the web UI in milestone 5); replaying the action log reproduces the final state exactly. |
| 3 | Random bot and simulator | 100 random-bot games finish without errors or broken invariants (e.g. no negative staff, one Probe time per Probe, counters within range); CSV outputs are written. |
| 4 | AI player and scripted bots | An AI seat finishes complete games in the text client; invalid moves fall back safely; token use and cost are reported. Every scripted bot type (9.4) finishes 100 games without errors or broken invariants, and a comparison run reports the endings of the main seating mixes. |
| 5 | Server, persistence and web UI | A human finishes a game in the browser against scripted bots, and one against AI seats; two browsers on the same network finish a game together; a refreshed browser rejoins its seat; a paused game resumes after a server restart. |
| 6 | Spectator mode and debrief | A spectator sees the hidden World Table; the debrief appears at game end and can be reopened later; fabrication and file-drawer panels show totals only. |
| 7 | Deployment | Runs on Google Cloud Run with Firestore and Secret Manager; a game with an AI seat works end to end from outside the local network. |
| 8 | Board design (7.4) | A human finishes a game on a laptop using the strip board in every phase; selecting a strip highlights the strips with no mismatch and the identical ones; pinning, minimising and the tile style are remembered. |

**Testing throughout:**

- One or more unit tests per rule section of the rulebook, named after the section, so a rules change points to the tests to update.
- A consistency check on every commit: every `[parameter]` named in the rulebook exists in `parameter_defaults.yaml` (as a top-level setting, or as a field of the `grant_track` or `journal_tiers` tables), every top-level setting there is named in the rulebook or in section 5.7, and every scenario file passes its schema.
- Saved "golden" games whose replays must not change unless a rule changes on purpose.
- Invariant checks run after every action in tests and in the simulator.
- A test that no player view contains hidden information belonging to someone else.

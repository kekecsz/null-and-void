# Open questions

Questions about the rulebook, the parameter file, the scenario file and the specification. When Zoltan has
answered a question and the answer is in the right document, remove its entry here.

Each entry gives the document and section, the exact text, the possible readings, and a suggested answer
(only a suggestion until it is confirmed).

---

## Answered: waiting for a document update

Zoltan has answered these. Each answer still has to go into the specification (a Google Docs export).
Remove an entry once the specification says it.

- **A2. Python version.** Use the latest Python (3.14). Specification §3 still says "Python 3.12".
- **A3. Probe deck building.** `nv_core` builds the Probe deck, the Input Parameter Decks and the sensor noise; the world file holds only the World Table. Specification §1 ("cuts the Probe deck") and the §3 table (`nv_world`: "Probe deck building") still say otherwise.
- **B1. Accuracy and coverage** (specification §4.3). Coverage is the weighted share of World Table rows that match the theory's input states. Accuracy is the weighted share of those rows where every one of the theory's world outcome states matches the realised outcome.
- **B3. Thresholds** (specification §4.3). `max_…` criteria fail only above the value (≤ passes); `min_…` criteria pass at or above the value (≥).
- **B5. Interactions** (specification §4.2 step 2). The pair of input states is drawn uniformly from all pairs of states that belong to different input parameters.
- **B9. Retries** (specification §4.3). Try seed, seed+1, …, up to `max_generation_tries`. The world file records the requested seed and the accepted seed. If every try fails, the command stops and reports how often each criterion failed.

---

## B. Milestone 1: world generator

### B2. Which count of Nobel-grade theories do `min_count` / `max_count` apply to? (blocking)
- **Where:** specification §4.3, scenario `acceptance_criteria.nobel_grade`.
- **Problem:** if `{IP1=a, IP3=b} → (WO1=x, WO2=y)` is 100 % accurate, then `{IP1=a, IP3=b} → WO1=x` and `→ WO2=y` are 100 % accurate too. The report will show three counts:
  (a) every qualifying theory; (b) distinct input patterns with at least one qualifying theory; (c) "maximal" qualifying theories (not implied by another qualifying theory with the same inputs and more outcomes).
  The generator has to apply one of them while it is screening.
- **Suggestion:** (b). It counts "how many separate discoveries could win a Nobel Prize". Make the choice explicit in the scenario YAML, e.g. `nobel_grade: {count: input_patterns, …}`.

### B4. Does `max_one_input_theory_accuracy` cover theories with two world outcomes?
- **Suggestion (used unless you object):** yes, every theory with exactly one input parameter.

### B6. Which state is the reference state when `reference_state_per_outcome: true`?
- **Suggestion (used unless you object):** the first listed state. It gets neither main effects nor interactions. Venus doesn't use this.

### B7. Format of the optional state `weights`
- **Suggestion (used unless you object):** `weights: [w1, w2, …]`, a list parallel to `states` with positive numbers that are normalised to sum to 1. A row's weight is the product of its input states' weights. How weights affect the decks is left to Milestone 2. Venus doesn't use weights.

### B8. Duplicate state names
- **Suggestion (used unless you object):** checked within one input parameter or world outcome only. IP1 and WO1 legitimately share "fat blue".

---

## C. Milestone 2: rules engine (does not block Milestone 1)

### C6. Scoring order within one reveal step
- **Where:** Scoring predictions: "Predictions are scored in the order they were revealed, so Preregistered predictions are scored first."
- **Problem:** all Preregistered predictions are revealed at the same moment (when the lab shields are removed), and so are all predictions in the Prediction Reveal. Which one is scored first decides who wins the Nobel Prize if two counters could reach `[nobel_condition]` in the same step.
- **Suggestion:** within one reveal step, score in turn order (starting with the First researcher); a researcher's own predictions go from the leftmost Probe to the rightmost.

### C22. Which publications count for the grant check?
- **Where:** Clean-up phase. "Grant funding track requirements are checked" now comes *before* the publication step. Research grants: "the number of publications by the researcher this round".
- **Readings:** (a) only papers published in an earlier step of this round. Since publication is now the last step of Clean-up, that is effectively none. (b) Papers published in this Clean-up count, so publication should come before the grant check. (c) Papers published in the previous round's Clean-up count.

### C23. Rounds in processing are now effectively one shorter
- **Where:** Clean-up phase: "1 Rounds in processing token is removed from each manuscript in the accept area" comes before the publication step in the same Clean-up.
- **Problem:** a Tier 1 manuscript accepted with 1 token loses it, and is published, in the Clean-up of the round it was accepted. That is the same timing as Tier 0, which has 0 tokens. The "reduce to 1" and "reduce to 0 in a crisis" limits also give the same result.
- **Readings:** (a) intended (X rounds in processing = published after X−1 further rounds); (b) only remove tokens from manuscripts that were in the Accept area at the start of the round; (c) publish before removing tokens.

### C24. Grant staff "used": the position before or after this round's adjustment?
- **Where:** Research grants: "As many staff members are used as specified in the admin requirement of the current grant track position". In Clean-up the grant check (which may move the marker) comes just before the unused-staff penalty.
- **Suggestion:** use the position the researcher held when staff were allocated, i.e. before the adjustment.

### C25. Which Input Parameter Deck cards are "discarded"?
- **Where:** Revealing input parameters: "When an Input Parameter Deck is exhausted, reshuffle the discarded input parameter deck cards".
- **Assumption (used unless you object):** cards are tracked by origin. Input Parameter Deck cards go to that deck's discard pile when they are thrown away: unrevealed noise cards at the end of the Observation and prediction phase, Probe readings that nobody records, and records discarded from Stale or after publication. Cards held in records or manuscripts are not reshuffled.

### C7. Self-citation
- **Where:** Running experiments, Sensor installation, Scoring predictions.
- **Question:** does a researcher who cites their own method or theory collect both rewards? In a crisis, does a failed prediction on their own theory cost both `[failed_prereg_pred_ac_crisis]` and `[crisis_failed_pred_citation_penalty]`?

### C8. What does a cited method allow in an experiment?
- **Where:** Running experiments: "[experiment\_free\_input\_parameters] Input Parameter states for free, plus one for each published method they cite."
- **Readings:** (a) a cited method lets you specify **its own** input parameter; (b) it adds one more specification of any parameter.

### C9. Two predictions with the same theory by the same researcher
- **Where:** Preregistration pruning / Outcome and Prediction Reveal: "the one belonging to the researcher who is earlier in turn order stays". This doesn't settle the case where both belong to the same researcher.
- **Suggestion:** a researcher cannot have two revealed predictions on the same theory, so they must choose one.

### C10. Record stacks: can observation and experiment cards be mixed?
- **Where:** Recording experimental findings, Supporting observational and experimental records, Recording observations.
- **Questions:** (a) Is an observation record always an intact Probe column ("taken as is"), while experiment cards form a pool that can be recombined? (b) Can one record stack mix observation cards and experiment cards? Tier 5's separate `min_observations` and `min_experiments` need each stack to have a kind. (c) Must a record stack have exactly one card per input parameter and world outcome?

### C11. Requirements for method manuscripts
- **Where:** Submission (tier table), Article processing.
- **Questions:** does a method submission have to meet the tier's `min_records`? `min_elements` does not apply to a method, does it? Can a method get the extra-record, extra-element or hot-topic reductions?

### C12. Hot topic publication
- **Where:** Article processing: "the theory does not have a mismatching input parameter from the Probe that is the Hot topic this round".
- **Questions:** is the theory checked against the visible readings or the true states? Which round counts: when it is submitted, or when it enters the Accept area (e.g. after a revision)?

### C13. Peer review details
- **Where:** Publication > Peer review.
- **Questions:** (a) Can a researcher be dealt, and vote on, their own manuscript? (b) If one reviewer gets two cards for the same manuscript, do they vote twice? (c) A manuscript with fewer than `[min_reviews_for_decision]` votes stays in place. Do its votes carry over to the next round, or are they discarded? (d) Does a revision put rounds-in-processing tokens on the manuscript, the same way as for a manuscript that is accepted directly?

### C14. Theories turned sideways
- **Where:** Clean-up: "Methods and Theories that have been turned sideways are returned to the upright position."
- **Problem:** no rule turns theories sideways; only methods are turned sideways when cited. Is this a leftover, or should a theory used for a prediction be turned sideways?

### C15. Patent income
- **Where:** Funding > Patents ("each patent grants [patent_funding] money") vs. Clean-up ("Each researcher gets as much money as many patents they own").
- **Suggestion:** Clean-up should say `[patent_funding]` per patent. The two texts agree only while it is 1.

### C16. Probe time order: ties in academic credit
- **Where:** Probe time: "in order of current academic credit (the researcher with the highest academic credit chooses first)".
- **Suggestion:** break ties by turn order.

### C17. The 0-academic-credit rule
- **Where:** Academic credit rules: "a researcher can not willingly take an action that will definitely cause an academic credit penalty".
- **Questions:** at 0 AC, is firing a postdoc forbidden (`[fired_postdoc_penalty]`)? Must every staff member be used, if that is possible, to avoid `[unused_staff_penalty]`? Which other actions are blocked?

### C18. Alliances
- **Where:** Alliance; Pieces ("Alliance tokens: 4, one per possible ally").
- **Questions:** (a) Can a researcher be in several pairwise alliances, and is winning transitive (A–B and B–C, A wins → does C win)? (b) The Warning shot card is revealed at the end of the Hiring phase, but the "last chance to leave" ends "once the Hiring phase is over". So is there a step right after the reveal where players may leave?

### C19. Crisis: what counts as "a Probe where no one made a prediction"?
- **Where:** Crisis: "one unsuccessful prediction is scored for each Probe where no one made a prediction".
- **Question:** does a Probe count as predicted if its only prediction was pruned as a duplicate?

### C20. Rebuilding the Probe deck
- **Where:** Revealing input parameters: "If the Probe deck is exhausted, re-match discarded probe-stacks from the discard pile, and reshuffle."
- **Problem:** Probe time holders take the Probe cards as records, so the discard pile is incomplete.
- **Suggestion:** the software rebuilds the full deck. With 10 × 24 stacks this almost never happens anyway.

### C21. Academic credit tie-break
- **Where:** Academic credit rules: "two players are tied … the one with the most published theories wins".
- **Suggestion:** apply the same tie-break to ties of three or more; "published theories" means theories currently published at game end (retracted ones don't count).

---

## D. Document hygiene (not blocking)

- **D1.** The rulebook's "Backstory" repeats the Venus story from scenario.md, which breaks the "each fact in one document" rule. It also has the placeholder "[Each scenario has its own backstory; see its scenario file.]". The World grid section also lists the Venus parameters, though only "for example".
- **D2.** The rulebook's "Game setup" has a heading "Input Parameter Deck" over text about starting track positions.
- **D3.** "Talent development phase", "Clean-up phase", "Alliance" and "Academic credit rules" are still plain text, not headings, in the export. Tests are named after rulebook sections, so they need to be real headings before Milestone 2.
- **D4.** Naming varies: "Probe X Parameter Y Deck" / "Probe X Input Deck"; "Experimentation and equipment phase" / "… development phase"; "(see Sensor installation rules below)" refers to a section that comes above.
- **D5.** Recording experimental findings: "researchers can take the cards from the experiments, and in the Fresh records area" is missing a verb.
- **D6.** Publication > Submission: "Tier 0 journals also charge [submission_fee]", but `submission_fee` is a field of every tier. "Each journal tier also charges its [submission_fee]" would stay correct if the values change.

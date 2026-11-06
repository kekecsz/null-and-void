# Open questions

Questions about the rulebook, the parameter file, the scenario file and the specification. When Zoltan has
answered a question and the answer is in the right document, remove its entry here.

Each entry gives the document and section, the exact text, the possible readings, and a suggested answer
(only a suggestion until it is confirmed).

---

## Rules engine (Milestone 2)

### E1. Staff who leave during the Clean-up phase
- **Where:** Clean-up phase. "All students leave the lab." and "Unpaid postdocs leave." come *before* "Grant funding track requirements are checked …" and "The researcher suffers [unused_staff_penalty] … for each staff member left on the task allocation mat."
- **Problem:** read literally, students (and unpaid postdocs) have already left when the grant check counts the Grants staff, and when the unused-staff penalty counts who is left on the mat. Students allocated to Grants would then never count towards the admin requirement, and unused students would never be penalised.
- **Readings:** (a) staff who leave during Clean-up still count for this round's grant check and unused-staff penalty (leaving only means they are gone next round); (b) the literal order: they no longer count.
- **Suggestion:** (a).

### E2. Citation reward for pruned predictions: per prediction or once?
- **Where:** Preregistration pruning: "The other predictions are discarded and [citation_reward] academic credits are awarded for the researcher who published the cited theory." Same wording in Outcome and Prediction Reveal.
- **Readings:** (a) the author gets [citation_reward] for each discarded prediction; (b) once, however many were discarded.
- **Suggestion:** (a): each discarded prediction cited the theory.

### E3. Identical theories: the last tie-break
- **Where:** Preregistration pruning: the cited theory among identical published theories is chosen by "1. the researcher's own theory, 2. … lowest value on its Nobel Prize counter …, 3. the theory of the researcher with the lowest academic credit".
- **Problem:** the engine needs a rule when all three still tie (e.g. two authors with equal academic credit, or one author who published the same theory twice).
- **Suggestion:** then the theory published earliest; if published in the same round, the author earlier in turn order. Theories the predictor may not use (Fresh out of print, someone else's) are never candidates.

### E4. Is recording optional?
- **Where:** Recording experimental findings: "researchers *can* take the cards from the experiments, and place them in the Fresh records area". Recording observations: "the researcher who has Probe time for a given Probe *can* take all cards from the Probe".
- **Problem:** records only ever help, so a choice adds a decision to every round without strategy.
- **Suggestion:** recording is automatic: experiment cards always go to Fresh records, and the Probe time holder always records the Probe.

### E5. The "last chance to leave" stage
- **Where:** Alliance: "a 'last chance to leave' stage is triggered … Once this stage is over (everyone who wants leaves or passes), alliances are unbreakable."
- **Problem:** the order in which players decide is not given.
- **Suggestion:** in turn order, each player leaves one or more alliances or passes; the stage repeats until everyone passes in a row (so players can react to someone leaving).

### E6. Simultaneous submissions when the Submission Portal fills up
- **Where:** Submission: "Manuscripts are submitted parallel by every researcher" and "If every numbered position … is occupied, no further submissions to journals with peer review can be made".
- **Problem:** with simultaneous commits, two researchers can both aim for the last free positions.
- **Suggestion:** commits are applied in turn order; a submission that no longer finds a free position is refused at that point and returned to its author's hand (no fee paid, the Write-up staff member stays unused and can still revise).

### E7. Tier 0 has an article processing charge of 0 (not blocking)
- **Where:** parameter_defaults.yaml `journal_tiers[0].apc: 0`; Publication scoring: "Open Access publications score an additional [OA_publication_AC_reward]".
- **Observation:** paying an APC of 0 is free, and tier 0 papers are published in the same round anyway, so every tier 0 paper can take the Open Access bonus at no cost. If that is intended (predatory open-access journals), no change is needed.

---


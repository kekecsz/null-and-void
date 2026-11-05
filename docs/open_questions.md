# Open questions

Questions about the rulebook, the parameter file, the scenario file and the specification. When Zoltan has
answered a question and the answer is in the right document, remove its entry here.

Each entry gives the document and section, the exact text, the possible readings, and a suggested answer
(only a suggestion until it is confirmed).

---

## World generator follow-ups (not blocking)

### B13. State weights vs. the rulebook's equal decks
- **Where:** specification §4.1 ("Optional state `weights` … A World Table row's weight is the product of the weights of its input states"); rulebook Pieces ("Probe deck: [probe_deck_copies] copies of every Probe stack of the scenario"; Input Parameter Decks "with states in the same proportions as in the Probe deck (with equal proportions)").
- **Problem:** with unequal weights, screening would weight rows unequally, but the Probe deck and the Input Parameter Decks the game deals are equal. The deck-size divisibility check would also no longer guarantee proportional decks. Venus Expedition has no weights, so nothing differs today.
- **Readings:** (a) weights also set how many copies of each Probe stack the deck holds and the Input Parameter Deck proportions (so `input_parameter_deck_size` × weight must be a whole number); (b) remove weights until a scenario needs them.
- **Suggestion:** (b). It keeps the rulebook's "equal proportions" true.

### B14. Neighbouring seeds give the same world
- **Where:** specification §4.3: "regenerate with the next seed (seed + 1, seed + 2, …)".
- **Problem:** the try sequences of nearby seeds overlap. If seed 1 is rejected 16 times and accepted at seed 17, then seeds 2–17 also end at seed 17 and give the identical world. With Venus Expedition's acceptance rate (about 1 in 16 worlds), consecutive seeds usually give the same world. The simulator's "a fresh world per game" (§9.2) would then repeat worlds when game seeds are consecutive.
- **Readings:** (a) keep seed + k and advise using seeds far apart; (b) derive each try's seed from the requested seed so that sequences never overlap, e.g. try k uses seed × `max_generation_tries` + k (which gives the same guarantee of reproducibility).
- **Suggestion:** (b).

---

## Answered: waiting for the next rulebook export

Zoltan has written these answers into the Google Doc. `docs/rules.md` is still the export of
2026-11-05 00:23, which does not contain them. Once the new export is saved to `docs/rules.md`, check each
item against it and remove it.

- **C6.** Scoring predictions: within one reveal step, predictions are scored in turn order.
- **C7.** Self-citation is allowed. It gives the same reward or penalty as being cited by another researcher.
- **C8.** Running experiments: a cited method lets the researcher specify its own input parameter.
- **C9.** Outcome and Prediction Reveal: a researcher with several revealed predictions on the same theory discards all but one.
- **C11 (c).** Article processing: methods get no extra-record, extra-element or hot-topic reductions.
- **C13 (d).** Revisions: a revised manuscript gets rounds-in-processing tokens in the same way.
- **C14.** Clean-up: a note that theories can be turned sideways to track which ones were cited this round.
- **C15.** Clean-up: patent income is `[patent_funding]` per patent.
- **C16.** Probe time: ties in academic credit are broken by turn order.
- **C18.** Alliance rules tightened.
- **C21.** Academic credit rules: the tie-break covers ties of any size, and only currently published theories count.
- **C22.** Clean-up: the grant check comes after the publication step.
- **C23.** Clean-up: rounds-in-processing tokens are removed after the publication step.
- **C25.** Revealing input parameters: which Input Parameter Deck cards are "discarded".
- **D2–D6.** Heading and wording fixes, including real headings for "Talent development phase", "Clean-up phase", "Alliance" and "Academic credit rules".

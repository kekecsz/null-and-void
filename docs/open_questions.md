# Open questions

Questions about the rulebook, the parameter file, the scenario file and the specification. When Zoltan has
answered a question and the answer is in the right document, remove its entry here.

Each entry gives the document and section, the exact text, the possible readings, and a suggested answer
(only a suggestion until it is confirmed).

---

## Answered: waiting for the next rulebook export

### C22. The grant check should come after the publication step
- **Where:** Clean-up phase. Zoltan answered that the grant check comes after the publication step, so this round's publications count. The 2026-11-05 23:53 export still has "Grant funding track requirements are checked and positions are adjusted." *before* "Those manuscripts in the Accept area … are revealed … and published." (The token removal was moved after publication as intended, see C23.)
- **To do:** move the grant check sentence (and probably the unused-staff penalty and "Return all staff members" that follow it) after the publication step in the Google Doc.

---

## Rulebook (not blocking)

### D7. A number written into the rulebook
- **Where:** Alliance: "A player can be involved in up to 4 pairwise alliances at a time."
- **Problem:** the ground rule is that values appear in the rulebook only as `[parameter]`. 4 is `max_players` − 1, i.e. "allied with everyone else".
- **Suggestion:** "A player can be in a pairwise alliance with any number of other players", or a new `[max_alliances_per_player]` in the parameter file.

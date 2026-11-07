# Open questions

Questions about the rulebook, the parameter file, the scenario file and the specification. When Zoltan has
answered a question and the answer is in the right document, remove its entry here.

Each entry gives the document and section, the exact text, the possible readings, and a suggested answer
(only a suggestion until it is confirmed).

---

## Spare supporting records for journals without peer review

**Document:** rulebook, Publication > Supporting observational and experimental records.

**Text:** "Submissions can include supporting records that are not necessary for the journal tier (this may be
useful to make a submission stack look like it is going for a high tier journal)."

**Problem:** extra records have two uses: they shorten rounds in processing (Article processing), and they make a
manuscript stack look bigger to the other players. Neither helps a journal without peer review with the default
`journal_tiers`. Tier 0 already has 0 rounds in processing. The manuscript goes straight to the Accept area with
its tier indicator card face up, so a thicker stack shows nothing. The extra records are simply lost, because the
supporting records are discarded on publication.

**Possible readings:**

1. Keep the rule as written: spare records are allowed for every tier, even where they are useless.
2. Journals without peer review take no supporting records beyond the tier's minimum.
3. Like 2, but only while extra records cannot shorten processing. This matters only if a journal without peer
   review is given 2 or more rounds in processing, where extras could still cut it down to 1.

**Agreed with Zoltan (2026-11-07):** reading 2. The engine already applies it: it refuses such records and no
longer offers them. **Waiting for:** the rulebook sentence above to be updated, for example to "Submissions to a
journal with peer review can include supporting records that are not necessary for the journal tier (...);
submissions to a journal without peer review cannot." Remove this entry once the rulebook says so.

## One patent per theory

**Document:** rulebook, Observation and prediction phase > Scoring predictions (Successful predictions: Patent),
and Funding > Patents.

**Text:** "A patent linked to the cited theory is created, and is allocated to the researcher making the
prediction (not the author of the cited theory)." and "Patents are always attached to a published theory."

**Problem:** nothing limits how many patents a theory can carry, so every successful prediction adds one. In a
playtest one theory had 5 patents. Zoltan's intention is at most one patent per theory.

**Possible readings once a theory has its patent, when a later successful prediction cites it:**

1. The first patent stays with its owner, and no new patent is created.
2. The patent moves to the researcher who made the latest successful prediction.

**Related:** Pieces lists 15 patent tokens. The rules don't say what happens when they run out, and the engine
doesn't count them. With one patent per theory this matters only if more than 15 published theories carry
patents at once.

**Agreed with Zoltan (2026-11-07):** reading 2. A theory carries at most one patent, held by the researcher who
made the latest successful prediction citing it. The rulebook already gives the patent to the researcher making
the prediction. The engine applies this: the prediction scores as usual, the patent moves, and the event log
says so. A retracted theory loses its patent, as the rulebook already says. **Waiting for:** the rulebook to say
so in Scoring predictions, for example "A theory has at most one patent. If the cited theory has no patent yet, a
patent linked to it is created; otherwise its patent moves. Either way the patent is allocated to the researcher
making the prediction (not the author of the cited theory)." Remove this entry once the rulebook says so.


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


## Talent development is a no-brainer, then forgotten (design note)

**Document:** rulebook, Talent development phase, together with Hiring and task allocation phase (student cap) and
Student task check phase (leaving students).

**Text:** "If a researcher has allocated staff to Talent development, they can advance their marker on the Talent
development track by one position. The Talent development marker can be advanced at most by one position each
round."

**Problem (Zoltan, playtest 2026-11-07):** each position raises the student cap (`student_base_hire_cap` plus the
position) and lowers the chance that students leave (`student_unassigned_base_threshold` minus the position). That
is so strong that a postdoc on Talent development is worth it in every opening round. Once the track is at
`talent_track_max`, the player never thinks about it again, so the mechanism feels empty after the opening.

**Ideas to try (Zoltan's):**

1. **Decay:** the marker drops one position in a round in which nobody is allocated to Talent development, or
   after a set number of such rounds. The track then needs upkeep, like the grant admin requirement.
2. **Rising cost:** each further position needs more staff members on Talent development, for example as many as
   the position to reach. This would also change the rule that only one staff member can be allocated to Talent
   development.

**Waiting for:** Zoltan to choose and playtest a version, then update the rulebook and `parameter_defaults.yaml`.
The engine and the bots will follow the rulebook export. Nothing changes in the code until then.

## The Crisis is almost unwinnable with the defaults (balance)

**Document:** `parameter_defaults.yaml` (`crisis_condition: 5`, `crisis_length: 4`); rulebook, Crisis.

**Problem:** with 3 players there are 4 Probes, so a 4-round Crisis has 16 Probe-rounds. Each failed prediction
and each Probe without a prediction counts as unsuccessful, so surviving the Crisis allows at most 4 of 16. The
simulator (2026-11-07, scripted bots of specification 9.4, Venus Expedition, 3 players, 100 games per table,
`crisis_condition` set to 100 so the Crisis always runs its full length) gives these unsuccessful predictions per
game, cumulative:

| After Crisis round | 3 cooperative | 1 cooperative + 2 selfish | 3 selfish |
| --- | --- | --- | --- |
| 1 | 2.3 | 2.7 | 3.0 |
| 2 | 4.5 | 5.3 | 6.0 |
| 3 | 6.5 | 8.1 | 9.1 |
| 4 | 8.5 | 11.1 | 12.3 |

Early on, most of them are Probes nobody predicts on (selfish tables leave about 2.5 of 4 empty in the first
Crisis round). Failures grow every round. Share of games that would survive the Crisis:

| `crisis_condition` | 5 | 6 | 7 | 8 | 9 | 10 |
| --- | --- | --- | --- | --- | --- | --- |
| 4 rounds: 3 cooperative / mixed / 3 selfish | 4% / 1% / 0% | 12% / 1% / 0% | 27% / 3% / 0% | 36% / 10% / 3% | 55% / 22% / 9% | 64% / 33% / 22% |
| 3 rounds: 3 cooperative / mixed / 3 selfish | 21% / 2% / 1% | 38% / 11% / 3% | 52% / 26% / 10% | 69% / 46% / 29% | 81% / 66% / 42% | 88% / 75% / 70% |

With the defaults, no table has a real chance, so cooperation cannot save the field.

**Suggestion (Zoltan):** `crisis_condition: 8`, or `crisis_length: 3`. The two can also be combined: a 3-round
Crisis with `crisis_condition` 7 to 8 gives about the same odds as a 4-round Crisis with 9.

**Caveats:** bots, not people; one scenario; 3 players only. With more players there are more Probes, so the best
value probably depends on the player count, and a condition relative to the number of Probes might hold up better.
The scripted bots do not play differently as a crash comes closer.

**Waiting for:** Zoltan's choice and a playtest, then `parameter_defaults.yaml`. A sweep with 4 and 5 players can
check how the value should scale.

## Early pullout: averting the Crisis by scaling down (design idea)

**Document:** a new rule for the rulebook (after the Warning shot, before the Crisis), a new `public_support`
setting in `parameter_defaults.yaml`, and probably the Victory section.

**Idea (Zoltan, 2026-11-07):** the field can avert the Crisis by pulling researchers out of Venus, or cutting
them to a sustainable number, before the Crisis hits. For example: if the Warning shot has been revealed, the
Crisis has not started, and the total number of staff members is below 2 × the number of players for two rounds
in a row, the game ends at the end of that Clean-up phase. Researchers with 2 or fewer staff members at the end
of Clean-up after the Warning shot get a `public_support` academic credit reward. It should be smaller than what
a full lab can expect, but not trivial.

**Why it fits:** it gives the Warning shot a second collective decision. The Crisis tests one kind of cooperation
(covering the Probes with predictions). The pullout tests another: restraint, a field that scales back before it
overheats ("fewer, better studies"). It builds on an existing mechanic: the staff count sets how many Game Period
cards are revealed, so fewer staff already slow the clock, and the pullout turns that into an ending.

**To decide before it goes into the rulebook:**

1. **One player can block it.** The threshold is the table's total, so a single lab with 2 × players staff members
   keeps the game going alone. That may be the intended dilemma (the hold-out who drags everyone into the Crisis).
   Alternatives: every lab at 2 or fewer (stricter), or most labs at 2 or fewer (softer).
2. **Who wins a pullout ending.** Presumably as a credit ending: the highest academic credit wins. Then the leader
   wants the pullout to lock in the lead, and trailing players want to block it. A theory close to the Nobel Prize
   also gives its author a reason to hold out. That tension can be good, but `public_support` decides whether the
   leader or the researchers who cut back gain more.
3. **When staff are counted.** In the Clean-up phase all students leave and the staff return, so "at the end of
   Clean-up" every lab has only its postdocs. Counting the staff allocated in that round's Hiring and task
   allocation phase is clearer. That is also the number that draws Game Period cards.
4. **The window.** Must both rounds come after the Warning shot? If the Crisis card is revealed during the two
   rounds, the pullout is presumably off. With fewer than 2 × players staff, only a few cards are drawn per round,
   so a timely pullout usually beats the clock.
5. **The size of `public_support`.** In the simulator (same runs as the Crisis balance question above), the
   scripted bots earn almost no credit in the last Calm rounds (median 0 per round). A Crisis they survive brings
   each of them 12 to 50 credit (average credit before and after the Crisis: 6 to 18 cooperative, 16 to 54 mixed,
   20 to 70 selfish). So the reward competes with an uncertain Crisis jackpot, roughly the chance of surviving
   times the Crisis gain. With the current defaults almost no table survives, so any reward would make pulling
   out the obvious choice and the Crisis would rarely happen. With a fairer Crisis (35 to 70% survival), about 5 to
   10 credit is a reasonable starting point to test.

**Simulation:** once the rule is in the rulebook, the scripted bots can play it (cooperative bots pull out;
selfish bots pull out only when they lead, or when `public_support` beats their expected Crisis gain), and the
simulator can show how often a pullout happens and whom it favours.

**Waiting for:** Zoltan's decisions on points 1 to 5, then the rulebook text and the parameter.

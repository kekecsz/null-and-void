# Open questions

Questions about the rulebook, the parameter file, the scenario file and the specification. When Zoltan has
answered a question and the answer is in the right document, remove its entry here.

Each entry gives the document and section, the exact text, the possible readings, and a suggested answer
(only a suggestion until it is confirmed).

---

## Talent development track: how many positions? (needs Zoltan's answer)

**Document:** `parameter_defaults.yaml` (`talent_track_max`, `talent_development_track`); rulebook, Talent development
phase.

**Text:** "The talent development track positions range between 0 and [talent_track_max]." and "The values for each
position are in parameter_defaults.yaml in the [talent_development_track] table."

**Problem:** `talent_track_max` is 3, but the table has entries for positions 0 to 6. The markers cannot go past 3, so
the last three rows are never used.

**Possible readings:**

1. The track now runs to position 6: `talent_track_max` should be 6. Pieces supports this: "Six-sided dice: 7 (the most
   students a researcher can have: [student_base_hire_cap] + 3)", and 3 is the bonus of the table's last row.
2. The track stays at 3, and the rows for positions 4 to 6 are not needed. The largest bonus is then the one of
   position 3, and the dice count in Pieces is one too many.

**Suggestion:** reading 1. The engine works with either; only the number in the parameter file changes.

## Talent development: one staff member, or any number? (needs Zoltan's answer)

**Document:** rulebook, Hiring and task allocation phase; Pieces; Talent development phase.

**Text:** "The number of staff members that can be allocated to the tasks is unlimited." but also "Talent development
(postdoc only, one staff member only)" and, in Pieces, "Talent development with room for one staff member".

**Problem:** the first sentence used to end with an exception for Talent development, which has been removed, while
the other two still limit it to one. The Talent development phase advances the marker "at most by one position each
round", so a second staff member would achieve nothing.

**Possible readings:**

1. One staff member only: the removal was accidental, and the sentence should get its exception back.
2. Any number may be allocated: the other two texts should change. As written, the extra staff would be wasted, unless
   the track is also meant to need more staff for higher positions.

**Until answered:** the engine keeps the limit of one.

## Easier difficulty levels, to allow true racing (design idea)

**Document:** `parameter_defaults.yaml`; specification 6.3 (the lobby's "settings preset").

**Problem (Zoltan, playtest 2026-11-09):** easier difficulty levels are needed to allow true racing. If the game is
this hard, selfish players will just drive the field into a loss all the time. The simulator agrees for scripted
bots: see the survival rates in "The Crisis is almost unwinnable with the defaults" above. Game lw3IvPaP was
Zoltan's first win; all earlier games Zoltan played or watched AI players play ended in a Crisis Crash.

**To decide:** which settings define a level (`crisis_condition` and `crisis_length` are the obvious ones; the
number of cards in the Game Period Deck sets how long the Calm period lasts), how many levels there are, what they
are called, and where the named presets are kept.

**Waiting for:** Zoltan's choice of levels. The simulator can then measure each level's survival rate for
cooperative, mixed and selfish tables.

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

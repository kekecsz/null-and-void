# Open questions

Questions about the rulebook, the parameter file, the scenario file and the specification. When Zoltan has
answered a question and the answer is in the right document, remove its entry here.

Each entry gives the document and section, the exact text, the possible readings, and a suggested answer
(only a suggestion until it is confirmed).

---

## Rule changes of 2026-11-12: open points (review before implementing)

### R3. Buying lab capacity
- **Where:** Experimentation and equipment phase: "Each round during the Experimentation and equipment phase the researcher may choose to spend money to increase their Lab capacity by 1 (and only 1 per round)".
- **Questions:** (a) Is buying a turn of its own in the sequential phase, or done alongside an action? (b) Does it need, or use up, an Experimentation staff member? Can a researcher with no Experimentation staff (who must pass) still buy? (c) The new capacity can only matter from the next Hiring phase on, since staff were allocated before; is that intended?
- **Also:** "up to a maximum of [starting_lab_capacity_advanced]+3" and the "+1", "+2", "+3" lines write numbers into the rulebook. The maximum follows from the three costs, so the text could say "up to the last capacity in the cost list", or the costs could become a table like `[talent_development_track]`.

### R4. What is one record, for the Records capacity?
- **Where:** Recording experimental findings; Recording observations; Supporting observational and experimental records; Clean-up phase.
- **Text:** "New records always enter at the first record position, and push older records one position higher." and "each card can be used only once"; experiment records "can be mixed across cards involved in several experiments".
- **Questions:** (a) Is one experiment one record (all its cards in one position), and one Probe observation one record? (b) When some cards of an experiment are used in a submission (a mixed stack), does the rest of that experiment keep its position and count toward the capacity? (c) When a record leaves (used in a submission, or archived), do the older records close the gap, moving one position lower?
- **Suggestion:** (a) yes; (b) yes, until all its cards are used; (c) yes.

### R6. Archiving
- **Where:** Development phase; Archiving records.
- **Questions:** (a) Do other players see that someone archived (as they see that someone developed something), or is it hidden behind the lab shield? (b) The archive has no limit, so over many rounds a lab can still build up a large table of experiments, the behaviour the change is meant to stop, at the price of Development staff. Intended? (c) The Development list says "Archive a record", while the section allows up to [max_archive_per_staff_member] records per staff member: "Archive records" would match.

### R8. A theory retracted during scoring
- **Where:** Scoring predictions; Failed predictions; Retraction.
- **Text:** "Increases the retraction counter of the cited theory by 1." and, from Retraction, the theory is unpublished once the counter reaches `[retraction_threshold]`.
- **Problem:** without pruning, several revealed predictions can cite the same theory on different Probes. If an earlier one retracts the theory, the later ones cite a theory that is no longer published.
- **Readings:** (a) the later predictions are still scored for the researchers who made them (credit for success or failure), but nothing happens to the retracted theory or its author (no counters, citation reward or patent); (b) they are discarded unscored, and their staff members are still used; (c) they are scored in full, as if the theory were still published.
- **The engine now:** (a).

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

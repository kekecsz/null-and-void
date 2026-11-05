# Scenario: Null & Void – Venus Expedition

This file holds everything specific to the Venus Expedition scenario: its story, the input parameters and world outcomes with their states, the effect model the world generator uses to build the World Table, and the criteria a generated world must meet.

- Rules that apply to every scenario are in the **rulebook** (`docs/rules.md`).
- Numeric game settings are in **`docs/parameter_defaults.yaml`**. This scenario uses them unchanged, unless `parameter_overrides` below says otherwise.
- How the world generator turns these values into a World Table is in the **software specification** (section "World generator").

The values live only in the YAML block below. The prose explains what they mean, but does not repeat them. The world generator reads the YAML block directly, so the same file serves human readers and the code.

## Story

*Null & Void: Venus Expedition*

Amazing scientific breakthrough! Astrobiologists reveal that they have found unmistakable evidence that clouds of Venus harbor primitive life. The life is mainly microbial with a few small multi-celled organisms. Researchers from all over the world send missions to Venus to find out more about this new lifeform. Researchers live in Zeppelin-like research labs floating in temperature safe-zones in the clouds of Venus, send probes to observe the creatures, collect samples, and conduct experiments in the labs. Academic journals are hungry for any findings, and would publish almost anything coming from Venus with “fast-track review”. Possible applications are numerous, findings are implemented in medicine, chemistry, material science, and even consumer products, whenever new aspects of this new lifeform are seen as sufficiently understood. Industry is only slightly more cautious than the publishers. Everyone wants to ship new products incorporating advanced Venus biotech.

Because the race between countries, research institutions, and companies is so fierce, safety regulations are lax. Every shipment going from Venus to Earth, be it carrying biosamples or research staff, increases the risk of contamination. It is only a matter of time until Venus fauna finds a foothold on our planet. As long as research is ongoing on Venus, a crisis seems to be inevitable.

## Scenario data

```yaml
scenario:
  id: venus_expedition
  title: "Null & Void: Venus Expedition"

# Input parameters, in World Grid row order (IP1 is the top row).
input_parameters:
  - id: IP1
    name: parent microbe type
    states: [fat blue, green ameba]
  - id: IP2
    name: parent microbe surface
    states: [smooth, cratered, spiky]
  - id: IP3
    name: nutrient
    states: [sugar, sulfur]
  - id: IP4
    name: weather
    states: [scorching hot, acid rain]

world_outcomes:
  - id: WO1
    name: child microbe type
    states: [fat blue, green ameba]
  - id: WO2
    name: child microbe surface
    states: [smooth, cratered, spiky]

effect_model:
  # Effect sizes on the log-odds scale (odds ratios of about 1.65, 3.3 and 6.7).
  effect_sizes_logit:
    small: 0.5
    medium: 1.2
    large: 1.9
  # The nonzero main effects available to each world outcome state;
  # all remaining input states get no main effect.
  main_effect_urn: [+large, -large, +medium, -medium, +small, -small]
  # false: every outcome state draws its own effects.
  # true: one state per world outcome is the reference and gets none.
  reference_state_per_outcome: false
  # Two-way interactions between two input states of different input parameters.
  interactions: [large, large, medium]
  interaction_sign: random          # positive or negative with equal probability
  max_interactions_per_outcome_state: 1
  # draw_once: each row's outcome is drawn once, then fixed for the whole game.
  outcome_realisation: draw_once

acceptance_criteria:
  max_base_rate: 0.60                # no world outcome state more common than this
  max_one_input_theory_accuracy: 0.85
  nobel_grade:
    min_accuracy: 0.90
    max_input_parameters: 2
    # What min_count and max_count count: input_patterns (input-state combinations
    # with at least one Nobel-grade theory), theories, or maximal_theories.
    count: input_patterns
    min_count: 2
    max_count: 5
  max_generation_tries: 1000

# Settings from docs/parameter_defaults.yaml that this scenario changes. Empty = none.
parameter_overrides: {}
```

## How these values are used

The world generator procedure that turns these values into a World Table, and checks it against the acceptance criteria, is in the software specification (section "World generator"). Players never see the effect model; it appears only in spectator mode and in the end-of-game debrief.

The acceptance criteria are there so that:

- no world outcome state is so common that a theory guessing it blindly does well;
- no theory with a single input parameter is accurate enough to make the world too easy;
- a few theories with at most two input parameters are accurate enough to win a Nobel Prize, but not too many.

## Notes for tuning

- The criteria are starting values, not tested ones. In early simulations with these parameter sizes, the typical world had about nine perfectly accurate two-input theories. So a maximum of five Nobel-grade theories may reject most worlds. The generator reports how many tries it needed. Weaken the effects, or relax the criteria, if it rarely succeeds.
- The early simulations used positive interactions only. The original design allows positive or negative interactions, which is what `interaction_sign: random` encodes.

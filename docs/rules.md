# Null and Void

Last updated: 2026.11.22. 12:30

\[Front page goes here\]

\[Illustration: Venus (Mariner 10).jpg\]

\[A round at a glance goes here\]

# Summary

Null and Void, is a game to demonstrate the hurdles of an academic researcher in the social, behavioral, and life sciences. The core idea of the game is that there is a simulation of a world that at the beginning of the game has unknown rules to the players (the researchers), but if they understand the rules governing the world, they can predict and exploit it.

The players can form theories about the rules of the world. They can observe the world, run experiments, rely on others’ published findings, or scoop other’s ideas. Theories can be utilized to make predictions in the game world. Successful predictions lead to benefits to society and of course the researcher.

The world itself is not idle. There is a crisis brewing below the surface, and the researchers are on the clock to discover the rules of the world to be able to avert or handle that crisis.

The researchers compete with each other and can achieve individual victory as well as joint or allied victory (optional) in some cases. However, if the crisis hits and it is not contained, everyone loses. Since the crisis can only be contained by learning the rules of the world, there is some incentive to cooperate.

# Victory

The ultimate victory condition is to win the Nobel Prize. The Nobel Prize is awarded for a theory that was used to successfully predict the world state (\[nobel\_condition\] \- journal tier) times consecutively. Winning the Nobel Prize is hard, and in many games, no Nobel Prize will be awarded.

A Crisis Crash is the ultimate lose condition. If a crisis hits and there are \[crisis\_condition\] total unsuccessful predictions (false predictions or missed predictions), everyone loses regardless of their academic credit.

The researchers score academic credit for academic activities such as publishing theories in prestigious journals, using theories to make successful predictions, and other researchers citing their theories or methods when making predictions. They can also lose credit if their theory is retracted. Successful predictions during the crisis score extra points for the researcher making the prediction and the publisher of the theory being cited. At game end, if it ended without a Nobel Prize or a Crisis Crash, the researcher with the highest academic credit wins.

Researchers can form an alliance, where if either of them wins the game, the other player would also win.

# Backstory

*Null & Void: Venus Expedition*

\[Each scenario has its own backstory; see its scenario file.\]

Amazing scientific breakthrough\! Astrobiologists reveal that they have found unmistakable evidence that clouds of Venus harbor primitive life. The life is mainly microbial with a few small multi-celled organisms. Researchers from all over the world send missions to Venus to find out more about this new lifeform. Researchers live in Zeppelin-like research labs floating in temperature safe-zones in the clouds of venus, send probes to observe the creatures, collect samples, and conduct experiments in the labs. Academic journals are hungry for any findings, and would publish almost anything coming from Venus with “fast-track review”. Possible applications are numerous, findings are implemented in medicine, chemistry, material science, and even consumer products, whenever new aspects of this new lifeform are seen as sufficiently understood. Industry is only slightly more cautious than the publishers. Everyone wants to ship new products incorporating advanced Venus biotech.

Because the race between countries, research institutions, and companies is so fierce, safety regulations are lax. Every shipment going from Venus to Earth, be it carrying biosamples or research staff, increases the risk of contamination. It is only a matter of time until Venus fauna finds a foothold on our planet. As long as research is ongoing on Venus, a crisis seems to be inevitable.

\[Illustration: Mars\_rock\_microbes.jpg\]

# Basic mechanics

\[min\_players\]-\[max\_players\] players can play the game. Each of them takes the role of a Principal Investigator in charge of a research station. They will be referred to as Researchers.

The game is divided into two periods: the Calm period, when researchers try to understand and exploit the world; and the Crisis period, when researchers try to handle the crisis. The game starts in the Calm period. By default, all rules apply to both periods, unless stated otherwise.

Turn order goes counterclockwise, starting with the player with the first researcher token.

There are two gameplay modes: simplified and normal. Normal mode gives the most insight about research life. The simplified game is intended to help to learn the game in stages instead of learning it all at once, but it can be skipped entirely.

# Game setup

The Game Period Deck is prepared by completing the following steps:

- One Crisis card is shuffled into a deck of (\[calm\_cards\_per\_player\_crisis\] \* player number) “Calm period” cards and the  deck is placed face down. In the simplified game, it is shuffled into a deck of (\[calm\_cards\_per\_player\_crisis\_simplified\] \* player number) instead.  
- One Warning shot card is shuffled into a another deck of (\[calm\_cards\_per\_player\_warning\] \* player number) “Calm period” cards, and this deck is placed face down on top of the previously prepared deck. In the simplified game, it is shuffled into a deck of (\[calm\_cards\_per\_player\_warning\_simplified\] \* player number) instead.  
- (\[calm\_cards\_per\_player\_top\] \* player number) “Calm period” cards are put face down on top of the previously prepared decks. In the simplified game the size of this deck is (\[calm\_cards\_per\_player\_top\_simplified\] \* player number) instead

Normal game only: The Hot topic counter starts at the first Probe.

Normal game only: Each researcher starts on position \[talent\_development\_track\_starting\_position\] on the Talent development track.

Normal game only: Each researcher starts on position \[grant\_track\_starting\_position\] on the Grant funding track.

Each researcher starts with a lab capacity of \[starting\_lab\_capacity\] in the normal mode, and \[starting\_lab\_capacity\_simplified\] in simplified mode.

By default, the first researcher token goes to one of the players randomly determined. (Alternatively, the players can agree that it goes to the player who has most recently submitted an academic work in real life (hand-in assignment, paper, grant, thesis, etc.)).

In the normal game Each researcher starts with the funding of their Grant track starting position. In the simplified game, each player starts with \[funding\_simplified\] in funds instead.

Each researcher places their academic credit marker on \[starting\_academic\_credit\].

Both input parameters and world outcomes are kept secret until they are revealed.

# Scenario setup rules

\[See the Specs document for rules on world generation. See the scenario.md for values that should be used for the world generation.\]

# World grid

The World grid shows what the researchers can observe of the world. Each row is a Probe: a probe sent out to gather data. There are as many Probes as players \+ 1\. Each column is one input parameter or one world outcome. The scenario names them and their possible states, for example:

- input parameter 1 \- parent microbe type: possible states: fat blue, green ameba  
- input parameter 2 \- parent microbe surface: possible states: smooth, cratered, spiky  
- input parameter 3 \- nutrient: possible states: sugar, sulfur  
- input parameter 4 \- weather: possible states: scorching hot, acid rain  
- world outcome 1 \- child microbe type: possible states: fat blue, green ameba  
- world outcome 2 \- child microbe surface: possible states: smooth, cratered, spiky

Behind the grid is a world that is fixed for the whole game. It is generated from the scenario before play starts (see Scenario setup rules). In it, the input parameters decide the world outcomes: the same input states always produce the same world outcomes. The researchers' task is to find out how.

Each round, every Probe gets a Probe stack from the Probe deck. A Probe stack holds the true states of one situation in that world: a state for every input parameter, and the world outcomes these inputs produce. Which stack a Probe gets is down to the shuffle of the deck. (For example, a Probe might have been exposed to the following true world state: input parameters: green ameba with smooth surface eating sugar in scorching hot condition will eventually turn into output parameters: green ameba with cratered surface) 

However, the true states of the world cannot be seen exactly by the researchers. A Probe shows only some of its input parameters, and some of its measurements can be inaccurate. There are two types of input parameters on the Probes: Specialty input parameters, and Other input parameters. 

Every Probe has two Specialty input parameters that are always shown, and always correct: input parameter 1, and one more that differs from Probe to Probe. The first Probe's second Specialty is input parameter 2, the second Probe's is input parameter 3, and so on. After the last input parameter, it starts again at input parameter 2 (with 4 input parameters, Probe 4's second Specialty is input parameter 2). (This resembles that each Probe has very accurate equipment for two input parameters.) Other input parameters show a blank card until a sensor is installed on that slot (see Sensor installation and upgrade). A sensor shows a reading, but sensors are noisy, so a reading can be wrong (see Revealing input parameters).

World outcomes are hidden until they are revealed later in the round (see Revealing world outcomes).

# Research Staff 

There are two types of research staff: 

- Postdocs: Postdocs are highly trained and can work independently.  
- Students: Students don’t require funding, but they require training and guidance.

# Hiring and task allocation phase

Simplified game:

At the beginning of the Hiring phase, researchers can hire or fire as many postdocs as they want, but the total amount of money it would take to pay all postdocs (\[cost\_of\_postdoc\] per postdoc) cannot exceed the total amount of money the researcher has at the moment. 

In the simplified game, researchers cannot hire students. 

Each research staff member is allocated to one of the following tasks during the task allocation phase:

- Experimentation and equipment: running experiments and developing new equipment  
- Data collection: collecting data and making predictions about the world  
- Development: developing theories and methods

Normal game:

At the beginning of the Hiring phase, researchers can hire or fire as many postdocs as they want, but the total amount of money it would take to pay all postdocs (\[cost\_of\_postdoc\] per postdoc) cannot exceed the total amount of money the researcher has at the moment. 

At the beginning of the Hiring phase, researchers can also hire as many students as they want up to \[student\_base\_hire\_cap\] plus the bonus student cap value associated with the Talent development track position.

Each research staff member is allocated to one of the following tasks during the task allocation phase:

- Experimentation and equipment: running experiments and developing new equipment  
- Data collection: collecting data and making predictions about the world  
- Development (postdoc only): developing theories and methods  
- Write-up: writing up research papers  
- Peer-review: reviewing manuscripts submitted by others.  
- Talent development (postdoc only, one staff member only): training research staff and scouting talents  
- Grants: administering your grants (needed to keep your position on the Grant funding track)

(Designer’s note: Students can and do develop new theories and methods, and they can train and scout staff. Restricting their allocation to these tasks was strictly a game mechanical choice, to limit too fast engine development.)

Both game modes:

The number of staff members that can be allocated to the tasks is unlimited, except for Experimentation and equipment, where the allocation is capped at the Researcher’s lab capacity, and Talent development (normal game only), where only a single staff member can be allocated to.

Hiring and task allocation is resolved parallel across researchers in secret.

Once all staff has been allocated by all researchers, the staff allocation mat is revealed. 

The staff allocation mat has an area for fired postdocs. For each postdoc they fired, the researcher suffers a penalty of \[fired\_postdoc\_penalty\] academic credits. Then, the fired postdocs are removed from the task allocation mat of each researcher.

At the end of the Hiring and task allocation phase, the research staff of each researcher are counted, a researcher with fewer than \[min\_cards\_burn\_each\_round\_per\_player\] counting as that many, and the sum of these numbers of cards is revealed from the top of the Game Period Deck. (If the Crisis card is revealed, see Crisis.)

## Student task check phase (normal game only)

During the Student task check phase, each researcher throws as many six sided dice as many students they allocated to any task. For each die result lower than \[student\_unassigned\_base\_threshold\] minus the student reliability value associated with the researcher’s marker position on the Talent development track, one student is unassigned from their task and leaves the lab. The researcher can choose which of their students are unassigned, as long as the total number of students they choose matches the number of die results below the threshold.

(Designer’s note: This phase resembles the high fluctuation among student workers, and the uncertainties related to relying on a student workforce.)

## Task resolution

In general, whenever a task is resolved by a staff member, it is removed from the task allocation mat. Unless it is explicitly specified otherwise, it is possible to not use a staff member to resolve the action they were allocated to. However, this indicates bad planning on the part of the researcher, and can hurt their reputation (In the normal game mode an academic credit penalty is incurred in the Clean-up phase for each staff member left on the task allocation mat).

\[Illustration: 2438\_pioneer\_venus\_map\_of\_venus.jpg\]

# Experimentation and equipment phase

For each staff member allocated to Experimentation and equipment, the researcher can choose one of the following actions:

- run one experiment in their lab  
- install or upgrade a sensor on a Probe

Experimentation and equipment phase is completed sequentially. Each researcher, in turn order, resolves their action, decides which published method(s) they want to cite (if any). Researchers can also pass when it is their turn. If they cannot run any more experiments for some reason (e.g. no more staff members), they must pass. A researcher who passed can not specify any more experiments in that round. The turns alternate until all researchers have passed.

Experimentation and equipment development actions often require citation of Methods.

Lab capacity determines how many staff members can be allocated to Experimentation and equipment. 

Normal game: 

Although space is limited on the research station, given enough funds and time, Lab capacity can be expanded. A player who has at least one staff member allocated to Experimentation and equipment may any time during this phase choose to spend money to increase their Lab capacity by 1 (and only 1 per round), up to a maximum of \[starting\_lab\_capacity\]+3. The cost increases with the lab size:

lab capacity \[starting\_lab\_capacity\]+1: \[bonus\_lab\_capacity\_1\]

lab capacity \[starting\_lab\_capacity\]+2: \[bonus\_lab\_capacity\_2\]

lab capacity \[starting\_lab\_capacity\]+3: \[bonus\_lab\_capacity\_3\]

Increasing lab capacity does not use any staff members.   

## Running experiments

Experiments mimic Probes, with the difference that the researcher has some control over the Input Parameter states. 

Experiments are conducted in secret behind the player’s lab shield. Researchers are not allowed to show their experiments to each other. They are allowed to talk about their experiments with others, but they don’t have to tell the truth.

For each experiment, the researcher can specify \[experiment\_free\_input\_parameters\] Input Parameter states for free, plus one for each published method they cite. If they cite multiple methods for the same experiment, the methods need to be specific to different Input Parameters. A method can only be cited for an experiment that specifies the method's own input parameter.

Methods with the Fresh out of print marker can only be used by their authors.

The authors of the methods cited immediately get \[experiment\_method\_citation\_AC\_reward\] academic credit each.

\[Figure: example\_experiment\_specification.png\]

The specified Input Parameter states are taken from the State Cards directly (not the Input Parameter Deck or the Probes).

The unspecified Input Parameter states are determined by randomly drawing from the Input Parameter Deck of that parameter.

The world outcome is determined and revealed to the researcher immediately after all of the Input Parameter slots are filled.

## Recording experimental findings

Following the experiments, researchers place the cards from the experiments in the Records area on the player mat. Records can later be used to form experiment record stacks that will support  manuscript submissions. 

One record slip (an experiment, or a Probe observation) takes one position. New records always enter at the first record position, and push older records one position higher. (Older records in positions beyond the Records capacity of \[records\_capacity\] will be discarded during Clean-up). When a record leaves the Records area (e.g. due to being attached to a submission as supporting evidence), the older ones (if any) move down to close the gap.

\[Figure: records\_are\_with\_example\_experiment\_slips.png\]

## Sensor installation and upgrade

Researchers can install or upgrade a sensor on a Probe to make it more versatile and reliable. A researcher can install a sensor on any Input Parameter slot of a Probe, except Specialty slots, or upgrade a sensor that is already there by one level. Each time, published Methods for that slot's Input Parameter need to be cited, equal to the new sensor level (e.g. 1 method has to be cited to install a new level 1 sensor, while 3 methods have to be cited to upgrade a level 2 sensor to level 3). Note that Sensor level can only be increased by one level at a time, but the same Sensor can be upgraded multiple times in the same round.

\[Figure: world\_grid\_exp\_with\_different\_sensor\_levels.png\]

Rewards for sensor installation or upgrade:

The Researcher’s marker is placed on the Probe time slot of the Probe they installed or upgraded the sensor on, if the slot is not occupied yet.

The author of the Method cited for the Sensor installation or upgrade immediately gets \[experiment\_method\_citation\_AC\_reward\]. Self-citation is possible, and it yields the same reward. (Methods with the Fresh out of print marker can only be cited by their authors.)

The Researcher that installed or upgraded a sensor is immediately rewarded \[sensor\_install\_and\_upgrade\_AC\_reward\] x the Sensor level reached by the action academic credits. (E.g. Upgrading a level 2 Sensor to level 3 grants \[sensor\_install\_and\_upgrade\_AC\_reward\] \* 3 academic credits).

During the Crisis period, sensor installation and upgrades are no longer allowed.

# Probe time

## Hot topic (normal game only)

Each round, one of the Probes is designated as a Hot topic, marked by the hot topic counter. This resembles the constantly shifting interest and hype in the scientific community.

## Claiming Probe time

Researchers can get privileged access to data from a Probe. This is referred to a researcher having “Probe time” on a given Probe for that round. Probe time on a Probe allows the researcher to record that observation (see predictions) and later to support their scientific theories during the publication process (see journal tiers). Probe time is claimed by putting a marker of the Researcher’s color next to the Probe on the World Grid. Only one Researcher’s marker can claim Probe time for each Probe. If the Probe time marker slot is already occupied (for example due to a Researcher installing a Sensor), it cannot be claimed by others.

Those researchers who do not have Probe time yet on any of the Probes, one-by-one in order of their current academic credit, claim Probe time on the next unoccupied Probe to the Probe with the Hot topic marker. If the Probe with the Hot topic is unoccupied, that counts as next. When reaching the last Probe, next is the first Probe. The researcher with the highest academic credit goes first, with turn order as tiebreaker. (Note that leftover probes cannot be occupied by players who got Probe time by installing or upgrading sensors, but a researcher can have Probe time on several Probes at the same time if they install or upgrade sensors on multiple Probes. It is possible that no Probes are left unoccupied before a Researcher can get Probe time. In this case they cannot claim Probe time that round.)

In the Simplified game, for determining Probe time claims, P1 counts as being the Hot topic Probe.

# Observation and prediction phase

## Revealing input parameters

At the start of the Observation and prediction phase, deal one Probe stack to each Probe. Then fill in each Probe's input parameter slots (sensors installed in this round's Experimentation phase already count):

Specialty slot: show the true state.

Slot without a sensor: show a blank card.

Slot with a sensor: make a small sensor deck. Take \[probe\_true\_input\_deck\_size\] cards showing the true state. Add Noise cards drawn from that input parameter's Input Parameter Deck; the better the sensor, the fewer:

Sensor level 1: \[probe\_fake\_input\_deck\_size\]

Sensor level 2: \[probe\_fake\_input\_deck\_size\]/2 (rounded down)

Sensor level 3: \[probe\_fake\_input\_deck\_size\]/4 (rounded down)

Shuffle the sensor deck and show its top card in the slot. (It may be a Noise card, showing a wrong state.) (If the Input Parameter Deck is depleted, refer to the Decks and discard piles in the Pieces section.)

\[Figure: world\_grid\_obs\_before\_prediction\_reveal.png\]

During the Crisis period, Probes show the true states (see probes in crisis).

## Revealing world outcomes

World outcomes remain hidden until predictions are finalized (see below).

## Probes in Crisis

During the Crisis period, all Probes have all of their input parameters revealed and all of them are the true input parameter (every input parameter slot shows its true state; no Noise cards are used). This resembles that during a Crisis, researchers get extra resources and the best equipment.

## Formulating predictions and preregistration

Formulating predictions is done in parallel across researchers and in secret, behind their lab shield. To formulate a prediction, the researcher must have at least one research staff member assigned to data collection.

Predictions mimic the structure of Probes and Theories. They specify input parameter states and world outcome states. Each prediction cites a published theory, it must be an exact copy of that theory, and it needs to be linked to a Probe. There can be no mismatching input parameter states between the prediction and the Probe. (This means that a theory including only one input parameter state can be used for prediction on a Probe that has multiple input parameters revealed. Also, a theory that includes four input parameter states can be used for prediction on a Probe that has only two input parameters revealed). The no mismatching input parameter state between theory and Probe reading is checked against the visible Probe readings (which can differ from the true world state due to sensor noise). One theory can only be cited once by the same Researcher on the same Probe within the same round. Also, no identical prediction can be made by the same Researcher on the same Probe within the same round through using another identical theory. 

\[Figure: prediction\_formulation\_task\_panel.png\]

Theories with the Fresh out of print marker can only be used by their authors.

When there are multiple identical theories matching the prediction, the cited theory is determined based on this preference order: 1\. the researcher’s own theory, 2\. the theory with the most successes still needed before reaching the Nobel Prize threshold (to prevent another researcher from getting the Nobel Prize), 3\. the theory of the researcher with the lowest academic credit (to reduce the lead of the leading player), 4\. the earlier published theory is cited.

The specified Input Parameter states of the predictions are taken from the State Cards directly (not the Input Parameter Deck or the Probes).

\[predictions\_per\_staff\] predictions can be made per research staff allocated to data collection. Multiple predictions per probe are allowed, as long as each prediction uses an eligible theory.

Once a prediction is formulated, it is turned face down (the researcher can check their own predictions at any time).

During the Calm period, Researchers can choose to make some of their predictions public before world outcomes are revealed. This is called Preregistration. At most as many predictions can be Preregistered by the researcher as many research staff they allocated to data collection. Researchers who have the research staff capacity to Preregister can secretly choose whether and which of their predictions they would like to Preregister, by turning these predictions face up (but for now still in secret behind the lab shield).

During the Crisis period all Predictions must be preregistered. Hidden predictions are no longer allowed. So during the Crisis period a researcher can make at most as many predictions as research staff they allocated to data collection.

## Outcome and Prediction Reveal

Once everyone is finished with Formulating predictions and preregistration assignment, all Researchers reveal their preregistered predictions to the others. 

After this, the world outcomes are revealed.

Next, a Prediction Reveal allocation starts. Researchers can decide to reveal any of their predictions, but only up to the number of research staff they have allocated to data collection. They choose simultaneously and in secret, by turning predictions they want to reveal face up behind their lab shields. The lab shields are removed once everyone is finished, to show the revealed predictions. (Preregistered predictions stay revealed automatically, whether they were successful or not. This means that if a researcher already has as many Preregistered predictions as the number of research staff they allocated to data collection, they can not reveal any of their secret predictions.) 

Once every researcher revealed all of the predictions they wanted, Scoring happens.

As many staff members are used during the Observation and prediction phase as many Predictions the researcher revealed, including Preregistered predictions.

## Scoring predictions

Only revealed predictions count for scoring purposes.

A prediction is considered successful when all world outcomes shown on the theory used for the prediction matches the world outcome revealed for the Probe for which that prediction was made. If a theory shows only one world outcome, it only needs to match that world outcome on the Probe, the other world outcome is disregarded. A prediction is considered failed in every other case.

Predictions are scored in two waves, first, all Preregistered predictions are scored, then, all other predictions in the next wave. In each wave, predictions are scored Probe-by-probe, starting with the Probe with the Hot Topic marker, and progressing in the same cycle the Hot Topic marker travels in (e.g. if the Hot Topic marker is on Probe 3, the Predictions are revealed for Probe 3 first, then Probe 4, then Probe 1, etc.). If multiple predictions are revealed for the same Probe, the predictions of the player who has Probe time scores them first. Turn order decides among the others. Among predictions of the same player made for the same Probe, predictions are scored in publication order of their theories. (Precise Probe scoring order matters for determining who gets the patent for the successful prediction, and which theory wins the Nobel prize, in cases when there is no competition for these, probe scoring order can be ignored). 

In the Simplified game, instead of the Hot Topic marker, the cycle of prediction reveal always starts at Probe 1\.

## Failed predictions: 

Academic credits

- If non-preregistered, \[failed\_non\_prereg\_pred\_ac\] academic credits are scored for the researcher who made the prediction;   
- If preregistered, \[failed\_prereg\_pred\_ac\] academic credits are scored for the researcher who made the prediction instead;  
- During the Crisis period, \[failed\_prereg\_pred\_ac\_crisis\] academic credits are scored for the researcher who made the prediction  
- During the Crisis period, \[crisis\_failed\_pred\_citation\_penalty\] academic credits are scored for the author of the cited theory

Patent

- no patent; 

Counters

- Sets the Nobel Prize counter of the cited theory to 0;   
- Increases the retraction counter of the cited theory by 1\. The retraction counter is only adjusted once for each theory per probe per round, so if the same theory was used for prediction in the same round on the same Probe by multiple researchers, the retraction counter is only increased once. (A theory retracted during scoring still scores the later predictions for the researchers who made them, but its author does not get academic credit for citation and counters no longer move on that theory.)

*Successful predictions:* 

Academic credits

- The base value of academic credit rewarded to the researcher who made the prediction is the number of input parameters in the theory used for the prediction.  
- For successful predictions during the crisis, the base value is increased by \[crisis\_pred\_base\_bonus\].  
- The value is multiplied by the number of world outcomes shown on the successful prediction.   
- If the prediction was preregistered, the value is doubled. (The multiplication for more outcomes and the preregistration effects can stack).  
- \[citation\_reward\] academic credits are awarded for the author of the cited theory in the Calm period  
- an additional \[crisis\_pred\_citation\_reward\_bonus\] academic credits are awarded for the author of the cited theory in the Crisis period

Patent (Normal game only)

- A patent linked to the cited theory is created if that theory did not already have a linked patent, and is allocated to the researcher who made the prediction (not the author of the cited theory).

Counters

- Increases the Nobel Prize counter of the cited theory by 1\. The Nobel Prize counter is only adjusted once for each theory per probe per round, so if the same theory was used for prediction in the same round on the same Probe by multiple researchers, the Nobel Prize counter is only increased once.    
- Set the retraction counter of the cited theory to 0\.

Self-citation is possible, and it yields the same reward (or penalty) as being cited by another researcher.

\[Figure: example\_predictions\_report\_page.png\]

## Recording observations

At the end of the Observation and prediction phase, the researcher who has Probe time for a given Probe takes all cards from the Probe, resembling that they record the observations. This observational record can be used to support a theory when it is submitted to a journal (see journal tiers). Since Probe readings are taken directly as observations, and Probe readings can be inaccurate, the observations carry these inaccuracies with them.

Records are put in the Records area on the player mat.

# Development phase

For each staff member allocated to Development, the researcher can choose one of the following actions:

- Formulate a theory  
- Develop a method  
- Archive a record

Development actions are taken in parallel by the researchers.

## Formulating a theory

Researchers can formulate theories about the world that allow them to make predictions of outcomes on the world grid.

A theory mimics the layout of Probes: they can specify the state of up to the number of input parameters specified in the scenario input parameters (at least one), and can specify the state of up to the number of  world outcomes specified in the scenario (at least one).

When formulating a theory, researchers build a stack of cards including one card for each of the input parameters and world outcomes on the World Grid. Cards for the theories are taken from the State Cards directly (not the Input Parameter Deck or the Probes). State Cards include multiple cards for each possible state of the input parameters and world outcomes, as well as blank cards for each input parameters and world outcomes, that can be used if the researcher would not like to specify the states of some of them.

Developed but yet unpublished theories are stored hidden in front of the developing researchers.

Example Theory: 

- Plain word description: When the parent microbe is a fat blue with smooth surface, the child microbe will also be a fat blue microbe.   
- Input Parameter 1: fat blue  
- Input Parameter 2: smooth  
- Input Parameter 3: IP3 blank  
- Input Parameter 4: IP4 blank  
- World outcome 1: fat blue  
- World outcome 2: WO2 blank

A researcher cannot formulate a theory that is already published.

(Theories need to be published before anyone can use them for prediction.)

\[Figure: example\_theory\_formation.png\]

## Developing methods

Researchers can develop new research methods that will allow them to run more precise experiments or to install sensors.

Methods are specific to one of the Input Parameters.

When developing a method, researchers build a stack of cards including one card for each of the input parameters and world outcomes on the World Grid, just like theories. However, each card in the deck will be the same blank card for one of the input parameters (e.g. number of input and output parameters specified in the scenario IP3 blank cards). The reason for this is to obfuscate whether a development stack is a theory or a method.  

(Methods need to be published before anyone can use them for experiments or sensor installation.)

## Archiving records

Researchers can archive their records, preserving them for the long term. At most \[max\_archive\_per\_staff\_member\] records can be archived for each staff member used for this action.

Archived records no longer have a record position, thus, they are not discarded at Clean-up, nor do they count toward Records capacity. Nevertheless, archived records count as being in the Records area for all other purposes, so they can be used for theory formation, or as supporting records during submission.

\[Figure: overflowing\_records\_area\_with\_archive\_buttons.png\]

# Publication (normal game only)

## Submission

For each staff member allocated to Write-up, the researcher can choose one of the following actions:

- Submit a manuscript  
- Revise a manuscript

Theories and Methods are published in scientific journals. Journals are ordered in tiers based on journal prestige. There are some low tier journals that will publish anything fast, and there are high tier journals that are more selective and are slower.

- Each journal tier sets the minimum number of supporting records (observations and experiments combined, plus any separate minimums for each kind), the minimum number of elements in the theory, the rounds in processing, whether there is peer review, whether methods are accepted, and the academic credit reward for the publication in each tier. The values are in parameter\_defaults.yaml in the \[journal\_tiers\] table. Each journal tier also charges its \[submission\_fee\]. 

Theories and Methods need to be submitted to one of the journal tiers, and once submitted, they are called Manuscripts. Manuscripts are submitted parallel by every researcher, turn order does not have to be respected. 

- When submitting to a journal with peer review, the submitted manuscript is put in the first open numbered position in the “awaiting peer review” area of the Submission Portal, face down, together with a journal tier indicator card and an author indicator card (both face up), slightly shifted so their value and color can be seen without having to touch the other cards in the manuscript.  
- When submitting to a journal with no peer review, place the manuscript stack directly in the Accept area of the Submission Portal instead.  
- If every numbered position in the “awaiting peer review” area is occupied, no further submissions to journals with peer review can be made until a position frees up. Submissions to journals without peer review (Tier 0\) are still allowed.

## Supporting observational and experimental records

If the journal tier requires observational or experimental support for the theory, recorded observations or experimental findings need to be included in the submission as well. The supporting records must be taken from the Records area. Each supporting record takes one card per slot from the player's pool (each card can be used only once). The supporting records must not have any mismatching elements (input parameters or world outcomes) with the theory they support. (A blank card never mismatches.) 

Submissions can include supporting records that are not necessary for the journal tier (this may be useful to make a submission stack look like it is going for a high tier journal). Note that method submissions can have any supporting record attached. These records are submitted as part of the manuscript submission, and they travel as part of the card stack of the manuscript during the peer review and article processing. Records submitted as evidence supporting a theory stay with the theory or method even after publication. Each card in these records that came from a deck (an Input Parameter Deck or the Probe deck) is replaced by the State Card of the same state from the general supply, and the deck card goes to its discard pile, so the decks keep their proportions. The records show exactly the same states as before. For open access publications, this is public information, while for non-open access, only the person who authored the publication is able to access these records. Submissions to a journal without peer review cannot include supporting records.

Note, that at no time do other researchers see the cards involved in experiments of the researcher, this means that the experiment records supporting the manuscript can be mixed across cards involved in several experiments. (Although researchers must put together valid experiments, and only those cards can be used to support a publication which were part of experiments at one point.) During this mixing process, the researcher can swap any IP or WO card on experiment records with any other card in the same parameter position (e.g. IP1 with IP1) on other experiment records.

(Designer’s note: the experimentation and data collection process is almost always hidden, allowing for questionable research practices, data falsification, and fabrication. The game is supposed to show that pressures on the field may drive an otherwise honest researcher to utilize questionable means to achieve goals. The game is also supposed to demonstrate that even if the individual researchers might get short term gains from these practices, the field, and society as a whole loses.)

\[Figure: example\_tier2\_submission\_with\_supporting\_records.png\]

## Revisions

When revising a manuscript, the researcher can place one of their manuscripts in the revise area to the “awaiting peer review” area in the first available numbered position. (During revision the researcher cannot change any element of the submission.)

When no one wants to submit or revise any more manuscripts, the Peer review commences.

## Peer review

The Peer review allocation deck should be set up in the following way: 

- \[min\_reviews\_for\_decision\] of the same number should be included for each occupied numbered position in the “awaiting peer review” area of the Submission Portal.   
- As many cards showing “0” as the total number of staff members allocated to peer review this round across all researchers should be included in the deck. 

This deck is then shuffled and dealt to the researchers, one for each of their staff members allocated to peer review. 

Researchers reveal the cards they got. If they got “0”, that means that that staff member got another irrelevant manuscript to review and they don’t get to evaluate any player manuscripts. For each card that shows a manuscript position, the researcher gets one pair of Peer review voting cards (one “accept”, one “revise”). For each manuscript they were allocated to review, they can secretly peek at the manuscript (including its supporting records), then must secretly choose one of the voting cards to evaluate the manuscript, placing the card next to the manuscript face down (discarding its voting card pair).

\[peer\_review\_random\_draws\] of the remaining Peer review allocation deck cards are revealed or if there are fewer cards remaining in the deck, all remaining cards. The manuscripts that are on the (non “0”) indicated positions get one “accept” decision each. \[Designer note: this resembles that the peer review process trundles along slowly even without the top researchers ever peer reviewing anything.\]

Once every peer review decision has been made, the face down voting cards next to the manuscripts are shuffled (if more than one) and turned face up.

All staff members allocated to peer review are used, no matter which cards the researcher got. 

(Designer notes: the hunger of the peer review system for free labor is insatiable).

A manuscript that has at least \[min\_reviews\_for\_decision\] peer review voting cards next to it is advanced to the next stage immediately (still face down). If the simple majority of the votes indicate “revise”, the manuscript moves to the Revise area of the Submission Portal. In any other case, the manuscript advances to the Accept area (place rounds in processing tokens according to the Article processing rules below).

## Article processing

X rounds in processing means how many rounds are required for the manuscript to be published. Rounds in processing can be shortened by 1 via the following means. These can stack, but rounds in processing can never be reduced below 1 via these methods: 

- one more observation/experiment than required for that journal tier (can stack multiple times)  
- one more element (input or outcome) in the theory than required for that journal tier  (can stack multiple times)  
- pay article processing charge (APC), \[apc\] amount of money into the bank. If you do so, submit your manuscript openly (face-up).  
- hot topic publication: at least one input parameter state of the theory matches a visible reading of the Probe that is the Hot topic this round, and none mismatches (blank readings neither match nor mismatch) (note that a theory including only a single input parameter, one that matches one of the input parameters of the hot topic Probe, can be considered a hot topic publication)

Crisis fast-track: a manuscript that enters the Accept area during the Crisis period gets 1 additional round of reduction, which can reduce it to 0 (but not below 0). Manuscripts already in the Accept area when the Crisis starts are not affected.

A method publication can only benefit from the APC and the Crisis fast-track time-reduction bonuses.

Rounds in processing tokens according to the journal tier and any of the above modifiers are placed next to the Manuscript when it advances to the Accept area of the Submission Portal, to indicate how many rounds the Manuscript will spend in processing before it is published. (These are gradually removed during the clean-up phase.)

\[Figure: submission\_portal\_all\_three\_areas\_containing\_submissions.png\]

## Publication

Manuscripts get published during the Clean-up phase (see Clean-up phase rules).

## Publication scoring

The researcher who published the paper scores academic credit indicated in the journal tier table. Open Access publications score an additional \[OA\_publication\_AC\_reward\] academic credits.

# Publication in the simplified game

Simplified game:

After the Development phase, theories and methods formulated during the Development phase are put directly in the Accept area of the Submission Portal with a tier 0 journal indicator, no supporting records, and 0 Rounds in processing tokens. No submission fee is paid, and publication is not scored. 

# Funding (normal game only)

Normal game:

Funding is used to pay research staff and article processing charges, and to build up lab capacity.

There are two main funding sources: research grants and patents.

Unspent funds are returned to the bank at the end of the round. (Designer’s note: this resembles that research funding usually cannot be stockpiled. Unspent funds are returned to the funder. This is also an anti-slippery slope mechanic.)

## Research grants

The position of the researcher’s marker on the Grant funding track represents how much grant money the lab receives each round, what are the funders’ expectations to maintain funding, and how much administrative burden the grants require.

Funding indicates the amount of money awarded each round to the researchers.

Admin indicates how many staff members need to be allocated to Grants to maintain the position.

Expected to maintain indicates the minimal number of publications required in the given round to maintain the position.

Expected to increase indicates the minimal number of publications required to advance to the next level of funding.

Publications are the theories and methods the researcher published in this round's Clean-up phase.

Each round in the Clean-up phase the Grant funding track requirements are checked and position is adjusted. If either of the two maintenance requirements (admin staff or expected to maintain) are not met, the researcher’s marker is moved one position down on the track. If (and only if) the maintenance requirements are met, the number of publications by the researcher this round are checked against expected to increase for their current track position. If it is met, the researcher’s marker is advanced to the next track position.

Note that through this process the marker can not move more than one position on the track. (Designer’s note: this resembles that grant funding issued by governments are slow to react to changes in the field.)

As many staff members are used as specified in the admin requirement of the current grant track position of the researcher. However, staff on Grants beyond the admin requirement do nothing and count as unused staff (see Clean-up phase).

The values for each position are in parameter\_defaults.yaml in the \[grant\_track\] table.

## Patents

Patents are awarded for successful predictions (see Predictions). Patents are always attached to a published theory, and there can only be a single patent linked to each theory.

During the Clean-up phase, each patent grants \[patent\_funding\] money to the owner of the patent.

(Designer’s note: patents represent funding from the industry, actual patent payments, and spinoff companies)

# Funding in the simplified game

In the simplified game, researchers get a flat rate of \[funding\_simplified\] each round, and grants and patents are ignored. 

# Nobel Prize

Once the Nobel Prize counter reaches (\[nobel\_condition\] \- the journal tier the theory was published in), the author of that theory immediately wins the game. (In the simplified game, the threshold for the Nobel Prize is \[nobel\_condition\_simplified\].)

The Nobel Prize is only checked for Nobel Prize during the Calm period and immediately when the Crisis ends. (So reaching the Nobel threshold during the Crisis is not enough for a Nobel Price, the theory needs to maintain its position until the Crisis ends). If multiple theories are eligible for the Nobel Prize at Crisis End, the theory that is furthest above its threshold wins. In case of a tie, the researchers share the Nobel Prize and win together.

# Retraction

Once the Retraction counter reaches \[retraction\_threshold\], the theory becomes unpublished. In the normal game the theory itself is returned to its author, all other cards attached to the theory, like patents, journal tier indicator, etc. are discarded. In the simplified game, the theory is simply discarded. Furthermore, when a theory is retracted, its author suffers a penalty of \[retraction\_ac\_penalty\] academic credits.

\[Figure: literature\_theory\_close\_to\_nobel\_another\_close\_to\_retraction.png\]

# Crisis

\[Illustration: Venus mountain.jpg\]

The Crisis period starts immediately when the Crisis card is revealed from the Game Period Deck (at the end of the Hiring phase).

When the Crisis period starts, the crisis tracker is also activated, where the number of rounds in crisis is tracked as well as the number of unsuccessful predictions. The rounds in crisis tracker starts on 1, and the number of unsuccessful predictions tracker starts on 0\. 

The Crisis period lasts for a total of \[crisis\_length\] rounds. If no other game-end condition is triggered first, the game ends at the end of the Clean-up phase of the \[crisis\_length\]th round of the Crisis period.

During the Crisis period, making successful predictions become a matter of life and death. The researchers must avert the crisis for long enough for a long term solution to be worked out. The number of unsuccessful predictions is tracked on the Crisis track. Each failed prediction counts as an unsuccessful prediction. Additionally, one unsuccessful prediction is scored for each Probe where no one made a prediction.

When the total number of unsuccessful predictions during the Crisis period reaches \[crisis\_condition\], it is called a Crisis Crash. A Crisis Crash ends the game immediately and all researchers lose collectively.

# Talent development phase (normal game only)

If a researcher has allocated staff to Talent development, they can advance their marker on the Talent development track by one position. The Talent development marker can be advanced at most by one position each round.

Staff members allocation to Talent development are always used, even if the researcher is at the maximum position on the talent development track.

The talent development track positions range between 0 and \[talent\_track\_max\].

The values for each position are in parameter\_defaults.yaml in the \[talent\_development\_track\] table.

# Clean-up phase

Each researcher pays \[cost\_of\_postdoc\] after each of their postdocs to the bank.

Normal game: Advance the Hot topic marker one space to the next Probe. (When it is at the last Probe at the beginning of the Clean-up phase, advance it to the first Probe.) 

Return the Researcher's markers from the Probe time slots.

Any Fresh out of print markers are removed.

Those manuscripts in the Accept area of the Submission Portal that have 0 Rounds in processing tokens during the publication step of the Clean-up phase are revealed (if not open already), published, and when in the normal game, scored. When published, theories and methods are moved to the Published Papers area and they each get a Fresh out of print marker (meaning that they can only be used by the researcher who published them until the marker is present).

Normal game: 1 Rounds in processing token is removed from each manuscript in the accept area of the Submission Portal.

Normal game: Grant funding track requirements are checked and positions are adjusted.

Normal game: The researcher suffers \[unused\_staff\_penalty\] academic credit penalty for each staff member left on the task allocation mat.

Normal game: Unpaid postdocs leave. For each unpaid postdoc, suffer a penalty of \[unpaid\_postdoc\_penalty\] academic credits. Additionally, if there were any unpaid postdocs in the lab this round, the researcher has to move their marker backwards by 1 position on the Talent development track.

Normal game: All students leave the lab.

Unspent money is returned to the bank.

Return all staff members to their researchers.

Each researcher gets as much money as the level of funding indicated for their current position on the Grant funding track. In the simplified game, the researchers get the flat rate instead.

Normal game: Each researcher gets \[patent\_funding\] for each patent they own.

During the Crisis period, advance the rounds in crisis track by one. When the crisis track cannot be advanced any further, the game ends.

Records in the Records area that are in positions beyond their \[records\_capacity\] are discarded.

The First researcher token moves to the next player counterclockwise.

\[Figure: example\_cleanup\_report.png\]

# Alliance (Optional, Normal game only)

Alliance is an optional rule. The players need to agree before starting the game whether they play with alliance enabled or not (if this was not discussed before the game, by default, it is not allowed). If alliance is enabled, a formal alliance can be formed at any time before the Crisis card is revealed. 

A formal alliance between two researchers means that if one of the researchers would win the game due to any game rule, the other player would also win. The formal alliance needs to be publicly announced and accepted by all players in the alliance. Alliances can be broken at any time unilaterally until the Warning shot card is revealed. At the time the Warning shot card is revealed, a “last chance to leave” stage is triggered, where players get a last chance to leave a formal alliance. This is decided secretly (behind the lab shields) in parallel by researchers by setting aside the alliance tokens that the player wants to leave. Once everyone is done, decisions are revealed at the same time for every player. Once this stage is over (everyone who wants leaves or passes), alliances are unbreakable.

A player can be in a pairwise alliance with any number of other players. Alliance victory is not transitional; it only applies to the direct allies of the primary victor.

Other cooperation is also possible between players, which could be open or secret, but are not bound by game rules. Even when cooperating or in a formal alliance, players must respect rules related to hidden game material. They cannot directly show each other experiment results, or predictions, although they can talk about them.

# Academic credit rules

If the game ends with an academic credit victory, and players are tied for the first place, the one with the most published theories in the published theories area wins. If this is also a tie, they win a tied victory.

Academic credit can never drop below 0\. When at 0 academic credit, a researcher can not willingly take an action that will definitely cause an academic credit penalty. E.g. they cannot spend money if they will not be able to pay their postdocs, and they cannot reveal a failed non-preregistered prediction. A researcher who has 0 academic credits, cannot spend money beyond which would allow them to pay for their postdocs. If they drop in funding outside of their control, where they don’t have enough money to pay for their postdocs, they must fire the un-fundable postdocs.
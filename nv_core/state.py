"""The game state (specification section 5.1).

Plain Pydantic data, serialisable to JSON. The rules that change it are in ``nv_core.engine``;
the rulebook section each field belongs to is named in the comments.
"""

import copy
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nv_core.settings import Settings
from nv_core.world_data import WorldData


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Task(StrEnum):
    """The tasks of the staff allocation mat (Hiring and task allocation phase)."""

    DEVELOPMENT = "development"
    DATA_COLLECTION = "data_collection"
    EXPERIMENTATION = "experimentation"
    WRITE_UP = "write_up"
    PEER_REVIEW = "peer_review"
    TALENT_DEVELOPMENT = "talent_development"
    GRANTS = "grants"


class Phase(StrEnum):
    """Where the game waits for input. Automatic steps never stop, so they have no value here."""

    HIRING = "Hiring and task allocation phase"
    LAST_CHANCE = "Alliance: last chance to leave"
    STUDENT_CHECK = "Student task check phase"
    EXPERIMENTATION = "Experimentation and equipment phase"
    PROBE_TIME = "Probe time"
    PREDICTION = "Formulating predictions and preregistration"
    REVEAL = "Outcome and Prediction Reveal"
    SCORING_ORDER = "Scoring predictions: order"
    DEVELOPMENT = "Development phase"
    SUBMISSION = "Publication: submission and revisions"
    PEER_REVIEW = "Publication: peer review"
    GAME_OVER = "Game over"


class Card(_Model):
    """A physical card, tracked by origin so it returns to the right pile (Revealing input parameters).

    ``state`` None is a blank card; ``origin`` is "supply" (State Cards), "input_deck" or "probe"
    (``stack`` = the Probe stack's id).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    var: str
    state: str | None
    origin: Literal["supply", "input_deck", "probe"]
    stack: int | None = None

    def __deepcopy__(self, memo=None) -> "Card":
        return self  # frozen, so copies of the game state can share it (much faster)


class StaffCount(_Model):
    postdocs: int = 0
    students: int = 0

    @property
    def total(self) -> int:
        return self.postdocs + self.students


class Idea(_Model):
    """A development stack: an unpublished theory or method (Development phase)."""

    id: int
    kind: Literal["theory", "method"]
    inputs: dict[str, str] = {}
    outcomes: dict[str, str] = {}
    parameter: str | None = None  # methods only: the input parameter the method is specific to


class Observation(_Model):
    """An observation record: a full, intact Probe column (Recording observations)."""

    id: int
    probe: int
    round: int
    cards: list[Card]


class ExperimentCard(_Model):
    """One card of an experiment in a record area; ``experiment`` is the experiment's id."""

    experiment: int
    card: Card


class RecordArea(_Model):
    observations: list[Observation] = []
    cards: list[ExperimentCard] = []


class Experiment(_Model):
    """Hidden bookkeeping of an experiment the researcher ran (for the debrief)."""

    id: int
    round: int
    specified: dict[str, str]
    inputs: dict[str, str]
    outcomes: dict[str, str]
    cited: list[int]


class Researcher(_Model):
    seat: int
    name: str
    credit: int
    money: int
    grant_position: int  # 1 = the first entry of grant_track
    talent_position: int
    postdocs: int = 0
    students: int = 0
    # This round's staff allocation mat, and how many staff of each task have been used.
    staff: dict[Task, StaffCount] = {}
    used: dict[Task, int] = {}
    fired: int = 0
    leaving_students: int = 0  # Student task check: how many must leave
    unpaid: int = 0
    publications_this_round: int = 0
    ideas: list[Idea] = []
    fresh: RecordArea = Field(default_factory=RecordArea)
    stale: RecordArea = Field(default_factory=RecordArea)
    experiments: list[Experiment] = []

    def allocated(self, task: Task) -> int:
        count = self.staff.get(task)
        return count.total if count else 0

    def remaining(self, task: Task) -> int:
        return self.allocated(task) - self.used.get(task, 0)


class Paper(_Model):
    """A published theory or method (Published Papers area)."""

    id: int
    idea: Idea
    author: int
    tier: int
    open_access: bool
    round: int
    nobel: int = 0
    retraction: int = 0
    fresh: bool = True  # Fresh out of print marker
    sideways: bool = False  # cited this round
    patents: list[int] = []  # one entry per patent: the seat that owns it

    @property
    def kind(self) -> str:
        return self.idea.kind


class SupportRecord(_Model):
    """A supporting record stack in a manuscript (Supporting observational and experimental records)."""

    kind: Literal["observation", "experiment"]
    area: Literal["fresh", "stale"]
    cards: list[Card]
    observation: int | None = None
    experiments: list[int] = []  # the experiments the cards came from
    fabricated: bool = False  # hidden: the cards do not come from one experiment (specification 5.5)


class Manuscript(_Model):
    idea: Idea
    author: int
    tier: int
    open_access: bool
    records: list[SupportRecord]
    round_submitted: int
    area: Literal["review", "revise", "accept"]
    position: int | None = None  # Awaiting peer review position
    votes: list[Literal["accept", "revise"]] = []
    tokens: int | None = None  # Rounds in processing tokens (Accept area)

    @property
    def id(self) -> int:
        return self.idea.id


class Probe(_Model):
    """A Probe column of the World Grid."""

    index: int
    specialty: list[str]
    sensors: dict[str, int] = {}
    stack: int | None = None
    readings: dict[str, Card] = {}
    outcomes: dict[str, Card] = {}
    outcomes_revealed: bool = False
    unrevealed_noise: dict[str, list[str]] = {}
    probe_time: int | None = None
    probe_time_from_sensor: bool = False


class Prediction(_Model):
    id: int
    round: int = 0
    seat: int
    probe: int
    theory: int  # the published theory the researcher copied
    inputs: dict[str, str]
    outcomes: dict[str, str]
    preregistered: bool = False
    revealed: bool = False
    reveal_step: int | None = None  # 1 = Preregistration pruning, 2 = Prediction Reveal
    cited: int | None = None  # the theory cited after the identical-theory preference
    status: Literal["hidden", "revealed", "pruned", "scored", "discarded"] = "hidden"
    success: bool | None = None  # set for every prediction once outcomes are revealed


class GameResult(_Model):
    ending: Literal["nobel", "crisis_crash", "credit", "ended_early"]
    winners: list[int]  # including allies
    primary: list[int]  # the researchers who won by a game rule (before alliances)
    theory: int | None = None  # the Nobel Prize theory


class Pending(_Model):
    """Choices made in a simultaneous step, editable until the researcher commits."""

    allocation: dict | None = None
    leaving_students: dict[Task, int] | None = None
    leave_alliances: list[int] = []
    development: list[Idea] = []
    votes: dict[int, Literal["accept", "revise"]] = {}
    scoring_order: list[int] | None = None


class GameState(_Model):
    # Setup
    world: WorldData
    settings: Settings
    seed: int
    players: list[str]
    rng: dict[str, int] = {}
    next_id: int = 1
    # Clock
    round: int = 1
    period: Literal["calm", "crisis"] = "calm"
    phase: Phase = Phase.HIRING
    period_deck: str = ""  # top card first: "c" Calm period, "w" Warning shot, "x" Crisis
    warning_revealed: bool = False
    last_chance_done: bool = False  # after this, alliances are unbreakable
    crisis_revealed: bool = False
    rounds_in_crisis: int = 0
    unsuccessful_predictions: int = 0
    first_player: int = 0
    # Who the game waits for
    waiting: list[int] = []  # simultaneous steps: seats that have not committed
    current: int | None = None  # sequential steps: the seat to act
    passed: list[int] = []
    queue: list[int] = []  # Probe time: seats still to choose, in order
    # World Grid
    probes: list[Probe] = []
    hot_topic: int = 0
    probe_deck: list[int] = []  # stack ids, top first
    stack_rows: list[int] = []  # stack id -> World Table row
    probe_discard: list[Card] = []
    input_decks: dict[str, list[str]] = {}
    input_discards: dict[str, list[str]] = {}
    # Researchers
    researchers: list[Researcher] = []
    pending: list[Pending] = []
    predictions: list[Prediction] = []
    # Publication
    published: list[Paper] = []
    manuscripts: list[Manuscript] = []
    review_cards: dict[int, list[int]] = {}  # seat -> Peer review allocation cards (0 = irrelevant)
    review_rest: list[int] = []
    # Alliance
    alliances: list[list[int]] = []  # sorted seat pairs
    proposals: list[list[int]] = []  # [from, to]
    # Hidden bookkeeping (never in player views)
    prediction_log: list[Prediction] = []
    # End
    result: GameResult | None = None

    def clone(self) -> "GameState":
        """A deep copy that shares the (frozen) world and settings."""
        memo = {id(self.world): self.world, id(self.settings): self.settings}
        return copy.deepcopy(self, memo)

    @property
    def n_players(self) -> int:
        return len(self.players)

    def turn_order(self) -> list[int]:
        """Seats in turn order, starting with the First researcher token (Basic mechanisms)."""
        n = self.n_players
        return [(self.first_player + i) % n for i in range(n)]

    def researcher(self, seat: int) -> Researcher:
        return self.researchers[seat]

    def paper(self, paper_id: int) -> Paper:
        for paper in self.published:
            if paper.id == paper_id:
                return paper
        raise KeyError(paper_id)

    def manuscript(self, manuscript_id: int) -> Manuscript:
        for manuscript in self.manuscripts:
            if manuscript.id == manuscript_id:
                return manuscript
        raise KeyError(manuscript_id)

    def new_id(self) -> int:
        value = self.next_id
        self.next_id += 1
        return value

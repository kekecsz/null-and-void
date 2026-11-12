"""Player actions (specification section 5.3): one discriminated union of typed models.

Every action names the seat that takes it. Whether it is legal now is decided by the engine
(``nv_core.engine.validate``), which gives a reason when it refuses.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from nv_core.state import StaffCount, Task


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seat: int


# Hiring and task allocation phase
class AllocateStaff(_Action):
    type: Literal["allocate_staff"] = "allocate_staff"
    hire_postdocs: int = 0
    fire_postdocs: int = 0
    hire_students: int = 0
    allocation: dict[Task, StaffCount] = {}


# Student task check phase
class ChooseLeavingStudents(_Action):
    type: Literal["choose_leaving_students"] = "choose_leaving_students"
    by_task: dict[Task, int]


# Experimentation and equipment phase
class RunExperiment(_Action):
    type: Literal["run_experiment"] = "run_experiment"
    specified: dict[str, str] = {}  # input parameter -> state
    cited_methods: list[int] = []


class InstallSensor(_Action):
    """Install a sensor, or upgrade the sensor already there by one level."""

    type: Literal["install_sensor"] = "install_sensor"
    probe: int  # 0-based column index
    parameter: str
    cited_methods: list[int]


class Pass(_Action):
    type: Literal["pass"] = "pass"


class ExpandLab(_Action):
    """Increase the lab capacity by 1, any time during the phase (not only on the researcher's turn)."""

    type: Literal["expand_lab"] = "expand_lab"


# Probe time
class ClaimProbeTime(_Action):
    type: Literal["claim_probe_time"] = "claim_probe_time"
    probe: int


# Observation and prediction phase
class MakePrediction(_Action):
    type: Literal["make_prediction"] = "make_prediction"
    theory: int  # a published theory to copy
    probe: int
    preregister: bool = False


class CancelPrediction(_Action):
    type: Literal["cancel_prediction"] = "cancel_prediction"
    prediction: int


class SetPreregistered(_Action):
    type: Literal["set_preregistered"] = "set_preregistered"
    prediction: int
    preregister: bool = True


class RevealPrediction(_Action):
    type: Literal["reveal_prediction"] = "reveal_prediction"
    prediction: int
    reveal: bool = True


class OrderPredictions(_Action):
    """The scoring order of several predictions on the same Probe (Scoring predictions)."""

    type: Literal["order_predictions"] = "order_predictions"
    order: list[int]


# Development phase
class FormulateTheory(_Action):
    type: Literal["formulate_theory"] = "formulate_theory"
    inputs: dict[str, str]
    outcomes: dict[str, str]


class DevelopMethod(_Action):
    type: Literal["develop_method"] = "develop_method"
    parameter: str


class CancelDevelopment(_Action):
    type: Literal["cancel_development"] = "cancel_development"
    index: int  # position in this round's list of development choices


# Publication
class ObservationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["observation"] = "observation"
    observation: int


class ExperimentRecord(BaseModel):
    """One card per row, each named by (experiment id, row id), all from one record area."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["experiment"] = "experiment"
    cards: list[tuple[int, str]]


RecordSpec = Annotated[Union[ObservationRecord, ExperimentRecord], Field(discriminator="kind")]


class Submit(_Action):
    type: Literal["submit"] = "submit"
    manuscript: int  # the idea (development stack) id
    tier: int
    records: list[RecordSpec] = []
    pay_apc: bool = False


class Revise(_Action):
    type: Literal["revise"] = "revise"
    manuscript: int


class WithdrawSubmission(_Action):
    """Take back a submission or revision made in this step, before committing (specification 5.2)."""

    type: Literal["withdraw_submission"] = "withdraw_submission"
    manuscript: int


class ReviewVote(_Action):
    type: Literal["review_vote"] = "review_vote"
    card: int  # index into the researcher's Peer review allocation cards
    vote: Literal["accept", "revise"]


# Alliance
class ProposeAlliance(_Action):
    type: Literal["propose_alliance"] = "propose_alliance"
    partner: int


class AcceptAlliance(_Action):
    type: Literal["accept_alliance"] = "accept_alliance"
    partner: int


class LeaveAlliance(_Action):
    type: Literal["leave_alliance"] = "leave_alliance"
    partner: int


class StayInAlliance(_Action):
    """Withdraw a leave choice in the "last chance to leave" stage."""

    type: Literal["stay_in_alliance"] = "stay_in_alliance"
    partner: int


# Simultaneous steps
class CommitPhase(_Action):
    type: Literal["commit"] = "commit"


Action = Annotated[
    Union[
        AllocateStaff,
        ChooseLeavingStudents,
        RunExperiment,
        InstallSensor,
        Pass,
        ExpandLab,
        ClaimProbeTime,
        MakePrediction,
        CancelPrediction,
        SetPreregistered,
        RevealPrediction,
        OrderPredictions,
        FormulateTheory,
        DevelopMethod,
        CancelDevelopment,
        Submit,
        Revise,
        WithdrawSubmission,
        ReviewVote,
        ProposeAlliance,
        AcceptAlliance,
        LeaveAlliance,
        StayInAlliance,
        CommitPhase,
    ],
    Field(discriminator="type"),
]

ACTION_ADAPTER: TypeAdapter = TypeAdapter(Action)
ACTION_LIST_ADAPTER: TypeAdapter = TypeAdapter(list[Action])


def action_from_json(data: dict) -> BaseModel:
    return ACTION_ADAPTER.validate_python(data)

"""The text client's command language (specification section 7.1).

Each command is parsed into the same action model the engine validates. Spaces inside state
names are written as underscores (fat_blue); names are case-insensitive and may be shortened
to any unique prefix.
"""

import re

from pydantic import BaseModel

from nv_core import actions as a
from nv_core.state import GameState, StaffCount, Task


class CommandError(ValueError):
    """The command could not be understood; the message says how to write it."""


TASK_NAMES = {
    "dev": Task.DEVELOPMENT,
    "data": Task.DATA_COLLECTION,
    "exp": Task.EXPERIMENTATION,
    "write": Task.WRITE_UP,
    "review": Task.PEER_REVIEW,
    "talent": Task.TALENT_DEVELOPMENT,
    "grants": Task.GRANTS,
}

HELP = """Commands (ids: P2 Probe, T7 theory, M3 method, D5 development stack/manuscript,
O12 observation, E9 experiment, Q4 prediction; state names with _ for spaces, prefixes allowed):

  Hiring        allocate hire=1 fire=0 students=3 dev=1p data=1s exp=2s write=1p review=0 talent=0 grants=0
                (every staff member needs a task: Np = N postdocs, Ns = N students, e.g. 1p2s)
  Students      leave data=1 exp=1                  which students leave after the dice
  Experiments   experiment IP1=fat_blue IP3=sugar [cite M3 M5]
                sensor P2 IP3 cite M3 [M5 ...]       install, or upgrade by one level
                pass
  Probe time    probe P2
  Predictions   predict T7 P2 [prereg]   cancel Q4   prereg Q4   unprereg Q4
  Reveal        reveal Q4   hide Q4
  Score order   order Q4 Q5
  Development   theory IP1=fat_blue IP2=smooth -> WO1=fat_blue
                method IP3      undo 2   (drop your 2nd choice of this phase)
  Publication   submit D5 tier 2 [records O12 E9 E10:IP1,IP2/E11:IP3,IP4,WO1,WO2] [apc]
                (a mixed experiment record lists experiment:rows parts joined by /)
                revise D4     withdraw D5   (take back this step's submission or revision)
  Peer review   vote 1 accept      (your 1st peer review card)
  Alliances     ally NAME   accept-ally NAME   leave-ally NAME   (any time the rules allow)
                stay-ally NAME   (withdraw a leave choice in the last chance to leave stage)
  Any step      commit (or done)  when your choices for this step are final
Client: view | log [N] | as NAME | help | quit"""


def _id(token: str, prefix: str) -> int:
    match = re.fullmatch(rf"{prefix}(\d+)", token, re.IGNORECASE)
    if not match:
        raise CommandError(f"expected an id like {prefix}3, got {token!r}")
    return int(match.group(1))


def _probe(token: str) -> int:
    return _id(token, "P") - 1


def _var(state: GameState, token: str, kind: str | None = None) -> str:
    ids = {
        None: [v.id for v in state.world.variables],
        "input": state.world.input_ids,
        "outcome": state.world.outcome_ids,
    }[kind]
    for var in ids:
        if var.lower() == token.lower():
            return var
    raise CommandError(f"{token!r} is not one of {', '.join(ids)}")


def resolve_state(state: GameState, var: str, token: str) -> str:
    wanted = token.replace("_", " ").lower()
    states = state.world.variable(var).states
    exact = [s for s in states if s.lower() == wanted]
    if exact:
        return exact[0]
    prefixed = [s for s in states if s.lower().startswith(wanted)]
    if len(prefixed) == 1:
        return prefixed[0]
    raise CommandError(f"{token!r} is not a state of {var} ({', '.join(s.replace(' ', '_') for s in states)})")


def _assignments(state: GameState, tokens: list[str], kind: str | None) -> dict[str, str]:
    values: dict[str, str] = {}
    for token in tokens:
        if "=" not in token:
            raise CommandError(f"expected ROW=state, got {token!r}")
        key, value = token.split("=", 1)
        var = _var(state, key, kind)
        values[var] = resolve_state(state, var, value)
    return values


def _seat(state: GameState, token: str) -> int:
    matches = [i for i, n in enumerate(state.players) if n.lower().startswith(token.lower())]
    exact = [i for i, n in enumerate(state.players) if n.lower() == token.lower()]
    if exact:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    raise CommandError(f"{token!r} is not a player ({', '.join(state.players)})")


def _staff(value: str) -> StaffCount:
    match = re.fullmatch(r"(?:(\d+)p)?(?:(\d+)s)?|(\d+)", value.lower())
    if not match or value == "":
        raise CommandError(f"expected staff like 1p, 2s or 1p2s, got {value!r}")
    if match.group(3) is not None:
        if int(match.group(3)) != 0:
            raise CommandError(f"write postdocs and students as Np / Ns, got {value!r}")
        return StaffCount()
    return StaffCount(postdocs=int(match.group(1) or 0), students=int(match.group(2) or 0))


def _record(state: GameState, token: str) -> BaseModel:
    if token.upper().startswith("O"):
        return a.ObservationRecord(observation=_id(token, "O"))
    if ":" not in token:
        experiment = _id(token, "E")
        return a.ExperimentRecord(cards=[(experiment, v.id) for v in state.world.variables])
    cards: list[tuple[int, str]] = []
    for part in token.split("/"):
        experiment_token, rows = part.split(":", 1)
        experiment = _id(experiment_token, "E")
        cards += [(experiment, _var(state, row)) for row in rows.split(",") if row]
    return a.ExperimentRecord(cards=cards)


def parse(state: GameState, seat: int, line: str) -> BaseModel:
    """Parse one command typed by ``seat`` into an action."""
    tokens = line.split()
    if not tokens:
        raise CommandError("empty command")
    verb, args = tokens[0].lower(), tokens[1:]

    if verb == "allocate":
        fields = {"hire": 0, "fire": 0, "students": 0}
        allocation: dict[Task, StaffCount] = {}
        for token in args:
            if "=" not in token:
                raise CommandError(f"expected name=value, got {token!r}")
            key, value = token.lower().split("=", 1)
            if key in fields:
                if not value.isdigit():
                    raise CommandError(f"{key} needs a number")
                fields[key] = int(value)
            elif key in TASK_NAMES:
                allocation[TASK_NAMES[key]] = _staff(value)
            else:
                raise CommandError(f"unknown name {key!r}: use hire, fire, students or {', '.join(TASK_NAMES)}")
        return a.AllocateStaff(
            seat=seat,
            hire_postdocs=fields["hire"],
            fire_postdocs=fields["fire"],
            hire_students=fields["students"],
            allocation=allocation,
        )
    if verb == "leave":
        by_task = {}
        for token in args:
            key, _, value = token.lower().partition("=")
            if key not in TASK_NAMES or not value.isdigit():
                raise CommandError("write e.g. leave data=1 exp=1")
            by_task[TASK_NAMES[key]] = int(value)
        return a.ChooseLeavingStudents(seat=seat, by_task=by_task)
    if verb in ("experiment", "sensor"):
        cited: list[int] = []
        if "cite" in [t.lower() for t in args]:
            at = [t.lower() for t in args].index("cite")
            cited = [_id(t, "M") for t in args[at + 1 :]]
            args = args[:at]
        if verb == "experiment":
            return a.RunExperiment(seat=seat, specified=_assignments(state, args, "input"), cited_methods=cited)
        if len(args) != 2:
            raise CommandError("write e.g. sensor P2 IP3 cite M3")
        return a.InstallSensor(seat=seat, probe=_probe(args[0]), parameter=_var(state, args[1], "input"), cited_methods=cited)
    if verb == "pass":
        return a.Pass(seat=seat)
    if verb == "probe" and len(args) == 1:
        return a.ClaimProbeTime(seat=seat, probe=_probe(args[0]))
    if verb == "predict" and len(args) in (2, 3):
        prereg = len(args) == 3
        if prereg and args[2].lower() not in ("prereg", "preregister", "preregistered"):
            raise CommandError("write e.g. predict T7 P2 prereg")
        return a.MakePrediction(seat=seat, theory=_id(args[0], "T"), probe=_probe(args[1]), preregister=prereg)
    if verb in ("cancel", "prereg", "unprereg", "reveal", "hide") and len(args) == 1:
        prediction = _id(args[0], "Q")
        if verb == "cancel":
            return a.CancelPrediction(seat=seat, prediction=prediction)
        if verb in ("prereg", "unprereg"):
            return a.SetPreregistered(seat=seat, prediction=prediction, preregister=verb == "prereg")
        return a.RevealPrediction(seat=seat, prediction=prediction, reveal=verb == "reveal")
    if verb == "order":
        return a.OrderPredictions(seat=seat, order=[_id(t, "Q") for t in args])
    if verb == "theory":
        if "->" not in args:
            raise CommandError("write e.g. theory IP1=fat_blue IP2=smooth -> WO1=fat_blue")
        at = args.index("->")
        return a.FormulateTheory(
            seat=seat,
            inputs=_assignments(state, args[:at], "input"),
            outcomes=_assignments(state, args[at + 1 :], "outcome"),
        )
    if verb == "method" and len(args) == 1:
        return a.DevelopMethod(seat=seat, parameter=_var(state, args[0], "input"))
    if verb == "undo" and len(args) == 1 and args[0].isdigit():
        return a.CancelDevelopment(seat=seat, index=int(args[0]) - 1)
    if verb == "submit":
        lowered = [t.lower() for t in args]
        if len(args) < 3 or lowered[1] != "tier" or not args[2].isdigit():
            raise CommandError("write e.g. submit D5 tier 2 records O12 E9 [apc]")
        pay_apc = "apc" in lowered
        rest = [t for t in args[3:] if t.lower() != "apc"]
        if rest and rest[0].lower() == "records":
            rest = rest[1:]
        return a.Submit(
            seat=seat,
            manuscript=_id(args[0], "D"),
            tier=int(args[2]),
            records=[_record(state, t) for t in rest],
            pay_apc=pay_apc,
        )
    if verb == "revise" and len(args) == 1:
        return a.Revise(seat=seat, manuscript=_id(args[0], "D"))
    if verb == "withdraw" and len(args) == 1:
        return a.WithdrawSubmission(seat=seat, manuscript=_id(args[0], "D"))
    if verb == "vote" and len(args) == 2 and args[0].isdigit():
        vote = args[1].lower()
        if vote not in ("accept", "revise"):
            raise CommandError("vote accept or revise")
        return a.ReviewVote(seat=seat, card=int(args[0]) - 1, vote=vote)
    if verb in ("ally", "accept-ally", "leave-ally", "stay-ally") and len(args) == 1:
        partner = _seat(state, args[0])
        cls = {
            "ally": a.ProposeAlliance,
            "accept-ally": a.AcceptAlliance,
            "leave-ally": a.LeaveAlliance,
            "stay-ally": a.StayInAlliance,
        }[verb]
        return cls(seat=seat, partner=partner)
    if verb in ("commit", "done"):
        return a.CommitPhase(seat=seat)
    raise CommandError(f"unknown command {line!r}; type help")

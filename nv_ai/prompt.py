"""What an AI player is sent (specification 8.1): the fixed tool list, the instructions
(rulebook, how to play through tools, scenario story, persona) and each decision's message.

Order matters for caching: tools and instructions are identical for every decision and every
seat up to the persona, which comes last.
"""

import json
import re
import typing
from typing import Any

from pydantic import BaseModel

from nv_core import actions as a
from nv_core.engine import Option
from nv_core.markdown_text import read_markdown
from nv_core.paths import RULEBOOK
from nv_core.text import render_text

# Rulebook sections a player does not need (specification 8.1): the backstory (the scenario
# story replaces it) and the pointer to the world generator.
LEFT_OUT_SECTIONS = ("Backstory", "Scenario setup rules")

# One line per action type: what it does and where the rulebook explains it.
DESCRIPTIONS: dict[str, str] = {
    "allocate_staff": "Hiring and task allocation phase: hire/fire postdocs, hire students, and give every staff "
    "member a task. Replaces your earlier choice until you commit.",
    "choose_leaving_students": "Student task check phase: choose which tasks the leaving students come from.",
    "run_experiment": "Running experiments: specify input parameter states (free ones plus one per cited method, "
    "which must specify the method's own parameter).",
    "install_sensor": "Sensor installation and upgrade: install a level 1 sensor or upgrade one by one level, "
    "citing as many methods for that parameter as the level reached.",
    "pass": "Experimentation and equipment phase: stop using experimentation staff this round.",
    "expand_lab": "Experimentation and equipment phase: pay to increase your lab capacity by 1 (once a round; "
    "does not use a staff member or end your turn).",
    "claim_probe_time": "Probe time: place your marker on a free Probe (0-based index: P1 is 0).",
    "make_prediction": "Formulating predictions and preregistration: copy a published theory onto a Probe "
    "(0-based index), optionally preregistered.",
    "cancel_prediction": "Formulating predictions and preregistration: withdraw one of your predictions.",
    "set_preregistered": "Formulating predictions and preregistration: preregister a prediction, or undo that.",
    "reveal_prediction": "Outcome and Prediction Reveal: choose a hidden prediction to reveal (reveal=false undoes).",
    "order_predictions": "Scoring predictions: the order of your predictions on one Probe.",
    "formulate_theory": "Development phase: formulate a theory (at least one input parameter and one world outcome).",
    "develop_method": "Development phase: develop a method for one input parameter.",
    "cancel_development": "Development phase: drop one of this phase's choices (0-based index).",
    "archive_records": "Archiving records: the records (experiment or observation ids) to archive this phase; "
    "replaces your earlier list ([] for none). Each started group of max_archive_per_staff_member records uses "
    "one development staff member.",
    "submit": "Submission: submit a development stack to a journal tier with supporting records "
    "(observation records by id, experiment records as [experiment id, row id] cards, one per row).",
    "revise": "Revisions: move your manuscript from the Revise area to the Accept area.",
    "withdraw_submission": "Submission: take back a submission or revision you made in this step "
    "(refunds the fee, returns the records and the staff member).",
    "review_vote": "Peer review: vote on the manuscript of one of your peer review cards (0-based card index).",
    "propose_alliance": "Alliance: propose a formal alliance to another researcher (seat number, 0-based).",
    "accept_alliance": "Alliance: accept a proposed alliance.",
    "leave_alliance": "Alliance: leave a formal alliance (in the last chance stage: choose to leave).",
    "stay_in_alliance": "Alliance: withdraw a leave choice in the last chance to leave stage.",
    "commit": "Commit: your choices for this simultaneous step are final.",
}

INTERFACE = """\
# How you play

You are one of the researchers in a game of Null & Void, played by software. The rules above are
the full rulebook. Each message shows your current view of the game (what you are allowed to see),
the recent public events, your private notes, and the actions you can take now.

- Act by calling exactly one tool per message. The engine checks every action against the rules;
  if it refuses one, you get the reason and can try again.
- Ids: P1.. Probes (tools take the 0-based index, so P1 is 0), IP1.. input parameters, WO1.. world
  outcomes, T7 published theory 7 (tools take 7), M3 published method, D5 your development stack or
  manuscript, O12 observation record, E9 experiment, Q4 prediction. Seats are numbered from 0.
- In steps where everyone decides in secret (hiring, predictions, reveals, development, submission,
  peer review), make your choices one call at a time and call `commit` when you are done.
- Every tool takes `reason`: one short sentence on why. It may also take `notes`: your private notes,
  replacing the old ones. You see them in every message, so keep plans and what you learned there
  (e.g. experiment results). Notes are cut to {notes_max} characters.
- Hidden information stays hidden: other researchers cannot see your lab, and you cannot see theirs.
"""

PERSONAS = {
    "neutral": "Play to win: a Nobel Prize, or the most academic credit when the game ends, while avoiding a "
    "Crisis Crash, in which everyone loses.",
    "cooperative": "Play to win, but cooperatively: help the field understand the world, avoid sabotage, and "
    "consider alliances. Everyone loses in a Crisis Crash.",
    "selfish": "Play to win at others' expense: when you can, sabotage rivals' Nobel Prize candidates (for example "
    "with predictions you expect to fail on their theories). Avoid a Crisis Crash, in which everyone loses.",
}


def rules_text() -> str:
    """The rulebook without the sections a player does not need."""
    lines = read_markdown(RULEBOOK).splitlines()
    kept, skipping = [], False
    for line in lines:
        heading = re.match(r"^(#+)\s+(.*)$", line)
        if heading and len(heading.group(1)) == 1:
            skipping = heading.group(2).strip() in LEFT_OUT_SECTIONS
        if not skipping:
            kept.append(line)
    return "\n".join(kept).strip()


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Replace $ref with the referenced definition (some providers do not resolve $defs)."""
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(dict(defs[node["$ref"].split("/")[-1]]))
            # "discriminator" only repeats what oneOf says, and points at the removed $defs
            return {k: walk(v) for k, v in node.items() if k not in ("title", "discriminator")}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def tool_definitions(notes_max: int) -> list[dict[str, Any]]:
    """One function tool per action type, always the same list in the same order."""
    tools = []
    union = typing.get_args(a.Action)[0]  # Action is Annotated[Union[...], discriminator]
    for cls in typing.get_args(union):
        name = cls.model_fields["type"].default
        schema = _inline_refs(cls.model_json_schema())
        properties = {k: v for k, v in schema.get("properties", {}).items() if k not in ("seat", "type")}
        required = [k for k in schema.get("required", []) if k not in ("seat", "type")]
        properties["reason"] = {"type": "string", "description": "One short sentence: why this action."}
        properties["notes"] = {
            "type": "string",
            "description": f"Optional: your new private notes (replace the old ones; at most {notes_max} characters).",
        }
        tools.append(
            {
                "type": "function",
                "name": name,
                "description": DESCRIPTIONS[name],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": [*required, "reason"],
                    "additionalProperties": False,
                },
                "strict": False,
            }
        )
    return tools


def instructions(story: str, persona: str, notes_max: int) -> str:
    """Rulebook first (shared by every seat), then the interface, the story and the persona."""
    if persona not in PERSONAS:
        raise ValueError(f"unknown persona {persona!r} (available: {', '.join(PERSONAS)})")
    return "\n\n".join(
        [
            rules_text(),
            INTERFACE.format(notes_max=notes_max),
            "# The scenario\n\n" + story,
            "# Your persona\n\n" + PERSONAS[persona],
        ]
    )


def _compact(action: BaseModel) -> str:
    data = action.model_dump(mode="json", exclude={"seat"})
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


MAX_LISTED = 40  # complete actions listed per option; the rest are counted


def options_text(options: list[Option]) -> str:
    lines = []
    for option in options:
        if option.actions:
            shown = option.actions[:MAX_LISTED]
            lines.append(f"- {option.type}:")
            lines += [f"    {_compact(x)}" for x in shown]
            if len(option.actions) > len(shown):
                lines.append(f"    ... and {len(option.actions) - len(shown)} more of the same kind")
        if option.template:
            lines.append(f"- {option.type} (build it within these limits): "
                         f"{json.dumps(option.template, ensure_ascii=False, separators=(',', ':'))}")
    return "\n".join(lines) or "(nothing)"


def decision_message(
    view: dict[str, Any], options: list[Option], events: list[str], notes: str, step_choices: list[str] = ()
) -> str:
    """``step_choices``: the actions of this seat the engine accepted earlier in the same step.
    Each decision is a fresh conversation, so without them a model cannot tell that it has
    already chosen and repeats the same choice instead of committing."""
    seat = view["seat"]
    parts = [
        f"You are seat {seat}, {view['players'][seat]}.",
        render_text(view),
        "RECENT EVENTS (oldest first)\n" + ("\n".join(f"  {e}" for e in events) or "  (none)"),
        "YOUR NOTES\n" + (notes or "(empty)"),
    ]
    if step_choices:
        listed = "\n".join(f"  {n}. {c}" for n, c in enumerate(step_choices, 1))
        hint = (
            " If these are what you want, call `commit` now; repeating a choice changes nothing."
            if any(o.type == "commit" for o in options)
            else ""
        )
        parts.append(f"YOUR CHOICES SO FAR IN THIS STEP (accepted by the engine)\n{listed}\n{hint.strip()}".rstrip())
    parts.append("WHAT YOU CAN DO NOW (call one tool)\n" + options_text(options))
    return "\n\n".join(parts)

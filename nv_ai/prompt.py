"""What an AI player is sent (specification 8.1): the fixed tool list, the instructions
(rulebook, how to play through tools, the game mode, scenario story, persona) and each
decision's message.

Order matters for caching: tools and instructions are identical for every decision and every
seat up to the persona, which comes last. A decision's message starts with the game log, one
block per round; finished rounds never change, so they are cached too (log_blocks).
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
the full rulebook. Each message shows the game log (what happened that you were allowed to see,
oldest first; see "Memory" below), your current view of the game, your private notes, and the
actions you can take now.

- Act by calling tools. One message may call several: they are carried out in the order you call
  them, so make all the choices you can in one message (for example all your predictions,
  experiments, reveals or submissions of a step at once). The engine checks every action against
  the rules; if it refuses one, the actions after it are not carried out, and you get the reason
  and can try again.
- Ids: P1.. Probes (tools take the 0-based index, so P1 is 0), IP1.. input parameters, WO1.. world
  outcomes, T7 published theory 7 (tools take 7), M3 published method, D5 your development stack or
  manuscript, O12 observation record, E9 experiment, Q4 prediction. Seats are numbered from 0.
- In steps where everyone decides in secret (hiring, predictions, reveals, development, submission,
  peer review), set `commit` to true on your last choice (you are then committed right after it),
  or call the `commit` tool last. In the Experimentation phase you act in turn: actions you call
  together are carried out on your next turns, one action per turn, while the engine allows them.
- Every tool takes `reason`: one short sentence on why. It may also take `notes`: your private notes,
  replacing the old ones. You see them in every message, so keep your plans there. Notes are cut
  to {notes_max} characters.
- Hidden information stays hidden: other researchers cannot see your lab, and you cannot see theirs.

## Memory

At the table, researchers remember world states through their records, not by heart, and this
game keeps that fair. The game log never shows world states (Probe readings and outcomes,
experiment results): you see them in your view, in the World Grid of the current round (and of
the last round, until new Probes are dealt) and in your Records area for the records you hold.
Your notes must not hold exact world states either: no Probe readings or outcomes, no experiment
inputs or results, no lists of which input states gave which outcomes.
To remember a world state, keep its record in your Records area, and archive the records you want
to keep beyond its capacity (Development phase: Archive a record). Your notes may hold plans,
judgments about theories (e.g. which published theories you trust and why) and what the other
researchers seem to be doing.
"""

# The rulebook has rules for two games (Basic mechanics); the game being played is a setting.
GAME_MODES = {
    "normal": "This is the normal game. Rules marked \"Normal game\", \"Normal game only\" or \"(normal game only)\" "
    "apply; rules marked "
    "\"Simplified game\" do not.",
    "simplified": "This is the simplified game. Where the rulebook marks a rule \"Simplified game\", it applies "
    "instead of the normal rule; rules and sections marked \"Normal game\", \"Normal game only\" or "
    "\"(normal game only)\" do not apply. The actions offered to you include only what this game allows.",
}

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
        if name != "commit":
            properties["commit"] = {
                "type": "boolean",
                "description": "Optional, in steps where everyone decides in secret: true if this is your last "
                "choice in this step; you are then committed right after it.",
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


def instructions(story: str, persona: str, notes_max: int, mode: str = "normal") -> str:
    """Rulebook first (shared by every seat), then the interface, the game mode, the story and the persona."""
    if persona not in PERSONAS:
        raise ValueError(f"unknown persona {persona!r} (available: {', '.join(PERSONAS)})")
    if mode not in GAME_MODES:
        raise ValueError(f"unknown game mode {mode!r} (available: {', '.join(GAME_MODES)})")
    return "\n\n".join(
        [
            rules_text(),
            INTERFACE.format(notes_max=notes_max),
            "# This game\n\n" + GAME_MODES[mode],
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


# A message is a list of blocks: (text, cache breakpoint after it). The provider caches a request's
# start only up to a breakpoint, and writes at most four of them per request; the instructions take
# one (provider.py), the latest finished rounds of the game log the others.
Blocks = list[tuple[str, bool]]
CACHED_ROUNDS = 3


def log_blocks(log: list[tuple[int, str]], current_round: int, left_out: int = 0) -> Blocks:
    """The game log, one block per round. A finished round never changes, so the latest
    CACHED_ROUNDS of them end in a breakpoint: each is written to the cache once and read by every
    later decision. The current round comes last, without one (it grows within the round)."""
    head = "GAME LOG (what you were allowed to see, oldest first; world states are in your view)\n"
    if left_out:
        head += f"  ({left_out} earlier lines left out: the request would be too long)\n"
    rounds: dict[int, list[str]] = {}
    for r, line in log:
        rounds.setdefault(r, []).append(f"  {line}\n")
    if not rounds:
        return [(head + "  (none)\n", False)]
    finished = [r for r in rounds if r < current_round][-CACHED_ROUNDS:]
    blocks = [(head, False)] + [("".join(lines), r in finished) for r, lines in rounds.items()]
    return blocks


def fit_log(log: list[tuple[int, str]], room: int) -> tuple[list[tuple[int, str]], int]:
    """The newest whole rounds of the log that fit in ``room`` characters, and how many older lines
    are left out (whole rounds, so the blocks that stay are unchanged and still cached)."""
    used = sum(len(line) + 3 for _, line in log)
    start = 0
    while used > room and start < len(log):
        first = log[start][0]
        while start < len(log) and log[start][0] == first:
            used -= len(log[start][1]) + 3
            start += 1
    return log[start:], start


def message_text(blocks: Blocks) -> str:
    return "".join(text for text, _ in blocks)


def decision_message(
    view: dict[str, Any], options: list[Option], log: list[tuple[int, str]], notes: str,
    step_choices: list[str] = (), left_out: int = 0,
) -> Blocks:
    """The game log's blocks, then everything else in one block that changes every time.
    ``log``: (round, line) (``left_out``: older lines not sent). ``step_choices``: the actions of
    this seat the engine accepted earlier in the same step. Each decision is a fresh conversation,
    so without them a model cannot tell that it has already chosen and repeats the same choice
    instead of committing."""
    seat = view["seat"]
    parts = [
        f"You are seat {seat}, {view['players'][seat]}.",
        render_text(view),
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
    return log_blocks(log, view["round"], left_out) + [("\n" + "\n\n".join(parts), False)]

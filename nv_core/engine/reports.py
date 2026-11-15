"""Phase reports (specification 7.4): what each researcher did in one part of the round and what it
earned, for the web client. A report is made of the events logged in that part of the round, each
with its visibility, plus every researcher's academic credit before and after. The prediction
report has a shape of its own (observation.py); its events are only dropped here.

The events of the open report are kept in the state, so a report survives a restart of the server.
"""

from typing import Any

from nv_core.state import GameState, Phase

# The step that ends each part of the round, and the name of that part's report.
ENDS: dict[Phase, str | None] = {
    Phase.STUDENT_CHECK: "hiring",
    Phase.PROBE_TIME: "experimentation",
    Phase.SCORING_ORDER: None,  # the prediction report
    Phase.PEER_REVIEW: "publication",
}
CLEANUP = "cleanup"  # ends with the round (Talent development and Clean-up phases)

# Events that tell a report nothing: bookkeeping, or shown elsewhere in the report.
LEFT_OUT = {"commit", "round", "deck", "probe", "outcomes", "credit", "shield"}


def open_report(state: GameState) -> None:
    state.report_events = []
    state.report_credit = [r.credit for r in state.researchers]


def close_report(state: GameState, name: str | None) -> None:
    if name is not None:
        state.reports[name] = _build(state)
    open_report(state)


def _seat(event: dict[str, Any]) -> int | None:
    """Whose report line it is: the event's researcher, or the one researcher who may see it."""
    if "seat" in event["data"]:
        return event["data"]["seat"]
    shown = event["visible_to"]
    return shown[0] if shown and len(shown) == 1 else None


def _build(state: GameState) -> dict[str, Any] | None:
    events = state.report_events
    items = [
        {"seat": _seat(e), "kind": e["kind"], "text": e["text"], "visible_to": e["visible_to"],
         "data": {k: v for k, v in e["data"].items() if k != "seat"}}
        for e in events
        if e["kind"] not in LEFT_OUT
    ]
    credits = [
        {"seat": e["data"]["seat"], "amount": e["data"]["amount"], "reason": e["data"]["reason"]}
        for e in events
        if e["kind"] == "credit"
    ]
    if not items and not credits:
        return None
    before = state.report_credit if len(state.report_credit) == state.n_players else None  # None: an older game
    return {"round": state.round, "items": items, "credits": credits, "before": before,
            "after": [r.credit for r in state.researchers]}


def player_reports(state: GameState, seat: int | None) -> dict[str, Any]:
    """The latest report of each part of the round, with only the lines ``seat`` may see
    (``seat`` None: a spectator, who sees everything)."""
    shown: dict[str, Any] = {}
    for name, report in state.reports.items():
        if report is None:
            continue
        items = [
            {k: v for k, v in item.items() if k != "visible_to"}
            for item in report["items"]
            if seat is None or item["visible_to"] is None or seat in item["visible_to"]
        ]
        shown[name] = {**report, "items": items}
    return shown

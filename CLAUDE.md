# Null & Void

A board game about the replication crisis and questionable research practices, implemented in Python.
The designer is Zoltan Kekecs (psychology researcher and methodologist, comfortable with Python and R,
not a professional software engineer). Explain design decisions briefly.

## Where each fact lives

| Document | Holds |
| --- | --- |
| `docs/rules.md` | Every game rule, in phase order. Values appear only as `[parameter_name]`. Google Docs export (has Markdown escapes such as `\_`, `\[`); never edit it, Zoltan re-exports it. |
| `docs/parameter_defaults.yaml` | Every numeric game setting, incl. the `grant_track` and `journal_tiers` tables. |
| `scenarios/<id>/scenario.md` | Scenario story, input parameters and world outcomes, effect model, world acceptance criteria (YAML block + prose). |
| `docs/specification.md` | Software specification: architecture, world generator, engine, server, clients, AI, simulator, debrief, milestones. Section 5.7 holds rule clarifications the rulebook leaves to common sense. |
| `docs/open_questions.md` | Unresolved questions and answers waiting for a document update. |

Only the rulebook is an export; the other documents are maintained here and may be edited (with Zoltan's answers).

## Ground rules

- Each fact lives in exactly one document. On disagreement the priority is: rulebook > parameter file > scenario file > specification.
- Never copy rules, numbers or scenario values into code, comments or new docs. Load values from the files; refer to rules by their rulebook section heading.
- Readers of the rulebook must strip Markdown escapes (`nv_core.markdown_text.read_markdown`).
- If a rule is ambiguous or documents contradict each other, don't guess: add the question to `docs/open_questions.md` (section, exact text, possible readings) and ask Zoltan. Remove an entry once answered and the answer is in the right document.
- Commit in small, meaningful steps.

## Layout (specification section 3)

`nv_core` (rules engine, settings, decks), `nv_world` (scenario reader, World Table, screening, world files),
`nv_server`, `nv_ai`, `nv_sim`, `nv_rulebook` (PDF edition of the rulebook), `web/`, `scenarios/`, `docs/`, `tests/`.

## Commands

```sh
py -3.14 -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"   # once
.venv/Scripts/python -m pytest                                              # all tests
.venv/Scripts/python -m pytest tests/test_consistency.py                    # document consistency check
git config core.hooksPath .githooks                                         # once: run the check on every commit
```

## Subagents

- `rules-auditor` (read-only): compares code with the documents and reports mismatches. Never edits.
- `test-writer`: writes pytest tests from the documents alone, never reading the implementation.

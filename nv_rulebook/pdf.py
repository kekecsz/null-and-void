"""Drawing the filled-in rulebook as a PDF.

    nv-rulebook-pdf [--out PATH]

ReportLab is used because it is pure Python: no LaTeX or browser needs to be installed. The built-in
fonts only cover Windows-1252, so any other character stops the build instead of printing a black box.
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Iterator
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.platypus.tableofcontents import TableOfContents

from nv_core.markdown_text import read_markdown
from nv_core.paths import REPO_ROOT, RULEBOOK
from nv_core.settings import load_settings
from nv_rulebook.fill import TABLE_LINE, fill_rulebook, table_rows

DEFAULT_OUT = REPO_ROOT / "dist" / "Null_and_Void_rulebook.pdf"
_MARGIN = 20 * mm
_FIRST_COLUMN_WIDTH = 13 * mm
_INK = colors.HexColor("#1f2a44")
_RULE = colors.HexColor("#b8bfcc")
_NOTE = colors.HexColor("#555555")

_ITALIC = re.compile(r"(?<![\w*])\*(\S(?:[^*\n]*\S)?)\*(?![\w*])")
_NOTE_LINE = re.compile(r"^\((?:Designer|Developer)")

_BODY = ParagraphStyle("Body", fontName="Times-Roman", fontSize=10.5, leading=14, spaceAfter=6)
_STYLES = {
    "title": ParagraphStyle("Title", fontName="Helvetica-Bold", fontSize=30, leading=36, textColor=_INK,
                            alignment=TA_CENTER, spaceBefore=40, spaceAfter=8),
    "subtitle": ParagraphStyle("Subtitle", fontName="Helvetica", fontSize=13, leading=18, textColor=_INK,
                               alignment=TA_CENTER, spaceAfter=4),
    "date": ParagraphStyle("Date", fontName="Helvetica", fontSize=9, leading=12, textColor=_NOTE,
                           alignment=TA_CENTER, spaceAfter=28),
    "contents": ParagraphStyle("Contents", fontName="Helvetica-Bold", fontSize=13, leading=18, textColor=_INK,
                               spaceAfter=6),
    "h1": ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=_INK,
                         spaceBefore=16, spaceAfter=6, keepWithNext=1),
    "h2": ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=_INK,
                         spaceBefore=10, spaceAfter=4, keepWithNext=1),
    "p": _BODY,
    "note": ParagraphStyle("Note", parent=_BODY, fontName="Times-Italic", textColor=_NOTE),
    "bullet0": ParagraphStyle("Bullet0", parent=_BODY, leftIndent=14, bulletIndent=3, spaceAfter=3),
    "bullet1": ParagraphStyle("Bullet1", parent=_BODY, leftIndent=28, bulletIndent=17, spaceAfter=3),
    "cell": ParagraphStyle("Cell", fontName="Helvetica", fontSize=8, leading=10, alignment=TA_CENTER),
    "head": ParagraphStyle("Head", fontName="Helvetica-Bold", fontSize=7, leading=9, alignment=TA_CENTER,
                           textColor=colors.white),
    "toc": ParagraphStyle("Toc", fontName="Helvetica", fontSize=10, leading=15),
}


def check_printable(text: str) -> None:
    """Stop on a character the built-in PDF fonts cannot draw."""
    for number, line in enumerate(text.splitlines(), start=1):
        for character in line:
            try:
                character.encode("cp1252")
            except UnicodeEncodeError:
                raise ValueError(f"line {number}: the PDF fonts cannot print {character!r}: {line[:80]}") from None


def _inline(text: str) -> str:
    return _ITALIC.sub(r"<i>\1</i>", escape(text.strip()))


def blocks(text: str) -> Iterator[tuple[str, Any]]:
    """The filled-in Markdown as (kind, content) pairs."""
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        table = TABLE_LINE.match(stripped)
        heading = re.match(r"^(#{1,2})\s+(.*)$", stripped)
        if table:
            yield "table", table.group(1)
        elif heading:
            yield f"h{len(heading.group(1))}", heading.group(2).strip()
        elif stripped.startswith("- "):
            depth = 1 if len(raw) - len(raw.lstrip()) >= 2 else 0
            yield f"bullet{depth}", stripped[2:]
        elif _NOTE_LINE.match(stripped):
            yield "note", stripped
        else:
            yield "p", stripped


def _table(name: str, settings: dict[str, Any], width: float) -> Table:
    header, rows = table_rows(name, settings)
    data = [[Paragraph(escape(h), _STYLES["head"]) for h in header]]
    data += [[Paragraph(escape(c), _STYLES["cell"]) for c in row] for row in rows]
    first = _FIRST_COLUMN_WIDTH
    widths = [first] + [(width - first) / (len(header) - 1)] * (len(header) - 1)
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="CENTER", spaceBefore=4, spaceAfter=10)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _INK),
        ("GRID", (0, 0), (-1, -1), 0.4, _RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f8")]),
    ]))
    return table


class _Rulebook(BaseDocTemplate):
    """Page numbers, PDF bookmarks, and table-of-contents entries for the main headings."""

    def __init__(self, path: Path):
        super().__init__(str(path), pagesize=A4, leftMargin=_MARGIN, rightMargin=_MARGIN, topMargin=_MARGIN,
                         bottomMargin=_MARGIN, title="Null and Void: Rulebook", author="Zoltan Kekecs")
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="body", leftPadding=0,
                      rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates(PageTemplate(id="page", frames=frame, onPage=self._footer))
        self._seq = 0

    def beforeDocument(self) -> None:  # the contents page needs several passes; keep the keys the same
        self._seq = 0

    @staticmethod
    def _footer(canvas, doc) -> None:
        canvas.setFont("Helvetica", 8.5)
        canvas.setFillColor(_NOTE)
        canvas.drawCentredString(A4[0] / 2, 11 * mm, str(doc.page))

    def afterFlowable(self, flowable) -> None:
        if not isinstance(flowable, Paragraph) or flowable.style.name not in ("H1", "H2"):
            return
        self._seq += 1
        key = f"section{self._seq}"
        text = flowable.getPlainText()
        level = 0 if flowable.style.name == "H1" else 1
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=level, closed=level == 0)
        if level == 0:
            self.notify("TOCEntry", (0, text, self.page, key))


def build_story(filled: str, settings: dict[str, Any], width: float) -> list:
    items = list(blocks(filled))
    if not items or items[0][0] != "h1":
        raise ValueError("the rulebook should start with its title as a main heading")
    story: list = [Paragraph(_inline(items[0][1]), _STYLES["title"]),
                   Paragraph("Rulebook with the default game settings", _STYLES["subtitle"])]
    rest = items[1:]
    if rest and rest[0][0] == "p" and rest[0][1].startswith("Last updated"):
        story.append(Paragraph(_inline(rest[0][1]), _STYLES["date"]))
        rest = rest[1:]
    else:
        story.append(Spacer(1, 28))
    contents = TableOfContents()
    contents.levelStyles = [_STYLES["toc"]]
    contents.dotsMinLevel = 0
    story += [Paragraph("Contents", _STYLES["contents"]), contents, PageBreak()]

    for kind, content in rest:
        if kind == "table":
            story.append(_table(content, settings, width))
        elif kind.startswith("bullet"):
            story.append(Paragraph(_inline(content), _STYLES[kind], bulletText="•" if kind == "bullet0" else "–"))
        else:
            story.append(Paragraph(_inline(content), _STYLES[kind]))
    return story


def make_pdf(out: Path = DEFAULT_OUT, rulebook: Path = RULEBOOK) -> Path:
    """Write the filled-in rulebook to ``out``, using the defaults in parameter_defaults.yaml."""
    settings = load_settings().model_dump()
    filled = fill_rulebook(read_markdown(rulebook), settings)
    check_printable(filled)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    document = _Rulebook(out)
    document.multiBuild(build_story(filled, settings, document.width))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nv-rulebook-pdf", description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"PDF to write (default: {DEFAULT_OUT})")
    args = parser.parse_args(argv)
    try:
        print(f"Rulebook written to {make_pdf(args.out)}")
    except ValueError as exc:  # includes FillError
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

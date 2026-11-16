"""The filled-in rulebook as a PDF, styled as an issue of a scholarly journal (specification 7.5).

    nv-rulebook-pdf [--out PATH]

ReportLab is used because it is pure Python: no LaTeX or browser needs to be installed. The page
is two columns; tables are made to fit one column, so nothing has to float across the page.
"""

import argparse
import io
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, Image, KeepTogether, NextPageTemplate, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

from nv_core.markdown_text import read_markdown, section_text
from nv_core.paths import DOCS_DIR, REPO_ROOT, RULEBOOK, SPECIFICATION
from nv_core.settings import load_settings
from nv_rulebook.fill import TABLE_LINE, fill_rulebook, table_rows

DEFAULT_OUT = REPO_ROOT / "dist" / "Null_and_Void_rulebook.pdf"
CREDITS = DOCS_DIR / "credits.md"
FONTS = Path(__file__).parent / "fonts"
IMAGES = REPO_ROOT / "web" / "images"
ICONS = REPO_ROOT / "web" / "icons"
EXAMPLE_ICONS = ICONS / "venus_expedition"
COVER_IMAGE = IMAGES / "Venus (Mariner 10).jpg"
CRISIS_IMAGE = IMAGES / "Venus mountain.jpg"

W, H = A4
MARGIN = 20 * mm
WIDTH = W - 2 * MARGIN
GUTTER = 6 * mm
COLUMN = (WIDTH - GUTTER) / 2
BODY_TOP, BODY_BOTTOM = H - 20 * mm, 15 * mm
BODY_HEIGHT = BODY_TOP - BODY_BOTTOM
# Full-width figures at the top of a page take at most this much of it, so the columns below keep
# room for a main heading with its first lines (and the Crisis figure); taller pictures are shrunk.
FIGURE_AREA = BODY_HEIGHT * 0.5
MAX_LAYOUTS = 30  # attempts to put every figure on the page that refers to it
MIN_FIGURE_SCALE = 0.6  # a figure shrunk to keep its reference on its page; below this, the reference moves
FIGURE_GAP = 5 * mm  # between a figure's caption and what follows

INK, PAPER, RUST, GREY, BOX = [colors.HexColor(x) for x in ("#1C1A17", "#FAF6EC", "#A8481F", "#6B655B", "#F1E9D8")]
RUST_HEX = "#A8481F"

_SERIF, _ITALIC, _BOLD, _DISPLAY, _SANS, _SANS_BOLD = "NvSerif", "NvSerif-It", "NvSerif-Bold", "NvDisplay", "NvSans", "NvSans-Semi"

_BODY = ParagraphStyle("Body", fontName=_SERIF, fontSize=9.3, leading=12.1, textColor=INK, alignment=TA_JUSTIFY, spaceAfter=4.4)
_STYLES = {
    "h1": ParagraphStyle("H1", fontName=_DISPLAY, fontSize=19, leading=23, textColor=INK, spaceBefore=13, spaceAfter=6),
    "h2": ParagraphStyle("H2", fontName=_BOLD, fontSize=11, leading=13.6, textColor=INK, spaceBefore=7, spaceAfter=3.4),
    "label": ParagraphStyle("Label", fontName=_BOLD, fontSize=9.4, leading=12.4, textColor=INK, spaceBefore=2, spaceAfter=2, keepWithNext=1),
    "p": _BODY,
    "bullet0": ParagraphStyle("Bullet0", parent=_BODY, leftIndent=10, bulletIndent=1, bulletFontName=_SERIF, spaceAfter=3),
    "bullet1": ParagraphStyle("Bullet1", parent=_BODY, leftIndent=20, bulletIndent=11, bulletFontName=_SERIF, spaceAfter=3),
    "caption": ParagraphStyle("Caption", fontName=_SANS, fontSize=8, leading=10.4, textColor=INK, spaceBefore=4, spaceAfter=3, keepWithNext=1),
    "figure_caption": ParagraphStyle("FigureCaption", fontName=_SANS, fontSize=8, leading=10.4, textColor=INK, spaceBefore=3, spaceAfter=8),
    "see_figure": ParagraphStyle("SeeFigure", fontName=_ITALIC, fontSize=9.3, leading=12.1, textColor=RUST, spaceAfter=4.4),
    "note_label": ParagraphStyle("NoteLabel", fontName=_SANS_BOLD, fontSize=7, leading=9, textColor=RUST, spaceAfter=2),
    "note": ParagraphStyle("Note", fontName=_ITALIC, fontSize=8.7, leading=11.2, textColor=INK),
    "head": ParagraphStyle("Head", fontName=_SANS_BOLD, fontSize=7.2, leading=8.6, textColor=INK, alignment=TA_CENTER),
    "cell": ParagraphStyle("Cell", fontName=_SANS, fontSize=8.1, leading=9.9, textColor=INK, alignment=TA_CENTER),
    "cell_left": ParagraphStyle("CellLeft", fontName=_SANS, fontSize=8.1, leading=9.9, textColor=INK, alignment=TA_LEFT),
    "title": ParagraphStyle("Title", fontName=_DISPLAY, fontSize=25, leading=30, textColor=INK, spaceAfter=7),
    "abstract": ParagraphStyle("Abstract", fontName=_SERIF, fontSize=9.2, leading=12, textColor=INK, alignment=TA_JUSTIFY, spaceAfter=3.5),
    "credits": ParagraphStyle("Credits", fontName=_SERIF, fontSize=8.2, leading=10.6, textColor=INK, alignment=TA_LEFT, spaceAfter=2),
}
_TABLE_CAPTIONS = {
    "journal_tiers": "Requirements and costs of the journal tiers.",
    "grant_track": "The positions of the Grant funding track.",
    "talent_development_track": "The positions of the Talent development track.",
}
_ROTATE_ABOVE = 6  # a table with more columns than this is printed with rows and columns swapped

_ITALICS = re.compile(r"(?<![\w*])\*(\S(?:[^*\n]*\S)?)\*(?![\w*])")
_LINK = re.compile(r"\[([^\]]+)\]\((https?:[^)\s]+)\)")
_NOTE_AT_END = re.compile(r"\s*[\[(]((?:Designer|Developer))(?:[’']s)? notes?:\s*(.*?)[\])]\.?\s*$", re.DOTALL)
_HEADING = re.compile(r"^(#{1,2})\s+(.*)$")
# "[Figure: <file in web/images>]" places a picture the text refers to ("See Figure N."), and
# "[Illustration: <file>]" one it does not (a photo); "[... goes here]" marks what this script
# draws itself (the cover, the overview page).
_PICTURE = re.compile(r"^\[(Figure|Illustration):\s*(.+?)\s*\]$")
# Captions other than the file name in words.
_CAPTIONS = {
    "2438_pioneer_venus_map_of_venus.jpg": "A map of Venus compiled from data from the Pioneer Venus Orbiter",
    "world_grid_exp_with_different_sensor_levels.png": "Probes with different sensor levels",
}
_PLACEHOLDER = re.compile(r"^\[[^\]]* goes here\]$")


def _register_fonts() -> None:
    if _SERIF in pdfmetrics.getRegisteredFontNames():
        return
    for name, file in ((_SERIF, "SourceSerif4-Regular"), (_ITALIC, "SourceSerif4-It"), (_BOLD, "SourceSerif4-Bold"),
                       ("NvSerif-BoldIt", "SourceSerif4-BoldIt"), (_DISPLAY, "SourceSerif4Display-Semibold"),
                       (_SANS, "IBMPlexSans-Regular"), (_SANS_BOLD, "IBMPlexSans-SemiBold")):
        pdfmetrics.registerFont(TTFont(name, str(FONTS / f"{file}.ttf")))
    pdfmetrics.registerFontFamily(_SERIF, normal=_SERIF, bold=_BOLD, italic=_ITALIC, boldItalic="NvSerif-BoldIt")
    pdfmetrics.registerFontFamily(_SANS, normal=_SANS, bold=_SANS_BOLD, italic=_SANS, boldItalic=_SANS_BOLD)


def check_printable(text: str) -> None:
    """Stop on a character the PDF fonts cannot draw."""
    _register_fonts()
    known = pdfmetrics.getFont(_SERIF).face.charToGlyph
    for number, line in enumerate(text.splitlines(), start=1):
        for character in line:
            if ord(character) not in known:
                raise ValueError(f"line {number}: the PDF fonts cannot print {character!r}: {line[:80]}")


def _inline(text: str) -> str:
    text = _ITALICS.sub(r"<i>\1</i>", escape(text.strip()))
    return _LINK.sub(lambda m: f'<a href="{m.group(2)}" color="{RUST_HEX}">{m.group(1)}</a>', text)


def blocks(text: str) -> Iterator[tuple[str, Any]]:
    """The filled-in Markdown as (kind, content) pairs."""
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        table = TABLE_LINE.match(stripped)
        heading = _HEADING.match(stripped)
        picture = _PICTURE.match(stripped)
        if _PLACEHOLDER.match(stripped):
            continue
        if picture:
            yield picture.group(1).lower(), picture.group(2)
        elif table:
            yield "table", table.group(1)
        elif heading:
            yield f"h{len(heading.group(1))}", heading.group(2).strip()
        elif stripped.startswith("- "):
            depth = 1 if len(raw) - len(raw.lstrip()) >= 2 else 0
            yield f"bullet{depth}", stripped[2:]
        else:
            yield "p", stripped


def structure(items: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    """Find what the export only shows typographically: designer's notes, labels, run-in headings."""
    result: list[tuple[str, Any]] = []
    for index, (kind, content) in enumerate(items):
        if kind == "h2":
            result.append(("h2", content.rstrip(" :")))
            continue
        if kind != "p":
            result.append((kind, content))
            continue
        note = _NOTE_AT_END.search(content)
        if note:
            before = content[: note.start()].strip()
            if before:
                result.append(("p", before))
            text = note.group(2).strip()
            result.append(("note", (f"{note.group(1)}’s note", text[:1].upper() + text[1:])))
            continue
        italic = re.fullmatch(r"\*([^*]+):\*", content)
        if italic:
            result.append(("h2", italic.group(1)))
            continue
        following = items[index + 1][0] if index + 1 < len(items) else None
        if len(content.split()) <= 3 and following == "bullet0":
            result.append(("label", content.rstrip(":")))
            continue
        result.append(("p", content))
    return result


@dataclass
class Phase:
    heading: str
    short: str
    who: str
    staff: str


def round_overview() -> list[Phase]:
    """The phases of a round, from the table in specification 7.5."""
    phases = []
    for line in section_text(read_markdown(SPECIFICATION), "7.5").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 4 and cells[0] != "Rulebook heading" and not set(cells[0]) <= {"-", " "}:
            phases.append(Phase(*cells))
    return phases


@dataclass
class Content:
    """What the story and the cover are built from."""

    settings: dict[str, Any]
    date: str
    abstract: list[str]
    body: list[tuple[str, Any]]
    credits: list[tuple[str, Any]]
    phases: list[Phase]
    sections: list[tuple[int, str]]  # numbered main headings, in order
    example: dict[str, str]

    def number_of(self, heading: str) -> int:
        return next(n for n, title in self.sections if title == heading)


def read_content(filled: str, settings: dict[str, Any]) -> Content:
    items = list(blocks(filled))
    if not items or items[0][0] != "h1":
        raise ValueError("the rulebook should start with its title as a main heading")
    items = items[1:]
    date = ""
    if items and items[0][0] == "p" and items[0][1].startswith("Last updated"):
        date = items[0][1].removeprefix("Last updated:").strip().split(" ")[0].rstrip(".")
        items = items[1:]
    start = items.index(("h1", "Summary"))
    end = next(i for i in range(start + 1, len(items)) if items[i][0] == "h1")
    abstract = [c for k, c in items[start + 1 : end] if k == "p"]
    body = structure(items[:start] + items[end:])
    sections = [(n, c) for n, c in enumerate((c for k, c in body if k == "h1"), start=1)]
    phases = round_overview()
    titles = {title for _, title in sections}
    missing = [p.heading for p in phases if p.heading not in titles]
    if missing or not phases:
        raise ValueError(f"specification 7.5 names phases the rulebook does not have as main headings: {missing or 'none listed'}")
    example = {}
    for kind, content in structure(items):
        if kind == "bullet0" and ":" in content:
            key, value = content.split(":", 1)
            example.setdefault(key.strip(), value.strip())
    needed = ["Plain word description", "Input Parameter 1", "World outcome 1"]
    if any(key not in example for key in needed):
        raise ValueError("the rulebook's Example Theory, drawn on the overview page, no longer has the expected lines")
    credits_items = [(k, c) for k, c in blocks(read_markdown(CREDITS)) if k != "h1"]
    return Content(settings, date, abstract, body, credits_items, phases, sections, example)


# Flowables -------------------------------------------------------------------------------------
class NeedRoom(Flowable):
    """Goes on to the next column when less than ``height`` is left. Used before headings: keeping a
    heading together with its whole paragraph would leave large gaps at the bottom of columns."""

    def __init__(self, height: float):
        super().__init__()
        self.need = height

    def wrap(self, available_width, available_height):
        return available_width, 0 if available_height >= self.need else available_height + 1

    def draw(self):
        pass


class TheoryFigure(Flowable):
    """The rulebook's example theory, as tiles."""

    def __init__(self, example: dict[str, str], width: float):
        super().__init__()
        inputs = sorted(k for k in example if k.startswith("Input Parameter "))
        outcomes = sorted(k for k in example if k.startswith("World outcome "))
        self.slots = [example[k] for k in inputs] + ["->"] + [example[k] for k in outcomes]
        self.width, self.tile, self.gap = width, 17 * mm, 5 * mm
        self.height = self.tile + 11

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        c, tile, gap = self.canv, self.tile, self.gap
        arrow = tile * 0.6
        tiles = sum(1 for s in self.slots if s != "->")
        x = (self.width - tiles * tile - arrow - gap * (len(self.slots) - 1)) / 2
        for slot in self.slots:
            if slot == "->":
                c.setFillColor(GREY)
                c.setFont(_SANS, tile * 0.55)
                c.drawCentredString(x + arrow / 2, 11 + tile * 0.38, "→")
                x += arrow + gap
                continue
            blank = "blank" in slot
            if blank:
                c.setDash(3, 2)
                c.setStrokeColor(GREY)
                c.setLineWidth(0.8)
                c.roundRect(x, 11, tile, tile, tile * 0.18, stroke=1, fill=0)
                c.setDash()
            else:
                c.drawImage(str(EXAMPLE_ICONS / f"{slot.replace(' ', '_')}.png"), x, 11, tile, tile, mask="auto")
            c.setFillColor(GREY if blank else INK)
            c.setFont(_SANS, 7.5)
            c.drawCentredString(x + tile / 2, 2, slot)
            x += tile + gap


def _rules(table: Table, extra: list | None = None) -> Table:
    table.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1.1, INK), ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK), ("LINEBELOW", (0, -1), (-1, -1), 1.1, INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.8),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2), *(extra or []),
    ]))
    return table


def column_table(name: str, settings: dict[str, Any]) -> Table:
    """A parameter table that fits one column; a wide one is printed with rows and columns swapped."""
    header, rows = table_rows(name, settings)
    if len(header) > _ROTATE_ABOVE:
        header, rows = ["", *(f"{header[0]} {r[0]}" for r in rows)], [[header[j], *(r[j] for r in rows)] for j in range(1, len(header))]
        first = 31 * mm
        widths = [first] + [(COLUMN - first) / (len(header) - 1)] * (len(header) - 1)
    else:
        widths = [COLUMN / len(header)] * len(header)
    left = len(widths) > 1 and widths[0] != widths[1]
    data = [[Paragraph(escape(x), _STYLES["head"]) for x in header]]
    data += [[Paragraph(escape(x), _STYLES["cell_left" if left and i == 0 else "cell"]) for i, x in enumerate(row)] for row in rows]
    return _rules(Table(data, colWidths=widths))


def note_box(label: str, text: str) -> Table:
    box = Table([[[Paragraph(label.upper(), _STYLES["note_label"]), Paragraph(_inline(text), _STYLES["note"])]]], colWidths=[COLUMN], spaceBefore=4, spaceAfter=8)
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BOX), ("LINEABOVE", (0, 0), (-1, 0), 0.9, RUST),
                             ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                             ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return box


def crisis_figure(content: Content, label: str) -> list:
    stat = ParagraphStyle("Stat", fontName=_DISPLAY, fontSize=22, leading=24, textColor=RUST)
    words = ParagraphStyle("StatWords", fontName=_SANS, fontSize=7.8, leading=9.8, textColor=INK)
    settings = content.settings
    pairs = ((settings["crisis_length"], "rounds of Crisis"), (settings["crisis_condition"], "unsuccessful predictions and everyone loses"))
    stats = Table([[[Paragraph(str(n), stat), Paragraph(text, words)] for n, text in pairs]], colWidths=[COLUMN / 2] * 2, spaceAfter=7)
    stats.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.9, RUST), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return [Image(str(CRISIS_IMAGE), width=COLUMN, height=COLUMN * 0.75),
            Paragraph(f"<b>{label}.</b> A mountain on Venus.", _STYLES["figure_caption"]), stats]


@dataclass
class PageFigure:
    """A picture printed across the top of the page whose text refers to it (make_pdf)."""

    path: Path
    number: int  # the order of the pictures placed this way, which the layout goes by
    label: str = ""  # "Figure 3" or "Illustration 1", as captioned
    scale: float = 1.0  # shrunk to keep the text that refers to it on its page (place_figures)

    @property
    def caption(self) -> Paragraph:  # the file name in words, unless _CAPTIONS has one
        words = _CAPTIONS.get(self.path.name) or re.sub(r"^\d+\s*", "", self.path.stem.replace("_", " ")).strip()
        return Paragraph(f"<b>{self.label}.</b> {escape(words[:1].upper() + words[1:])}.", _STYLES["figure_caption"])

    def caption_height(self) -> float:
        return self.caption.wrap(WIDTH, BODY_HEIGHT)[1] + 3

    def size(self, shrink: float = 1.0) -> tuple[float, float]:
        width, height = ImageReader(str(self.path)).getSize()
        scale = min(WIDTH / width, (FIGURE_AREA - self.caption_height() - FIGURE_GAP) / height) * self.scale * shrink
        return width * scale, height * scale

    def height(self, shrink: float = 1.0) -> float:
        return self.size(shrink)[1] + self.caption_height() + FIGURE_GAP

    def draw(self, canvas, top: float, shrink: float) -> float:
        """Draws the figure below ``top``; returns where the next one starts."""
        width, height = self.size(shrink)
        canvas.drawImage(str(self.path), MARGIN + (WIDTH - width) / 2, top - height, width, height, mask="auto")
        caption = self.caption
        _, caption_height = caption.wrap(WIDTH, BODY_HEIGHT)
        caption.drawOn(canvas, MARGIN, top - height - 3 - caption_height)
        return top - self.height(shrink)


def page_shrink(figures: list[PageFigure]) -> float:
    """How much the pictures of one page are shrunk so that together they fit in FIGURE_AREA."""
    pictures = sum(f.size()[1] for f in figures)
    rest = sum(f.caption_height() + FIGURE_GAP for f in figures)
    return min(1.0, (FIGURE_AREA - rest) / pictures) if pictures else 1.0


class FigureAnchor(Flowable):
    """Where the text refers to a full-width figure; the layout notes on which page it lands."""

    def __init__(self, figure: PageFigure):
        super().__init__()
        self.figure = figure

    def wrap(self, available_width, available_height):
        return 0, 0

    def draw(self):
        pass


class FigureStart(FigureAnchor):
    """Where the paragraph that refers to a figure starts."""


# Pages -------------------------------------------------------------------------------------------
def _paper(canvas, doc) -> None:
    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, W, H, stroke=0, fill=1)


def _body(canvas, doc) -> None:
    _paper(canvas, doc)
    top = BODY_TOP
    for figure in doc.page_figures:
        top = figure.draw(canvas, top, doc.shrink)
    if doc.page_figures:
        canvas.setStrokeColor(INK)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, top + FIGURE_GAP / 2, W - MARGIN, top + FIGURE_GAP / 2)


def _columns(height: float) -> list[Frame]:
    return [Frame(MARGIN + i * (COLUMN + GUTTER), BODY_BOTTOM, COLUMN, height, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
            for i in range(2)]


def _running(canvas, doc) -> None:
    canvas.setFillColor(GREY)
    canvas.setFont(_SANS, 7.8)
    canvas.drawString(MARGIN, H - 13 * mm, "Null & Void  ·  Vol. 1, Issue 1")
    canvas.drawRightString(W - MARGIN, H - 13 * mm, doc.running)
    canvas.setStrokeColor(INK)
    canvas.setLineWidth(0.7)
    canvas.line(MARGIN, H - 15 * mm, W - MARGIN, H - 15 * mm)
    canvas.setFillColor(INK)
    canvas.setFont(_SANS, 8.5)
    canvas.drawCentredString(W / 2, 9.5 * mm, str(doc.page))


def _cover(canvas, doc) -> None:
    _paper(canvas, doc)
    content, pages = doc.content, doc.known_pages
    canvas.setStrokeColor(INK)
    canvas.setLineWidth(2.4)
    canvas.line(MARGIN, H - 18 * mm, W - MARGIN, H - 18 * mm)
    canvas.setFillColor(INK)
    canvas.setFont(_DISPLAY, 66)
    canvas.drawCentredString(W / 2, H - 44 * mm, "Null & Void")
    canvas.setFont(_ITALIC, 14.5)
    canvas.drawCentredString(W / 2, H - 53 * mm, "Proceedings of the Venus Expedition")
    canvas.setLineWidth(0.7)
    canvas.line(MARGIN, H - 58 * mm, W - MARGIN, H - 58 * mm)
    canvas.setFont(_SANS, 9)
    canvas.drawString(MARGIN, H - 63 * mm, "Vol. 1, Issue 1")
    canvas.drawCentredString(W / 2, H - 63 * mm, "SPECIAL ISSUE: THE RULEBOOK")
    canvas.drawRightString(W - MARGIN, H - 63 * mm, content.date)
    canvas.line(MARGIN, H - 66 * mm, W - MARGIN, H - 66 * mm)
    image_h = WIDTH * 720 / 1280
    canvas.drawImage(str(COVER_IMAGE), MARGIN, H - 71 * mm - image_h, WIDTH, image_h)
    y = H - 71 * mm - image_h - 5 * mm
    canvas.setFont(_ITALIC, 8.5)
    canvas.setFillColor(GREY)
    canvas.drawString(MARGIN, y, "On the cover: Venus as seen by Mariner 10. Image: NASA.")
    y -= 11 * mm
    canvas.setFillColor(RUST)
    canvas.setFont(_SANS_BOLD, 10)
    canvas.drawString(MARGIN, y, "IN THIS ISSUE")
    canvas.setStrokeColor(RUST)
    canvas.setLineWidth(0.8)
    canvas.line(MARGIN, y - 2.5 * mm, W - MARGIN, y - 2.5 * mm)
    y -= 9 * mm
    half = math.ceil(len(content.phases) / 2)
    for i, phase in enumerate(content.phases):
        x = MARGIN + (0 if i < half else COLUMN + GUTTER)
        row_y = y - (i % half) * 11 * mm
        canvas.setFillColor(RUST)
        canvas.setFont(_BOLD, 11)
        canvas.drawString(x, row_y, str(content.number_of(phase.heading)))
        canvas.setFillColor(INK)
        canvas.setFont(_SERIF, 13)
        canvas.drawString(x + 10 * mm, row_y, phase.short)
        canvas.setFillColor(GREY)
        canvas.setFont(_SANS, 9)
        canvas.drawRightString(x + COLUMN - 2 * mm, row_y, str(pages.get(phase.heading, "")))
        canvas.linkRect("", destination(phase.heading), (x, row_y - 2.5 * mm, x + COLUMN, row_y + 5 * mm), thickness=0)
    canvas.setFillColor(INK)
    canvas.setFont(_ITALIC, 10.5)
    canvas.drawCentredString(W / 2, 19 * mm, "Zoltan Kekecs, Editor")
    canvas.setFont(_SANS, 8.5)
    canvas.setFillColor(GREY)
    settings = content.settings
    canvas.drawCentredString(W / 2, 13 * mm, f"For {settings['min_players']}–{settings['max_players']} researchers. Peer review not guaranteed.")


def destination(title: str) -> str:
    """The name of a main section's place in the PDF, which the contents link to."""
    return "section-" + re.sub(r"\W+", "-", title).strip("-").lower()


def _linked(text: str, title: str) -> str:
    return f'<a href="#{destination(title)}">{text}</a>'


class _Issue(BaseDocTemplate):
    """Page furniture, PDF bookmarks, and where each main section starts."""

    def __init__(self, target, content: Content, known_pages: dict[str, int], figures: dict[int, PageFigure] | None = None,
                 plan: dict[int, int] | None = None):
        super().__init__(target, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=20 * mm, bottomMargin=15 * mm,
                         title="Null & Void: Rulebook", author="Zoltan Kekecs")
        self.content, self.known_pages = content, known_pages
        self.found_pages: dict[str, int] = {}
        self.running = "A round at a glance"
        self._bookmarks = 0
        self.figures = figures or {}  # by number
        self.plan = plan or {}  # figure number -> the page it is printed on
        self.anchor_pages: dict[int, int] = {}  # figure number -> the page whose text refers to it
        self.anchor_room: dict[int, float] = {}  # figure number -> column space left on that page after the reference
        self.start_pages: dict[int, int] = {}  # figure number -> the page where its referring paragraph starts
        self.page_figures: list[PageFigure] = []  # those at the top of this page
        self.shrink = 1.0
        self.printed: list[int] = []  # the numbers of the figures printed so far
        whole = lambda: Frame(MARGIN, BODY_BOTTOM, WIDTH, BODY_HEIGHT, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([
            PageTemplate(id="cover", frames=whole(), onPage=_cover),
            PageTemplate(id="overview", frames=whole(), onPage=_paper, onPageEnd=_running),
            PageTemplate(id="body", frames=_columns(BODY_HEIGHT), onPage=_body, onPageEnd=_running),
        ])

    def handle_pageBegin(self) -> None:
        """The figures planned for this page go across its top; the columns take the rest."""
        self.page_figures = []
        if self.pageTemplate.id == "body":
            # the page number is counted up by the base class, in super().handle_pageBegin()
            self.page_figures = [self.figures[n] for n in sorted(self.plan) if self.plan[n] == self.page + 1]
            self.shrink = page_shrink(self.page_figures)
            self.printed += [f.number for f in self.page_figures]
            self.pageTemplate.frames = _columns(BODY_HEIGHT - sum(f.height(self.shrink) for f in self.page_figures))
        super().handle_pageBegin()

    def afterFlowable(self, flowable) -> None:
        if isinstance(flowable, FigureStart):
            self.start_pages[flowable.figure.number] = self.page
            return
        if isinstance(flowable, FigureAnchor):
            frames = self.pageTemplate.frames
            later = frames[frames.index(self.frame) + 1:] if self.frame in frames else []
            self.anchor_pages[flowable.figure.number] = self.page
            self.anchor_room[flowable.figure.number] = (self.frame._y - self.frame._y1) + sum(f._height for f in later)
            return
        heading = getattr(flowable, "heading", None)
        if heading is None:
            return
        title, level, numbered = heading
        self._bookmarks += 1
        key = destination(title) if level == 0 else f"s{self._bookmarks}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(numbered, key, level=level, closed=level == 0)
        if level == 0:
            self.found_pages[title] = self.page
            self.running = numbered


def _heading(kind: str, title: str, number: str | None, level: int, suffix: str = "") -> Paragraph:
    label = f'<font color="{RUST_HEX}">{number}</font>&nbsp;&nbsp;' if number else ""
    paragraph = Paragraph(f"{label}{escape(title)}{suffix}", _STYLES[kind])
    paragraph.heading = (title, level, f"{number}. {title}" if number else title)
    return paragraph


def _overview(content: Content, pages: dict[str, int]) -> list:
    width = WIDTH
    abstract = [Paragraph("ABSTRACT", _STYLES["note_label"])] + [Paragraph(_inline(p), _STYLES["abstract"]) for p in content.abstract]
    box = Table([[abstract]], colWidths=[width], spaceAfter=9)
    box.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.7, RUST), ("LINEBELOW", (0, 0), (-1, 0), 0.7, RUST), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    left = _STYLES["cell_left"]
    head = ParagraphStyle("HeadLeft", parent=_STYLES["head"], alignment=TA_LEFT)
    data = [[Paragraph(x, head) for x in ("Phase", "Who decides", "Staff at work", "Page")]]
    for phase in content.phases:
        row = [phase.short, phase.who, phase.staff, str(pages.get(phase.heading, ""))]
        data.append([Paragraph(_linked(escape(x), phase.heading) if i in (0, 3) else escape(x), left) for i, x in enumerate(row)])
    table = _rules(Table(data, colWidths=[62 * mm, 54 * mm, 42 * mm, 12 * mm], spaceAfter=7))
    figure = TheoryFigure(content.example, width)
    caption = Paragraph(f"<b>Figure 1.</b> How to read a theory: {escape(content.example['Plain word description'])}", _STYLES["figure_caption"])

    entries = [(f"{n}. {title}", title) for n, title in content.sections] + [("Credits", "Credits")]
    half = math.ceil(len(entries) / 2)
    page_style = ParagraphStyle("ContentsPage", parent=left, alignment=TA_RIGHT)
    rows = []
    for i in range(half):
        row = []
        for j in (i, i + half):
            if j < len(entries):
                text, title = entries[j]
                row += [Paragraph(_linked(escape(text), title), left), Paragraph(_linked(str(pages.get(title, "")), title), page_style), ""]
        rows.append(row[:5] + [""] * (5 - len(row[:5])))
    contents = Table(rows, colWidths=[70 * mm, 10 * mm, 10 * mm, 70 * mm, 10 * mm])
    contents.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 1.1, INK), ("LINEBELOW", (0, -1), (-1, -1), 1.1, INK), ("TOPPADDING", (0, 0), (-1, -1), 1.2),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6), ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
    return [Paragraph("A round at a glance", _STYLES["title"]), box,
            Paragraph("<b>Table 1.</b> The phases of a round, in order.", _STYLES["caption"]), table,
            figure, caption, KeepTogether([Paragraph("Contents", _STYLES["h2"]), contents])]


def build_story(content: Content, pages: dict[str, int], breaks: set[int] = frozenset()) -> list:
    """``breaks``: figures whose referring paragraph starts a new page (see place_figures)."""
    story: list = [Spacer(1, 1), NextPageTemplate("overview"), PageBreak(), *_overview(content, pages), NextPageTemplate("body"), PageBreak()]
    section = sub = 0
    tables = 1
    numbers = {"figure": 1, "illustration": 0}  # Figure 1 is on the overview page
    placed = 0
    for kind, item in content.body:
        if kind == "h1":
            section, sub = section + 1, 0
            story += [NeedRoom(COLUMN + 90 if item == "Crisis" else 95), _heading("h1", item, str(section), 0)]
        elif kind in numbers:
            path = IMAGES / item
            if path == COVER_IMAGE:  # already on the cover
                continue
            if not path.is_file():
                raise ValueError(f"the rulebook's {kind} {item!r} is not in web/images "
                                 "(nv-rulebook-illustrations makes the pictures of the game's screens)")
            numbers[kind] += 1
            label = f"{kind.capitalize()} {numbers[kind]}"
            if path == CRISIS_IMAGE:  # a photo with the Crisis numbers, in the column
                story += crisis_figure(content, label)
                continue
            placed += 1
            figure = PageFigure(path, placed, label)
            story[-1:-1] = [PageBreak()] * (placed in breaks) + [FigureStart(figure)]  # before the referring paragraph
            if kind == "figure":  # an illustration is only placed, not referred to
                story.append(Paragraph(f"See {label}.", _STYLES["see_figure"]))
            story.append(FigureAnchor(figure))
        elif kind == "h2":
            sub += 1
            icon = f' <img src="{ICONS / "fire.png"}" width="13" height="13" valign="-2"/>' if item == "Hot topic" else ""
            story += [NeedRoom(62), _heading("h2", item, f"{section}.{sub}", 1, icon)]
        elif kind == "note":
            story.append(note_box(*item))
        elif kind == "table":
            tables += 1
            caption = Paragraph(f"<b>Table {tables}.</b> {_TABLE_CAPTIONS[item]}", _STYLES["caption"])
            story.append(KeepTogether([caption, column_table(item, content.settings), Spacer(1, 7)]))
        elif kind == "label":
            story.append(Paragraph(_inline(item), _STYLES["label"]))
        elif kind.startswith("bullet"):
            story.append(Paragraph(_inline(item), _STYLES[kind], bulletText="•" if kind == "bullet0" else "–"))
        else:
            story.append(Paragraph(_inline(item), _BODY))
    story += [NeedRoom(95), _heading("h1", "Credits", None, 0)]
    names = [item for kind, item in content.credits if kind == "bullet0" and len(item.split()) <= 3 and "http" not in item]
    for kind, item in content.credits:
        if kind == "bullet0" and item in names:  # a list of short names reads better as one line
            if item == names[0]:
                story.append(Paragraph(_inline(", ".join(names)), _STYLES["credits"]))
        elif kind == "h2":
            story.append(Paragraph(escape(item), _STYLES["label"]))
        elif kind.startswith("bullet"):
            story.append(Paragraph(_inline(item), ParagraphStyle("c", parent=_STYLES["credits"], leftIndent=8, bulletIndent=1, bulletFontName=_SERIF), bulletText="•"))
        else:
            story.append(Paragraph(_inline(item), _STYLES["credits"]))
    return story


def lay_out(content: Content, known_pages: dict[str, int], plan: dict[int, int], breaks: set[int], target,
            scales: dict[int, float] | None = None) -> _Issue:
    story = build_story(content, known_pages, breaks)
    figures = {f.figure.number: f.figure for f in story if type(f) is FigureAnchor}
    for n, scale in (scales or {}).items():
        figures[n].scale = scale
    doc = _Issue(target, content, known_pages, figures, plan)
    doc.build(story)
    return doc


def place_figures(content: Content) -> tuple[dict[int, int], set[int], dict[int, float], dict[str, int]]:
    """Each figure (and illustration) goes on a page with the paragraph that refers to it: the
    paragraph before its marker in the rulebook. Placing figures moves the text, so the layout is repeated, each figure
    moved to the nearest such page of the last layout, until nothing has to move. A figure that
    pushes its whole paragraph to the next page (and without which the paragraph moves back) is
    shrunk until the paragraph stays (two columns lose its height each); when that would leave
    less than MIN_FIGURE_SCALE, the paragraph starts the next page and the figure goes there too.
    Returns (figure number -> page, the figures with such a page break, figure number -> scale,
    the page of each section)."""
    plan: dict[int, int] = {}
    breaks: set[int] = set()
    scales: dict[int, float] = {}
    moves: set[tuple[int, int, int]] = set()  # (figure, planned page, page it had to move to)
    doc = None
    for _ in range(MAX_LAYOUTS):
        doc = lay_out(content, {}, plan, breaks, io.BytesIO(), scales)
        wrong = {n for n, end in doc.anchor_pages.items() if not doc.start_pages[n] <= plan.get(n, 0) <= end}
        if not wrong:
            break
        for n in sorted(wrong):
            start, end, planned = doc.start_pages[n], doc.anchor_pages[n], plan.get(n)
            page = end if planned is None or planned > end else start
            plan[n] = page
            if planned is None:
                continue
            if (n, page, planned) in moves and page < planned:  # back and forth; now without it on its page
                figure = doc.figures[n]
                fits = doc.anchor_room[n] / 2 / 1.1 - figure.caption_height() - FIGURE_GAP  # with some slack
                scale = min(fits / (figure.size()[1] / figure.scale), scales.get(n, 1.0) * 0.85)
                if scale >= MIN_FIGURE_SCALE:
                    scales[n] = scale
                else:
                    breaks.add(n)
                    scales.pop(n, None)
                    plan[n] = planned
            moves.add((n, planned, page))
    else:
        labels = ", ".join(doc.figures[n].label for n in sorted(wrong))
        print(f"warning: {labels}: not on a page with the text that refers to them", file=sys.stderr)
    return plan, breaks, scales, doc.found_pages


def make_pdf(out: Path = DEFAULT_OUT, rulebook: Path = RULEBOOK) -> Path:
    """Write the filled-in rulebook to ``out``, using the defaults in parameter_defaults.yaml."""
    _register_fonts()
    settings = load_settings().model_dump()
    filled = fill_rulebook(read_markdown(rulebook), settings)
    check_printable(filled)
    content = read_content(filled, settings)
    plan, breaks, scales, pages = place_figures(content)  # the passes also find the page of each section
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lay_out(content, pages, plan, breaks, str(out), scales)
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

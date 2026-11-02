import csv
import io
import re
from decimal import Decimal
from xml.sax.saxutils import escape

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table as RLTable, TableStyle

WEIGHTS = {"text": 2.4, "date": 1.1, "money": 1.25, "price": 1.0, "qty": 0.9, "num": 0.8, "pct": 0.8}
RIGHT = {"money", "price", "qty", "num", "pct"}
INK, MUTED, LINE, TINT = colors.HexColor("#121b16"), colors.HexColor("#5f6b65"), colors.HexColor("#e2e7e3"), colors.HexColor("#f4f5f4")


def fmt(value, kind, symbol="$"):
    if value is None or value == "":
        return ""
    if isinstance(value, str):      # labels like "Total" in a date or money column
        return value
    if kind == "date":
        return value.strftime("%b %d, %Y")
    if kind in RIGHT:
        n = Decimal(value)
        if kind == "money":
            return f"{'-' if n < 0 else ''}{symbol}{abs(n):,.2f}"
        if kind == "price":
            return f"{symbol}{n:,.3f}"
        if kind == "qty":
            return f"{n:,.1f}"
        if kind == "num":
            return f"{int(n):,}"
        return f"{n:.1f}%"
    return str(value)


# ---------------------------------------------------------------- PDF

def _styles(accent):
    base = dict(fontName="Helvetica", fontSize=8, leading=10, textColor=INK)
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=INK),
        "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=10, leading=14, textColor=MUTED),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11, leading=14, spaceBefore=16, spaceAfter=6, textColor=accent, keepWithNext=1),
        "td": ParagraphStyle("td", **base),
        "td_r": ParagraphStyle("td_r", alignment=TA_RIGHT, **base),
        "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white),
        "th_r": ParagraphStyle("th_r", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white, alignment=TA_RIGHT),
        "kpi_l": ParagraphStyle("kpi_l", fontName="Helvetica", fontSize=7.5, leading=10, textColor=MUTED),
        "kpi_v": ParagraphStyle("kpi_v", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=INK),
        "note": ParagraphStyle("note", fontName="Helvetica-Oblique", fontSize=8, leading=11, textColor=MUTED, spaceBefore=4),
    }


def _kpi_row(report, doc_width, styles):
    cells = [[Paragraph(escape(label.upper()), styles["kpi_l"]), Paragraph(escape(fmt(value, kind, report.symbol) or "n/a"), styles["kpi_v"])]
             for label, value, kind in report.kpis]
    t = RLTable([cells], colWidths=[doc_width / len(cells)] * len(cells))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TINT), ("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def _table(tbl, symbol, doc_width, styles, accent):
    weights = [WEIGHTS[k] for _, k in tbl.columns]
    widths = [doc_width * w / sum(weights) for w in weights]
    cls = lambda kind, base: styles[f"{base}_r"] if kind in RIGHT else styles[base]
    data = [[Paragraph(escape(h), cls(k, "th")) for h, k in tbl.columns]]
    for row in tbl.rows:
        data.append([Paragraph(escape(fmt(v, k, symbol)), cls(k, "td")) for v, (_, k) in zip(row, tbl.columns)])
    if tbl.totals:
        data.append([Paragraph(f"<b>{escape(fmt(v, k, symbol))}</b>", cls(k, "td")) for v, (_, k) in zip(tbl.totals, tbl.columns)])
    t = RLTable(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), accent), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, TINT]), ("LINEBELOW", (0, 1), (-1, -1), 0.25, LINE),
    ]
    if tbl.totals:
        style += [("LINEABOVE", (0, -1), (-1, -1), 1, accent), ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eaf2ec"))]
    t.setStyle(TableStyle(style))
    return t


def _chart(chart, width, accent):
    d = Drawing(width, 160)
    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 48, 30, width - 64, 100
    bc.data = [[float(v) for v in values] for _, values in chart["series"]]
    bc.categoryAxis.categoryNames = chart["labels"]
    bc.categoryAxis.labels.fontSize = 7
    if len(chart["labels"]) > 8:
        bc.categoryAxis.labels.angle, bc.categoryAxis.labels.boxAnchor, bc.categoryAxis.labels.dy = 35, "ne", -3
    bc.valueAxis.labels.fontSize = 7
    bc.valueAxis.valueMin = 0
    bc.valueAxis.strokeColor = LINE
    bc.valueAxis.gridStrokeColor = LINE
    bc.valueAxis.visibleGrid = True
    bc.bars[0].fillColor = accent
    bc.bars[1].fillColor = colors.HexColor("#9aa6a0")
    bc.groupSpacing, bc.barSpacing = 6, 1
    d.add(bc)
    x = 48
    for (name, _), fill in zip(chart["series"], (accent, colors.HexColor("#9aa6a0"))):
        d.add(Rect(x, 148, 8, 8, fillColor=fill, strokeColor=None))
        d.add(String(x + 12, 148, name, fontSize=8, fillColor=MUTED))
        x += 80
    return d


def _header(c, doc, brand, accent, logo):
    w, h = doc.pagesize
    left, right = doc.leftMargin, w - doc.rightMargin
    x = left
    if logo:
        iw, ih = logo.getSize()
        lh = 0.55 * inch
        lw = min(lh * iw / ih, 1.8 * inch)
        c.drawImage(logo, left, h - 0.5 * inch - lh, width=lw, height=lh, preserveAspectRatio=True, mask="auto", anchor="sw")
        x = left + lw + 10
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x, h - 0.72 * inch, (brand.business_name or "Expense Tracker")[:60])
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    lines = [ln.strip() for ln in (brand.address or "").splitlines() if ln.strip()][:2]
    contact = " · ".join(v for v in (brand.phone, brand.email) if v)
    if contact:
        lines.append(contact)
    y = h - 0.88 * inch
    for ln in lines[:3]:
        c.drawString(x, y, ln[:95])
        y -= 10
    c.setStrokeColor(accent)
    c.setLineWidth(1.5)
    c.line(left, h - 1.08 * inch, right, h - 1.08 * inch)


def _numbered(brand):
    generated = timezone.localtime().strftime("%b %d, %Y %I:%M %p")

    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._states = []

        def showPage(self):
            self._states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._states)
            for state in self._states:
                self.__dict__.update(state)
                self._footer(total)
                super().showPage()
            super().save()

        def _footer(self, total):
            w, _ = self._pagesize
            self.setStrokeColor(LINE)
            self.setLineWidth(0.5)
            self.line(0.6 * inch, 0.6 * inch, w - 0.6 * inch, 0.6 * inch)
            self.setFont("Helvetica", 7.5)
            self.setFillColor(MUTED)
            self.drawString(0.6 * inch, 0.42 * inch, (brand.footer_text or "")[:110])
            self.drawRightString(w - 0.6 * inch, 0.42 * inch, f"Generated {generated} · Page {self._pageNumber} of {total}")

    return NumberedCanvas


def render_pdf(report, brand, logo_bytes=None):
    try:
        accent = colors.HexColor(brand.accent_color or "#166534")
    except ValueError:
        accent = colors.HexColor("#166534")
    pagesize = landscape(letter) if any(len(t.columns) > 7 for t in report.tables) else letter
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=pagesize, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=1.3 * inch, bottomMargin=0.85 * inch,
                            title=report.title, author=brand.business_name or "Expense Tracker")
    s = _styles(accent)
    story = [Paragraph(escape(report.title), s["title"]),
             Paragraph(escape(f"{report.scope_label} · {report.period}"), s["sub"]), Spacer(1, 12)]
    if report.kpis:
        story.append(_kpi_row(report, doc.width, s))
    if report.chart:
        story += [Paragraph("Income and expenses by month", s["h2"]), _chart(report.chart, doc.width, accent)]
    for tbl in report.tables:
        story.append(Paragraph(escape(tbl.title), s["h2"]))
        story.append(_table(tbl, report.symbol, doc.width, s, accent) if tbl.rows else Paragraph("None in this period.", s["note"]))
    for note in report.notes:
        story.append(Paragraph(escape(note), s["note"]))
    logo = ImageReader(io.BytesIO(logo_bytes)) if logo_bytes else None
    draw = lambda c, d: _header(c, d, brand, accent, logo)
    doc.build(story, onFirstPage=draw, onLaterPages=draw, canvasmaker=_numbered(brand))
    return buffer.getvalue()


# ---------------------------------------------------------------- CSV and Excel

def _raw(value, kind):
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value
    if kind == "date":
        return value.isoformat()
    if kind == "money":
        return f"{Decimal(value):.2f}"
    if kind in ("price", "qty"):
        return f"{Decimal(value):.3f}"
    if kind == "pct":
        return f"{Decimal(value):.1f}"
    if kind == "num":
        return int(value)
    return value


def render_csv(report):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerows([[report.title], [report.period], [report.scope_label], []])
    for label, value, kind in report.kpis:
        w.writerow([label, _raw(value, kind)])
    for tbl in report.tables:
        w.writerows([[], [tbl.title], [h for h, _ in tbl.columns]])
        for row in tbl.rows:
            w.writerow([_raw(v, k) for v, (_, k) in zip(row, tbl.columns)])
        if tbl.totals:
            w.writerow([_raw(v, k) for v, (_, k) in zip(tbl.totals, tbl.columns)])
    for note in report.notes:
        w.writerows([[], [note]])
    return out.getvalue().encode("utf-8-sig")        # the BOM makes Excel read accents correctly


XL_FORMATS = {"money": '#,##0.00;[Red]-#,##0.00', "price": "#,##0.000", "qty": "#,##0.0", "num": "#,##0", "pct": '0.0"%"', "date": "yyyy-mm-dd"}


def _xl(value, kind):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    return value if kind in ("date", "text") else float(value)


def render_xlsx(report, accent="#166534"):
    wb = Workbook()
    fill = PatternFill("solid", fgColor=accent.lstrip("#"))
    ws = wb.active
    ws.title = "Summary"
    ws.append([report.title])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([report.period])
    ws.append([report.scope_label])
    ws.append([])
    for label, value, kind in report.kpis:
        ws.append([label, _xl(value, kind)])
        ws.cell(ws.max_row, 2).number_format = XL_FORMATS.get(kind, "General")
        ws.cell(ws.max_row, 1).font = Font(bold=True)
    for note in report.notes:
        ws.append([])
        ws.append([note])
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 18

    used = {"Summary"}
    for tbl in report.tables:
        name = re.sub(r"[\[\]:*?/\\]", "", tbl.title)[:31] or "Sheet"
        base, n = name, 2
        while name in used:
            name, n = f"{base[:28]} {n}", n + 1
        used.add(name)
        sheet = wb.create_sheet(name)
        sheet.append([h for h, _ in tbl.columns])
        for cell in sheet[1]:
            cell.font, cell.fill, cell.alignment = Font(bold=True, color="FFFFFF"), fill, Alignment(horizontal="center")
        rows = list(tbl.rows) + ([tbl.totals] if tbl.totals else [])
        for ri, row in enumerate(rows, start=2):
            sheet.append([_xl(v, k) for v, (_, k) in zip(row, tbl.columns)])
            for ci, (_, kind) in enumerate(tbl.columns, start=1):
                cell = sheet.cell(ri, ci)
                cell.number_format = XL_FORMATS.get(kind, "General")
                if tbl.totals and ri == len(rows) + 1:
                    cell.font = Font(bold=True)
        for ci, (header, _) in enumerate(tbl.columns, start=1):
            longest = max([len(str(header))] + [len(str(sheet.cell(r, ci).value or "")) for r in range(2, min(sheet.max_row, 200) + 1)])
            sheet.column_dimensions[get_column_letter(ci)].width = min(longest + 3, 48)
        sheet.freeze_panes = "A2"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
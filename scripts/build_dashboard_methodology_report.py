from __future__ import annotations

import json
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "tmp" / "dashboard_report_run51.json"
ASSET_DIR = ROOT / "tmp" / "pdfs" / "dashboard_report"
OUTPUT_PATH = ROOT / "output" / "pdf" / "investment_research_dashboard_report.pdf"

INK = colors.HexColor("#102722")
TEAL = colors.HexColor("#087B72")
TEAL_SOFT = colors.HexColor("#DCEDE9")
GOLD = colors.HexColor("#A87312")
RED = colors.HexColor("#A63D40")
GRAY_900 = colors.HexColor("#1C2724")
GRAY_700 = colors.HexColor("#4C5A56")
GRAY_500 = colors.HexColor("#78837F")
GRAY_300 = colors.HexColor("#CBD2CF")
GRAY_150 = colors.HexColor("#E8ECEA")
GRAY_075 = colors.HexColor("#F5F7F6")
WHITE = colors.white


def load_payload() -> dict:
    with DATA_PATH.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def build_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("Title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=27, leading=31, textColor=INK, alignment=TA_LEFT, spaceAfter=9),
        "subtitle": ParagraphStyle("Subtitle", parent=base["Normal"], fontName="Helvetica", fontSize=11, leading=16, textColor=GRAY_700, spaceAfter=12),
        "h1": ParagraphStyle("H1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=INK, spaceBefore=3, spaceAfter=10),
        "h2": ParagraphStyle("H2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=INK, spaceBefore=8, spaceAfter=6),
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.1, leading=13.2, textColor=GRAY_900, spaceAfter=7),
        "small": ParagraphStyle("Small", parent=base["BodyText"], fontName="Helvetica", fontSize=7.4, leading=10.2, textColor=GRAY_700, spaceAfter=4),
        "caption": ParagraphStyle("Caption", parent=base["BodyText"], fontName="Helvetica-Oblique", fontSize=7.2, leading=9.5, textColor=GRAY_500, spaceBefore=3, spaceAfter=8),
        "bullet": ParagraphStyle("Bullet", parent=base["BodyText"], fontName="Helvetica", fontSize=8.9, leading=12.8, leftIndent=11, firstLineIndent=-6, bulletIndent=0, textColor=GRAY_900, spaceAfter=5),
        "callout": ParagraphStyle("Callout", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=10, leading=14, textColor=INK, spaceAfter=0),
        "table": ParagraphStyle("TableText", parent=base["BodyText"], fontName="Helvetica", fontSize=7.1, leading=9.2, textColor=GRAY_900),
        "table_head": ParagraphStyle("TableHead", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.2, leading=9.2, textColor=WHITE, alignment=TA_LEFT),
        "kpi_label": ParagraphStyle("KpiLabel", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=6.5, leading=8, textColor=GRAY_700, alignment=TA_CENTER),
        "kpi_value": ParagraphStyle("KpiValue", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=INK, alignment=TA_CENTER),
    }


def p(text: str, style) -> Paragraph:
    return Paragraph(text, style)


def bullet(text: str, styles) -> Paragraph:
    return Paragraph(f"- {text}", styles["bullet"])


def section_label(text: str, styles) -> Table:
    table = Table([[p(text.upper(), styles["small"])]], colWidths=[42 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TEAL_SOFT), ("TEXTCOLOR", (0, 0), (-1, -1), TEAL),
        ("BOX", (0, 0), (-1, -1), 0.5, TEAL), ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def callout(text: str, styles, accent=TEAL) -> Table:
    table = Table([[p(text, styles["callout"])]], colWidths=[171 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GRAY_075), ("LINEBEFORE", (0, 0), (0, -1), 4, accent),
        ("BOX", (0, 0), (-1, -1), 0.4, GRAY_300), ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return table


def kpi_strip(summary: dict, styles) -> Table:
    cells = [
        ("UNIVERSE", f"{summary['universe_count']}", "companies"),
        ("EXTRACTED", f"{summary['companies_with_records']}/{summary['universe_count']}", "with records"),
        ("MODEL READY", f"{summary['sector_model_ready_count']}", "sector model"),
        ("AVG COVERAGE", f"{summary['average_score_coverage'] * 100:.1f}%", "weighted evidence"),
        ("ACTIONABLE", f"{summary['actionable_source_issues']}", "source issues"),
    ]
    data = [
        [p(label, styles["kpi_label"]) for label, _, _ in cells],
        [p(value, styles["kpi_value"]) for _, value, _ in cells],
        [p(note, styles["kpi_label"]) for _, _, note in cells],
    ]
    table = Table(data, colWidths=[34.2 * mm] * 5, rowHeights=[7 * mm, 9 * mm, 7 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WHITE), ("BOX", (0, 0), (-1, -1), 0.6, GRAY_300),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, GRAY_300), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return table


def horizontal_bars(items, width=470, height=200, max_value=100, value_suffix="%") -> Drawing:
    drawing = Drawing(width, height)
    left, right, top = 125, 42, 18
    row_height = (height - top - 10) / max(1, len(items))
    bar_width = width - left - right
    for index, (label, value, color) in enumerate(items):
        y = height - top - (index + 1) * row_height + row_height * 0.27
        drawing.add(String(0, y + 2, label, fontName="Helvetica", fontSize=7.5, fillColor=GRAY_700))
        drawing.add(Rect(left, y, bar_width, 7, fillColor=GRAY_150, strokeColor=None))
        fill = max(0, min(bar_width, bar_width * float(value) / max_value))
        drawing.add(Rect(left, y, fill, 7, fillColor=color, strokeColor=None))
        drawing.add(String(left + bar_width + 6, y + 1, f"{value:g}{value_suffix}", fontName="Helvetica-Bold", fontSize=7.3, fillColor=INK))
    return drawing


def stacked_quality_bar(summary: dict) -> Drawing:
    width, height = 470, 76
    drawing = Drawing(width, height)
    total = summary["source_records"]
    ready = summary["ready_source_records"]
    unavailable = summary["failed_source_records"]
    documented = total - ready - unavailable
    segments = [("Ready", ready, TEAL), ("Documented substitution / N.A.", documented, GOLD), ("Provider unavailable", unavailable, RED)]
    cursor, y = 0, 39
    for _, value, color in segments:
        segment_width = width * value / total
        drawing.add(Rect(cursor, y, segment_width, 13, fillColor=color, strokeColor=WHITE, strokeWidth=0.4))
        cursor += segment_width
    cursor = 0
    for label, value, color in segments:
        drawing.add(Rect(cursor, 12, 8, 8, fillColor=color, strokeColor=None))
        drawing.add(String(cursor + 12, 12, f"{label}: {value:,}", fontName="Helvetica", fontSize=7.3, fillColor=GRAY_700))
        cursor += 155
    drawing.add(String(0, 59, f"{total:,} persisted source records", fontName="Helvetica-Bold", fontSize=8, fillColor=INK))
    return drawing


def pipeline_table(styles) -> Table:
    data = [[
        p("1. Universe", styles["table_head"]), p("2. Capture", styles["table_head"]),
        p("3. Normalize", styles["table_head"]), p("4. Score", styles["table_head"]),
        p("5. Review", styles["table_head"]),
    ], [
        p("120 frozen candidates<br/>6 sectors x 20", styles["table"]),
        p("Authenticated browser pages plus Polygon market data", styles["table"]),
        p("Provider-specific pages become semantic records", styles["table"]),
        p("Evidence signals become 0-100 factors and coverage", styles["table"]),
        p("Sector rank, comparison, detail ledger, and retry controls", styles["table"]),
    ]]
    table = Table(data, colWidths=[34.2 * mm] * 5, rowHeights=[9 * mm, 28 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK), ("BACKGROUND", (0, 1), (-1, 1), GRAY_075),
        ("BOX", (0, 0), (-1, -1), 0.6, GRAY_300), ("INNERGRID", (0, 0), (-1, -1), 0.35, GRAY_300),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def styled_table(data, widths, styles, header=True) -> Table:
    rendered = []
    for row_index, row in enumerate(data):
        style = styles["table_head"] if header and row_index == 0 else styles["table"]
        rendered.append([p(str(value), style) for value in row])
    table = Table(rendered, colWidths=widths, repeatRows=1 if header else 0)
    commands = [
        ("BOX", (0, 0), (-1, -1), 0.5, GRAY_300), ("INNERGRID", (0, 0), (-1, -1), 0.3, GRAY_300),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), INK))
    for row_index in range(1 if header else 0, len(data)):
        if row_index % 2 == 0:
            commands.append(("BACKGROUND", (0, row_index), (-1, row_index), GRAY_075))
    table.setStyle(TableStyle(commands))
    return table


def screenshot(path: Path, width_mm=171) -> Image:
    image = Image(str(path))
    ratio = image.imageHeight / image.imageWidth
    image.drawWidth = width_mm * mm
    image.drawHeight = width_mm * mm * ratio
    return image


class DashboardReportDoc(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs):
        super().__init__(filename, **kwargs)
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates(PageTemplate(id="report", frames=[frame], onPage=self._decorate))

    def _decorate(self, canvas, doc):
        page_width, page_height = A4
        canvas.saveState()
        if doc.page > 1:
            canvas.setFillColor(INK)
            canvas.rect(0, page_height - 13 * mm, page_width, 13 * mm, fill=1, stroke=0)
            canvas.setFillColor(WHITE)
            canvas.setFont("Helvetica-Bold", 7.5)
            canvas.drawString(20 * mm, page_height - 8.2 * mm, "MEIRI STRATEGIC CONSULTING | INVESTMENT RESEARCH DASHBOARD")
            canvas.setFillColor(GRAY_500)
            canvas.setFont("Helvetica", 7)
            canvas.drawString(20 * mm, 10 * mm, "Methodology and operating guide | Run 51 snapshot: 1 Aug 2026")
            canvas.drawRightString(page_width - 20 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()


def build_report(payload: dict) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    styles = build_styles()
    summary = payload["summary"]
    methodology = payload["methodology"]
    sectors = payload["sectors"]
    companies = payload["companies"]
    doc = DashboardReportDoc(
        str(OUTPUT_PATH), pagesize=A4, leftMargin=20 * mm, rightMargin=19 * mm,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title="Investment Research Dashboard - Purpose and Methodology",
        author="Meiri Strategic Consulting", subject="Investment research dashboard methodology and operating guide",
    )
    story = []

    story.extend([
        Spacer(1, 14 * mm), section_label("Research system report", styles), Spacer(1, 8 * mm),
        p("Investment Research Dashboard", styles["title"]),
        p("Purpose, evidence architecture, scoring methodology, data-quality controls, and operating workflow", styles["subtitle"]),
        Spacer(1, 5 * mm),
        callout("A decision-support screen for prioritizing deeper equity research across a global, six-sector universe. It is not an automated buy list, valuation opinion, or portfolio-allocation engine.", styles),
        Spacer(1, 12 * mm), kpi_strip(summary, styles), Spacer(1, 11 * mm),
        p("Report scope", styles["h2"]),
        p("This report documents the dashboard developed for a 3-5 year, ILS-base global equity research process. It describes the reusable system and uses Run 51 as the operating example. Current-run metrics are dated 1 August 2026 and will change when sources are refreshed or the universe is replaced.", styles["body"]),
        Spacer(1, 13 * mm), p("Prepared for: Yoav Meiri", styles["body"]),
        p("Prepared by: Meiri Strategic Consulting", styles["body"]),
        p("Research horizon: 3-5 years | Base currency: ILS | Objective: total-return screening", styles["small"]),
        Spacer(1, 20 * mm),
        p("Important: Research process documentation only. The dashboard does not provide personalized investment advice and does not guarantee loss limits or future returns.", styles["caption"]),
        PageBreak(),
    ])

    story.extend([
        p("Executive Summary", styles["h1"]),
        bullet("<b>Purpose.</b> Convert a broad global equity universe into a transparent, evidence-ranked research queue, while preserving the source records needed to challenge every score.", styles),
        bullet("<b>Current operating state.</b> Run 51 contains 120 companies, all with source records; 118 are sector-model ready, weighted evidence coverage averages 97.18%, and no actionable extraction failures remain.", styles),
        bullet("<b>Method.</b> Paid-source evidence from Seeking Alpha, Zacks, and InvestingPro is normalized with Polygon market data into eight factor categories. Scores are coverage-aware and ranks are primarily interpreted within sector.", styles),
        bullet("<b>Boundary.</b> Sector models remain provisional and unbacktested. Moat and pricing power are inferred from measurable evidence, not supplied as authoritative provider ratings. A high rank means <i>research first</i>, not <i>buy</i>.", styles),
        Spacer(1, 4 * mm), p("The dashboard is ready for screening, not autonomous allocation", styles["h2"]),
        p("Its strongest contribution is disciplined triage: it makes source completeness visible, applies consistent scoring rules, distinguishes provider absence from engineering failures, and gives the user a direct path from sector rank to raw evidence. The next maturity step is validation against historical outcomes and sector-specific fundamental drivers.", styles["body"]),
        screenshot(ASSET_DIR / "dashboard_overview.png"),
        p("Figure 1. Guided review presents the run status and explains how to interpret ranking before exposing the full universe.", styles["caption"]),
        p("Recommended use", styles["h2"]),
        bullet("Use sector rank and coverage to create a diligence queue, then inspect the company detail and source ledger.", styles),
        bullet("Compare candidates within the same sector before making cross-sector judgments.", styles),
        bullet("Treat the dashboard as one input alongside valuation work, primary filings, macro scenarios, tax, currency exposure, and position sizing.", styles),
        PageBreak(),
    ])

    story.extend([
        p("A Research Funnel, Not a Recommendation Engine", styles["h1"]),
        p("The system addresses a practical problem: a large research universe creates inconsistent attention. The dashboard standardizes what gets collected, how evidence is compared, and which gaps must be resolved before ranking is trusted.", styles["body"]),
        pipeline_table(styles), Spacer(1, 5 * mm),
        p("The five user decisions", styles["h2"]),
        styled_table([
            ["Decision", "Dashboard answer", "Required user judgment"],
            ["Can this run be used?", "Extraction, model readiness, coverage, and issue counts", "Whether evidence quality is adequate for the intended decision"],
            ["Where should research start?", "Sector rank, percentile, and top-three lists", "Whether the sector model reflects the company economics"],
            ["Why did a company rank there?", "Eight factor scores and scored evidence", "Whether the evidence is economically meaningful and current"],
            ["Do providers agree?", "Provider highlights and consensus factor", "Whether signals are independent or correlated"],
            ["What is missing?", "Source ledger and quality taxonomy", "Whether missing evidence changes the thesis or only lowers convenience"],
        ], [35 * mm, 67 * mm, 69 * mm], styles),
        Spacer(1, 6 * mm),
        callout("Interpretation rule: read sector rank first, coverage second, factor evidence third, and provider source pages last. Never reverse that order by treating one provider grade as the conclusion.", styles, accent=GOLD),
        p("Interface structure", styles["h2"]),
        bullet("<b>Walk me through:</b> guided interpretation for first-time and periodic users.", styles),
        bullet("<b>Universe:</b> sortable and filterable research queue with company detail inspection.", styles),
        bullet("<b>Compare:</b> side-by-side factor comparison for up to six selected companies.", styles),
        bullet("<b>Data quality:</b> source status, sector progress, retry controls, and provider-absence explanations.", styles),
        PageBreak(),
    ])

    story.extend([
        p("Four Source Families Become One Evidence Model", styles["h1"]),
        p("The extractor does not scrape a single summary number. It captures page-specific evidence, identifies its semantic type, and stores one auditable record per ticker, provider, and data type. Provider data is complementary, not interchangeable.", styles["body"]),
        styled_table([
            ["Source", "Primary role in the dashboard", "Examples of normalized evidence"],
            ["Seeking Alpha", "Factor and analyst context", "Quant, author and sell-side ratings; valuation, growth, profitability and momentum grades; estimates, revisions, peers, income and cash-flow statements"],
            ["Zacks", "Rank, style, target and estimate context", "Zacks Rank, price target, Value/Growth/Momentum/VGM Style Scores, industry rank, ESP, estimate tables, revisions and surprise history when supplied"],
            ["InvestingPro", "Valuation, financial quality and peer context", "Fair value, financial health, company-versus-industry ratios, annual financial history, consensus forecasts, cash flow and ownership"],
            ["Polygon", "Independent market-data anchor", "Previous close used to anchor dated market comparisons"],
        ], [30 * mm, 50 * mm, 91 * mm], styles),
        p("ADR and OTC handling", styles["h2"]),
        p("The universe prioritizes the tradable New York ADR or US ticker where available. Zacks detailed-estimate pages are attempted first because they can contain richer estimate and revision tables. When that page is blocked for an ADR/OTC symbol, the extractor retries the working price-target and forecast route and captures only the fields visibly supplied there: rank, target, style scores, and industry rank. Missing estimate tables remain documented as unavailable and are not imputed.", styles["body"]),
        p("Record lifecycle", styles["h2"]),
        styled_table([
            ["State", "Meaning", "Effect on scoring and workflow"],
            ["Ready", "Page parsed and semantic evidence persisted", "Eligible evidence can contribute to factors"],
            ["Not applicable / substituted", "Requested field set does not apply or a narrower fallback was used", "No invented data; available fallback fields live in their real semantic records"],
            ["Provider does not supply", "Explicit rating absence, ticker search redirect, or genuine page 404", "Non-retryable unless provider coverage changes"],
            ["Access blocked", "Authentication, 403, anti-bot or verification page", "Retry after confirming paid-source session"],
            ["Parser gap", "Normal page loaded but structured evidence was not recognized", "Engineering follow-up and targeted retry"],
            ["Temporary", "Timeout, maintenance, or transient availability problem", "Targeted retry without replacing successful records"],
        ], [35 * mm, 62 * mm, 74 * mm], styles),
        PageBreak(),
    ])

    weights = methodology["category_weights"]
    label_map = {
        "valuation": "Valuation", "moat_evidence": "Moat evidence", "fcf_quality": "FCF quality",
        "growth_revisions": "Growth & revisions", "pricing_power": "Pricing power",
        "downside_quality": "Downside quality", "cross_source_consensus": "Cross-source consensus",
        "momentum": "Momentum",
    }
    story.extend([
        p("The Generic Score Rewards Evidence, Not Missing Data", styles["h1"]),
        p("Each factor converts a set of observable signals to a 0-100 scale. A factor contributes only when its minimum evidence threshold is met. The composite is a weighted average of sufficient factors; missing categories are excluded and exposed through coverage rather than filled with neutral assumptions.", styles["body"]),
        horizontal_bars([(label_map[key], value, TEAL if value >= 15 else GOLD) for key, value in weights.items()], height=210),
        p("Figure 2. Generic factor weights sum to 100%. Valuation and derived moat evidence receive the highest weights.", styles["caption"]),
        styled_table([
            ["Factor", "What it is designed to measure", "Representative signals"],
            ["Valuation", "Price paid relative to value and peers", "SA valuation grade, Zacks Value style, InvestingPro fair-value upside, P/E, P/FCF and EV/EBITDA versus industry"],
            ["Moat evidence", "Observable durability and economic quality", "Profitability grade, ROE/ROA/ROI versus industry, gross/EBIT/FCF margin premiums"],
            ["FCF quality", "Cash-generation strength and persistence", "Levered FCF margin, positive annual FCF persistence, recent versus earlier median FCF"],
            ["Growth & revisions", "Growth quality and direction of expectations", "SA growth grade, Zacks Growth style, 3-month EPS and revenue revision breadth"],
            ["Pricing power", "Ability to preserve or expand economics", "Gross-margin premium, stability versus five-year average, margin change versus history"],
            ["Downside quality", "Financial resilience and risk sensitivity", "Financial-health label, beta, debt-to-equity versus industry"],
            ["Consensus", "Direction across normalized provider signals", "SA ratings, InvestingPro forecast, Zacks Rank"],
            ["Momentum", "Current factor momentum", "SA momentum grade; not a full technical-analysis model"],
        ], [30 * mm, 57 * mm, 84 * mm], styles),
        Spacer(1, 5 * mm),
        callout("Rank eligibility requires at least 70% weighted coverage and at least six sufficient categories. Coverage is therefore a model input, not a decorative confidence label.", styles),
        PageBreak(),
    ])

    sector_model = methodology["sector_model"]
    sector_rows = [["Sector", "Val.", "Moat", "FCF", "Growth", "Pricing", "Downside", "Consensus", "Mom."]]
    for sector in ["Consumer Staples", "Energy", "Healthcare", "Industrials", "Materials", "Utilities"]:
        w = sector_model["weights"][sector]
        sector_rows.append([sector, w["valuation"], w["moat_evidence"], w["fcf_quality"], w["growth_revisions"], w["pricing_power"], w["downside_quality"], w["cross_source_consensus"], w["momentum"]])
    story.extend([
        p("Sector Ranking Changes the Economic Emphasis", styles["h1"]),
        p("The generic score supports broad consistency, but the dashboard's primary ranking is sector-specific. Each sector model reweights the same validated factor scores to better reflect its economics. Companies are ranked only against eligible peers in the same sector.", styles["body"]),
        styled_table(sector_rows, [36 * mm] + [16.9 * mm] * 8, styles),
        p("Table 1. Sector-model weights, percent. Zero means the generic factor is intentionally excluded for that sector model.", styles["caption"]),
        p("Why the weights differ", styles["h2"]),
        bullet("<b>Energy and Materials:</b> emphasize FCF and downside quality; generic pricing power is excluded because commodity economics require reserve and cost-curve context.", styles),
        bullet("<b>Consumer Staples:</b> retains moat, FCF and pricing power as central durability signals.", styles),
        bullet("<b>Healthcare:</b> gives growth and revisions the largest weight, while recognizing that patent and pipeline risk are not yet modeled.", styles),
        bullet("<b>Industrials:</b> balances moat, growth and cash generation but does not yet model backlog or cycle quality.", styles),
        bullet("<b>Utilities:</b> emphasizes downside quality and excludes generic FCF and pricing power because regulated funding and rate-base economics need a dedicated model.", styles),
        p("Current cohort readiness", styles["h2"]),
        horizontal_bars([(sector["sector"], sector["sector_model_ready"] / sector["companies"] * 100, TEAL) for sector in sectors], height=155),
        p("Figure 3. Sector-model readiness is 95%-100% across all six 20-company cohorts.", styles["caption"]),
        callout("These sector models are provisional sensitivity frameworks, not backtested alpha models. Their value today is consistency and transparency; predictive validity remains an open research question.", styles, accent=GOLD),
        PageBreak(),
    ])

    story.extend([
        p("Data Quality Is a First-Class Dashboard Output", styles["h1"]),
        p("Source issues are classified by cause because the next action differs. A provider absence should not be repeatedly retried, while a parser gap or temporary failure should. Successful records remain persisted during retries, so recovery work does not erase prior evidence.", styles["body"]),
        stacked_quality_bar(summary),
        p("Figure 4. Run 51 record status. Documented substitutions and not-applicable records are separated from ready evidence and true provider absence.", styles["caption"]),
        screenshot(ASSET_DIR / "dashboard_quality.png"),
        p("Figure 5. Data-quality view after the Zacks ADR fallback correction: no blocked, parser, temporary, or unextracted cases remain.", styles["caption"]),
        p("Current provider absences", styles["h2"]),
        styled_table([
            ["Cause", "Requested pages", "Interpretation"],
            ["Seeking Alpha rating unavailable", summary["provider_absence_breakdown"]["sa_rating_not_supplied"], "The provider explicitly does not publish the requested rating for that security"],
            ["Zacks ticker redirects to search", summary["provider_absence_breakdown"]["zacks_ticker_not_supported"], "The requested quote or forecast product is not supported for the ticker"],
            ["InvestingPro page returns 404", summary["provider_absence_breakdown"]["investing_page_not_found"], "The requested ownership page does not exist for that instrument"],
        ], [48 * mm, 28 * mm, 95 * mm], styles),
        Spacer(1, 5 * mm),
        p("The remaining 14 issues are page-level requests, not 14 unresearched companies. All 120 companies retain source records, and the unavailable pages remain visible in the ledger so users can judge whether the missing provider product matters.", styles["body"]),
        PageBreak(),
    ])

    top_by_sector = []
    for sector in ["Consumer Staples", "Energy", "Healthcare", "Industrials", "Materials", "Utilities"]:
        ranked = sorted([company for company in companies if company["sector"] == sector and company.get("sector_model_rank")], key=lambda company: company["sector_model_rank"])[:3]
        for index, company in enumerate(ranked):
            top_by_sector.append([
                sector if index == 0 else "", company["ticker"], f"#{company['sector_model_rank']}",
                f"{company['sector_model_score']:.1f}", f"{company['sector_model_coverage'] * 100:.0f}%",
                f"{company['sector_model_percentile']:.1f}%",
            ])
    story.extend([
        p("Run 51 Produces a Diligence Queue", styles["h1"]),
        p("The table below is included to demonstrate dashboard output, not to make recommendations. These names lead their current sector cohorts under the provisional model and should therefore receive earlier evidence review and valuation work.", styles["body"]),
        styled_table([["Sector", "Ticker", "Rank", "Score", "Coverage", "Percentile"]] + top_by_sector, [43 * mm, 25 * mm, 19 * mm, 25 * mm, 28 * mm, 31 * mm], styles),
        p("Table 2. Top three by provisional sector-model score, Run 51 snapshot. Scores are not expected returns or price targets.", styles["caption"]),
        p("How to use this queue", styles["h2"]),
        bullet("Open the company and inspect the factor profile for concentration: one exceptional factor should not dominate the decision.", styles),
        bullet("Review scored evidence and provider highlights for freshness, agreement, and economic relevance.", styles),
        bullet("Open source-ledger links where the evidence is surprising, missing, or material to the thesis.", styles),
        bullet("Compare the candidate with two to five close sector peers before beginning primary-source diligence.", styles),
        bullet("Move only the surviving candidates into a separate investment memo, valuation model, catalyst calendar, and portfolio-risk process.", styles),
        Spacer(1, 4 * mm),
        callout("A rank is ordinal within the eligible cohort. It does not state that the company is undervalued, that the security will outperform, or that the position fits a 20% maximum-loss constraint.", styles, accent=RED),
        PageBreak(),
    ])

    story.extend([
        p("Recommended Next Steps", styles["h1"]),
        styled_table([
            ["Priority", "Next step", "Why it matters"],
            ["1", "Backtest rank persistence and forward returns", "Measure whether generic and sector ranks add signal over 6, 12, 36, and 60 months, including delisted names and transaction assumptions"],
            ["2", "Add sector-specific operating drivers", "Reserve life, patent cliffs, backlog, price-volume-mix, regulation and funding needs are more causal than generic factors"],
            ["3", "Add valuation and drawdown scenarios", "Translate evidence ranks into bull/base/bear value ranges and test the stated loss constraint"],
            ["4", "Build ILS currency and hedge analysis", "Separate security return from USD/ILS and non-USD currency exposure; define when hedging improves portfolio risk"],
            ["5", "Formalize freshness and change tracking", "Display source age, score deltas, rank changes, revision direction and thesis triggers between runs"],
            ["6", "Add portfolio construction outside the screen", "Control sector, factor, currency, liquidity and single-name concentration after research selection"],
        ], [18 * mm, 62 * mm, 91 * mm], styles),
        p("Further questions", styles["h2"]),
        bullet("Which factor definitions and weights remain stable across regimes, and which are overfit to the current universe?", styles),
        bullet("How should ADR liquidity, withholding tax, domicile, reporting currency and local-listing differences affect ranking?", styles),
        bullet("What freshness threshold should make a score stale enough to suspend ranking?", styles),
        bullet("How should correlated provider signals be de-duplicated so consensus does not become false confidence?", styles),
        bullet("Which portfolio-level hedges reduce ILS investor drawdown without destroying expected total return?", styles),
        p("Caveats and assumptions", styles["h2"]),
        bullet("Provider data may change after extraction and paid-page layouts can change without notice.", styles),
        bullet("The 0-100 transformations are heuristics intended for ranking transparency, not estimates of intrinsic value or probability of success.", styles),
        bullet("Sector scores are sensitive to weights, cohort composition, and missing categories. Current models have not been historically validated.", styles),
        bullet("Moat and pricing power are derived evidence constructs. They are not Morningstar moat ratings or direct management disclosures.", styles),
        bullet("The current dashboard does not yet incorporate Israeli tax treatment, FX hedging cost, execution cost, liquidity limits, or portfolio-level covariance.", styles),
        PageBreak(),
    ])

    story.extend([
        p("Governance and Evidence Map", styles["h1"]),
        p("The dashboard is designed so that methodology, normalized evidence, and operational state remain inspectable. The following artifacts define the current implementation and Run 51 snapshot.", styles["body"]),
        styled_table([
            ["Artifact", "Role"],
            ["Investment scoring module", "Defines factor construction, evidence thresholds, coverage and composite-score logic"],
            ["Sector scoring module", "Defines sector weights, cohort eligibility, percentiles and documented model limitations"],
            ["Rating enrichment and research-metrics modules", "Define source URLs, provider parsers, ADR fallback behavior and semantic records"],
            ["Research API", "Builds the universe, summary, methodology payload, issue taxonomy and targeted retry workflow"],
            ["Research dashboard UI", "Implements guided review, universe filters, comparison, company detail, tooltips and data-quality controls"],
            ["Run 51 database and production_batch_08 export", "Provide the dated 120-company evidence and ranking snapshot used in this report"],
        ], [55 * mm, 116 * mm], styles),
        p("Operational controls", styles["h2"]),
        bullet("Successful evidence is persisted before retries; source recovery is selective by provider and data type.", styles),
        bullet("Bulk extraction can be stopped after the current company without discarding completed records.", styles),
        bullet("Individual companies can be re-extracted, while the existing evidence remains visible until replacement records are saved.", styles),
        bullet("Provider non-coverage remains visible and non-retryable; access, parser and temporary failures are independently actionable.", styles),
        bullet("CSV and JSON exports preserve rankings, category scores, evidence and source-ledger records for offline analysis.", styles),
        Spacer(1, 8 * mm),
        callout("Governance principle: every dashboard number should be traceable to a normalized record, every missing record should have a reason, and every rank should disclose its coverage and cohort.", styles),
        Spacer(1, 13 * mm),
        p("Prepared 1 August 2026 | Run 51 | Dashboard version documented after Zacks ADR forecast-fallback correction", styles["small"]),
        p("This report describes a research workflow and software system. It is not financial advice, a solicitation, or a guarantee of investment performance.", styles["caption"]),
    ])

    doc.build(story)


if __name__ == "__main__":
    build_report(load_payload())
    print(OUTPUT_PATH)

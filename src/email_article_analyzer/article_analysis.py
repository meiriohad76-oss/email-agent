import json
from dataclasses import dataclass
from typing import Any, Protocol

from email_article_analyzer.model_defaults import DEFAULT_EXTRACTION_MODEL
from email_article_analyzer.model_defaults import DEFAULT_REPORT_MODEL
from email_article_analyzer.model_defaults import DEFAULT_SUMMARY_MODEL
from email_article_analyzer.model_defaults import normalize_model_name


@dataclass(frozen=True)
class ArticleAnalysisResult:
    provider: str
    model: str | None
    summary: str
    stance: str
    sentiment: str
    recommendation: str
    confidence: float
    supporting_evidence: list[str]
    mentioned_tickers: list[str]
    price_targets: list[dict[str, Any]]
    rating_snapshots: list[dict[str, Any]]
    actionable_data: list[dict[str, Any]]
    actionable_signals: list[dict[str, Any]]
    raw_response: dict[str, Any]


@dataclass(frozen=True)
class ArticlePrecheckResult:
    provider: str
    model: str | None
    is_relevant: bool
    confidence: float
    tickers: list[str]
    reason: str
    raw_response: dict[str, Any]


@dataclass(frozen=True)
class RunReportSynthesisResult:
    provider: str
    model: str | None
    executive_summary: str
    priority_tickers: list[dict[str, Any]]
    contradictions: list[dict[str, Any]]
    recommended_actions: list[str]
    raw_response: dict[str, Any]


class ArticleAnalyzer(Protocol):
    def analyze_article(
        self,
        url: str,
        source_key: str,
        email_subject: str,
        article_title: str | None,
        article_text: str | None,
        model: str | None,
    ) -> ArticleAnalysisResult:
        pass


class ArticlePrechecker(Protocol):
    def precheck_article(
        self,
        url: str,
        source_key: str,
        email_subject: str,
        article_title: str | None,
        article_text: str | None,
        model: str | None,
    ) -> ArticlePrecheckResult:
        pass


class RunReportSynthesizer(Protocol):
    def synthesize_run(
        self,
        run: dict[str, Any],
        articles: list[dict[str, Any]],
        ticker_enrichments: list[dict[str, Any]],
        model: str | None,
    ) -> RunReportSynthesisResult:
        pass


ARTICLE_PRECHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "is_relevant": {
            "type": "boolean",
            "description": "True when the content is a stock, ETF, market, or portfolio-relevant article worth full analysis.",
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "tickers": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["is_relevant", "confidence", "tickers", "reason"],
    "additionalProperties": False,
}


ARTICLE_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": (
                "A substantive 130-220 word investor brief. Open with the article's main theme, "
                "then explain its principal arguments, material facts and figures, catalysts, risks, "
                "and the author's conclusion or recommendation. Do not use generic filler."
            ),
        },
        "stance": {
            "type": "string",
            "enum": ["buy_watch", "hold", "sell_watch", "avoid", "unclear"],
        },
        "sentiment": {
            "type": "string",
            "enum": ["strong_bullish", "bullish", "neutral", "bearish", "strong_bearish", "unclear"],
        },
        "recommendation": {
            "type": "string",
            "enum": ["buy", "hold", "sell", "avoid", "watch", "unclear"],
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
        "supporting_evidence": {
            "type": "array",
            "items": {"type": "string"},
        },
        "mentioned_tickers": {
            "type": "array",
            "items": {"type": "string"},
        },
        "price_targets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "target_price": {"type": ["number", "null"]},
                    "currency": {"type": "string"},
                    "timeframe": {"type": "string"},
                    "source_text": {"type": "string"},
                },
                "required": ["ticker", "target_price", "currency", "timeframe", "source_text"],
                "additionalProperties": False,
            },
        },
        "rating_snapshots": {
            "type": "array",
            "description": (
                "Grounded ratings or rank snapshots explicitly present in the article/page text, "
                "including Seeking Alpha Quant, SA Analysts, SA Wall Street, SA price target, "
                "Zacks Rank, and Zacks price target when available."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "provider": {
                        "type": "string",
                        "enum": ["seeking_alpha", "zacks", "other"],
                    },
                    "rating_type": {
                        "type": "string",
                        "enum": [
                            "quant",
                            "analysts",
                            "wall_street",
                            "rank",
                            "price_target",
                            "other",
                        ],
                    },
                    "rating": {"type": "string"},
                    "score": {"type": ["number", "null"]},
                    "price_target": {"type": ["number", "null"]},
                    "currency": {"type": "string"},
                    "source_text": {"type": "string"},
                },
                "required": [
                    "ticker",
                    "provider",
                    "rating_type",
                    "rating",
                    "score",
                    "price_target",
                    "currency",
                    "source_text",
                ],
                "additionalProperties": False,
            },
        },
        "actionable_data": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "theme_summary": {
                        "type": "string",
                        "description": (
                            "Two to four complete sentences explaining the article's main thesis and "
                            "argument for this ticker only."
                        ),
                    },
                    "key_points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Three to five decision-relevant points about this ticker from the article.",
                    },
                    "sentiment": {
                        "type": "string",
                        "enum": [
                            "strong_bullish",
                            "bullish",
                            "neutral",
                            "bearish",
                            "strong_bearish",
                            "unclear",
                        ],
                    },
                    "recommendation": {
                        "type": "string",
                        "enum": ["buy", "hold", "sell", "avoid", "watch", "unclear"],
                    },
                    "source_recommendation_text": {
                        "type": "string",
                        "description": (
                            "A faithful paraphrase of the author's recommendation and rationale. "
                            "State explicitly when the article makes no recommendation."
                        ),
                    },
                    "timeframe": {"type": "string"},
                    "catalysts": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "financial_details": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "investor_actions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "One to three practical research or portfolio-review actions justified by "
                            "the article, with conditions where possible; never invent facts."
                        ),
                    },
                    "follow_up_checks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "One to three concrete metrics, events, dates, or thesis conditions the "
                            "investor should monitor after reading."
                        ),
                    },
                },
                "required": [
                    "ticker",
                    "theme_summary",
                    "key_points",
                    "sentiment",
                    "recommendation",
                    "source_recommendation_text",
                    "timeframe",
                    "catalysts",
                    "risks",
                    "financial_details",
                    "evidence",
                    "investor_actions",
                    "follow_up_checks",
                ],
                "additionalProperties": False,
            },
        },
        "actionable_signals": {
            "type": "array",
            "description": (
                "Specific investor decision signals found in the article. Use this for data points "
                "that should be scanned in a report: valuation, earnings or guidance, revenue or EPS, "
                "margin changes, dividends or income data, analyst revisions, technical levels, "
                "sector or macro drivers, corporate actions, and dated catalysts."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "signal_type": {
                        "type": "string",
                        "enum": [
                            "valuation",
                            "earnings",
                            "guidance",
                            "growth",
                            "margins",
                            "dividend_income",
                            "analyst_revision",
                            "technical_level",
                            "sector_macro",
                            "corporate_action",
                            "event_timing",
                            "risk",
                            "other",
                        ],
                    },
                    "signal": {"type": "string"},
                    "value": {"type": "string"},
                    "direction": {
                        "type": "string",
                        "enum": ["positive", "negative", "mixed", "neutral", "unclear"],
                    },
                    "timeframe": {"type": "string"},
                    "source_text": {"type": "string"},
                },
                "required": [
                    "ticker",
                    "signal_type",
                    "signal",
                    "value",
                    "direction",
                    "timeframe",
                    "source_text",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "summary",
        "stance",
        "sentiment",
        "recommendation",
        "confidence",
        "supporting_evidence",
        "mentioned_tickers",
        "price_targets",
        "rating_snapshots",
        "actionable_data",
        "actionable_signals",
    ],
    "additionalProperties": False,
}


RUN_REPORT_SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {
            "type": "string",
            "description": "Run-level investor summary focused on what changed and what deserves attention first.",
        },
        "priority_tickers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "priority": {"type": "string"},
                    "reason": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["ticker", "priority", "reason", "evidence"],
                "additionalProperties": False,
            },
        },
        "contradictions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "issue": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                },
                "required": ["ticker", "issue", "why_it_matters"],
                "additionalProperties": False,
            },
        },
        "recommended_actions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "executive_summary",
        "priority_tickers",
        "contradictions",
        "recommended_actions",
    ],
    "additionalProperties": False,
}


class OpenAIArticlePrechecker:
    def __init__(self, client):
        self.client = client

    def precheck_article(
        self,
        url: str,
        source_key: str,
        email_subject: str,
        article_title: str | None,
        article_text: str | None,
        model: str | None,
    ) -> ArticlePrecheckResult:
        model = normalize_model_name(model, DEFAULT_EXTRACTION_MODEL)
        response = self.client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Do a fast relevance precheck for a stock-article analyzer. "
                        "Decide whether the supplied email/article content is worth full investor analysis. "
                        "Extract only ticker symbols that are explicitly visible or strongly indicated by the title/text. "
                        "Be conservative and do not infer tickers from vague company names."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Source: {source_key}\n"
                        f"Email headline: {email_subject}\n"
                        f"Article URL: {url}\n"
                        f"Article title: {article_title or 'Unknown'}\n"
                        f"Article text:\n{(article_text or 'No article text extracted.')[:8000]}\n"
                    ),
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "stock_article_precheck",
                    "strict": True,
                    "schema": ARTICLE_PRECHECK_SCHEMA,
                }
            },
        )
        raw_output = getattr(response, "output_text", "")
        payload = json.loads(raw_output)
        return ArticlePrecheckResult(
            provider="openai",
            model=model,
            is_relevant=bool(payload["is_relevant"]),
            confidence=float(payload["confidence"]),
            tickers=list(payload["tickers"]),
            reason=str(payload["reason"]),
            raw_response={"output_text": raw_output},
        )


class OpenAIArticleAnalyzer:
    def __init__(self, client):
        self.client = client

    def analyze_article(
        self,
        url: str,
        source_key: str,
        email_subject: str,
        article_title: str | None,
        article_text: str | None,
        model: str | None,
    ) -> ArticleAnalysisResult:
        model = normalize_model_name(model, DEFAULT_SUMMARY_MODEL)
        response = self.client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Analyze the linked stock-market article for an investor. "
                        "Write a substantive article brief, not a headline-sized synopsis. "
                        "Extract sentiment, recommendation, source ratings/ranks, price targets, catalysts, risks, "
                        "valuation details, guidance, margins, P/E, revenue, EPS, ratings, "
                        "and other actionable data for each materially discussed ticker. For every ticker, "
                        "separate the article's thesis and recommendation from your practical investor research "
                        "actions and follow-up checks. Make actions conditional on the article evidence and identify "
                        "what would confirm or weaken the thesis. If the author gives no explicit recommendation, "
                        "say so rather than inferring one. "
                        "Return only evidence grounded in the article. If confidence "
                        "is above 0.70, include at least 2 supporting evidence items."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Source: {source_key}\n"
                        f"Email headline: {email_subject}\n"
                        f"Article URL: {url}\n"
                        f"Article title: {article_title or 'Unknown'}\n"
                        f"Article text:\n{article_text or 'No article text extracted.'}\n"
                    ),
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "stock_article_analysis",
                    "strict": True,
                    "schema": ARTICLE_ANALYSIS_SCHEMA,
                }
            },
        )
        raw_output = getattr(response, "output_text", "")
        payload = json.loads(raw_output)
        confidence = float(payload["confidence"])
        supporting_evidence = list(payload["supporting_evidence"])
        price_targets = list(payload["price_targets"])
        rating_snapshots = list(payload["rating_snapshots"])
        actionable_data = list(payload["actionable_data"])
        actionable_signals = list(payload["actionable_signals"])
        if confidence > 0.70 and len(supporting_evidence) < 2:
            raise ValueError(
                "Article analysis with confidence above 70% requires at least 2 supporting evidence items"
            )
        raw_response = {
            "output_text": raw_output,
            "sentiment": payload["sentiment"],
            "recommendation": payload["recommendation"],
            "price_targets": price_targets,
            "rating_snapshots": rating_snapshots,
            "actionable_data": actionable_data,
            "actionable_signals": actionable_signals,
        }
        return ArticleAnalysisResult(
            provider="openai",
            model=model,
            summary=str(payload["summary"]),
            stance=str(payload["stance"]),
            sentiment=str(payload["sentiment"]),
            recommendation=str(payload["recommendation"]),
            confidence=confidence,
            supporting_evidence=supporting_evidence,
            mentioned_tickers=list(payload["mentioned_tickers"]),
            price_targets=price_targets,
            rating_snapshots=rating_snapshots,
            actionable_data=actionable_data,
            actionable_signals=actionable_signals,
            raw_response=raw_response,
        )


class OpenAIRunReportSynthesizer:
    def __init__(self, client):
        self.client = client

    def synthesize_run(
        self,
        run: dict[str, Any],
        articles: list[dict[str, Any]],
        ticker_enrichments: list[dict[str, Any]],
        model: str | None,
    ) -> RunReportSynthesisResult:
        model = normalize_model_name(model, DEFAULT_REPORT_MODEL)
        payload = {
            "run": {
                "id": run.get("id"),
                "status": run.get("status"),
                "started_at": run.get("started_at"),
                "completed_at": run.get("completed_at"),
            },
            "articles": _compact_articles_for_synthesis(articles),
            "ticker_enrichments": _compact_enrichments_for_synthesis(ticker_enrichments),
        }
        response = self.client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Synthesize a completed stock-email analysis run for an investor. "
                        "Focus on portfolio-relevant priorities, contradictions across articles and enrichments, "
                        "and concrete next review actions. Use only the supplied data."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, sort_keys=True),
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "stock_run_report_synthesis",
                    "strict": True,
                    "schema": RUN_REPORT_SYNTHESIS_SCHEMA,
                }
            },
        )
        raw_output = getattr(response, "output_text", "")
        parsed = json.loads(raw_output)
        return RunReportSynthesisResult(
            provider="openai",
            model=model,
            executive_summary=str(parsed["executive_summary"]),
            priority_tickers=list(parsed["priority_tickers"]),
            contradictions=list(parsed["contradictions"]),
            recommended_actions=list(parsed["recommended_actions"]),
            raw_response={"output_text": raw_output},
        )


def _compact_articles_for_synthesis(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = []
    for article in articles:
        analysis = article.get("analysis") or {}
        if not analysis:
            continue
        compact.append(
            {
                "title": (article.get("content") or {}).get("title") or article.get("subject"),
                "source_key": article.get("source_key"),
                "url": article.get("normalized_url"),
                "stance": analysis.get("stance"),
                "sentiment": analysis.get("sentiment"),
                "recommendation": analysis.get("recommendation"),
                "confidence": analysis.get("confidence"),
                "summary": analysis.get("summary"),
                "tickers": analysis.get("mentioned_ticker_details") or analysis.get("mentioned_tickers"),
                "evidence": (analysis.get("supporting_evidence") or [])[:3],
                "price_targets": analysis.get("price_targets") or [],
                "actionable_data": analysis.get("actionable_data") or [],
                "actionable_signals": analysis.get("actionable_signals") or [],
            }
        )
    return compact[:40]


def _compact_enrichments_for_synthesis(enrichments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = []
    for enrichment in enrichments:
        compact.append(
            {
                "ticker": enrichment.get("ticker"),
                "provider": enrichment.get("provider"),
                "data_type": enrichment.get("data_type"),
                "status": enrichment.get("status"),
                "failure_reason": enrichment.get("failure_reason"),
                "data": enrichment.get("data"),
            }
        )
    return compact[:120]

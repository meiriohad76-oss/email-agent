import json
from dataclasses import dataclass
from typing import Any, Protocol

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
    actionable_data: list[dict[str, Any]]
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


ARTICLE_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Brief stock-market relevant summary of the article.",
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
        "actionable_data": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
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
                    "timeframe": {"type": "string"},
                    "catalysts": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "financial_details": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "ticker",
                    "sentiment",
                    "recommendation",
                    "timeframe",
                    "catalysts",
                    "risks",
                    "financial_details",
                    "evidence",
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
        "actionable_data",
    ],
    "additionalProperties": False,
}


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
                        "Extract sentiment, recommendation, price targets, catalysts, risks, "
                        "valuation details, guidance, margins, P/E, revenue, EPS, ratings, "
                        "and other actionable data for each materially discussed ticker. "
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
        actionable_data = list(payload["actionable_data"])
        if confidence > 0.70 and len(supporting_evidence) < 2:
            raise ValueError(
                "Article analysis with confidence above 70% requires at least 2 supporting evidence items"
            )
        raw_response = {
            "output_text": raw_output,
            "sentiment": payload["sentiment"],
            "recommendation": payload["recommendation"],
            "price_targets": price_targets,
            "actionable_data": actionable_data,
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
            actionable_data=actionable_data,
            raw_response=raw_response,
        )

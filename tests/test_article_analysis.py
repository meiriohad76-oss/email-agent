import json

import pytest

from email_article_analyzer.article_analysis import OpenAIArticleAnalyzer
from email_article_analyzer.article_analysis import OpenAIArticlePrechecker
from email_article_analyzer.article_analysis import OpenAIRunReportSynthesizer
from email_article_analyzer.model_defaults import DEFAULT_EXTRACTION_MODEL
from email_article_analyzer.model_defaults import DEFAULT_REPORT_MODEL
from email_article_analyzer.model_defaults import DEFAULT_SUMMARY_MODEL


class FakeResponses:
    def __init__(self, output_text):
        self.output_text = output_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("Response", (), {"output_text": self.output_text})()


class FakeOpenAIClient:
    def __init__(self, output_text):
        self.responses = FakeResponses(output_text)


def test_openai_article_analyzer_requests_strict_structured_output():
    client = FakeOpenAIClient(
        json.dumps(
            {
                "summary": "Margins improved after a stronger guide.",
                "stance": "buy_watch",
                "sentiment": "bullish",
                "recommendation": "buy",
                "confidence": 0.82,
                "supporting_evidence": ["Raised FY guide", "Gross margin expanded"],
                "mentioned_tickers": ["NVDA"],
                "price_targets": [
                    {
                        "ticker": "NVDA",
                        "target_price": 150.0,
                        "currency": "USD",
                        "timeframe": "12 months",
                        "source_text": "$150 price target",
                    }
                ],
                "rating_snapshots": [
                    {
                        "ticker": "NVDA",
                        "provider": "seeking_alpha",
                        "rating_type": "quant",
                        "rating": "Strong Buy",
                        "score": 4.8,
                        "price_target": None,
                        "currency": "USD",
                        "source_text": "SA Quant rates NVDA Strong Buy",
                    },
                    {
                        "ticker": "NVDA",
                        "provider": "zacks",
                        "rating_type": "rank",
                        "rating": "Rank #2 Buy",
                        "score": 2,
                        "price_target": 170.0,
                        "currency": "USD",
                        "source_text": "Zacks Rank #2 Buy with $170 target",
                    },
                ],
                "actionable_data": [
                    {
                        "ticker": "NVDA",
                        "theme_summary": (
                            "The article argues that Nvidia's raised outlook strengthens the growth thesis. "
                            "Margin expansion provides operating support for that view."
                        ),
                        "key_points": ["Revenue guidance increased", "Gross margin expanded"],
                        "sentiment": "bullish",
                        "recommendation": "buy",
                        "source_recommendation_text": "The author recommends buying NVDA for a 12-month horizon.",
                        "timeframe": "12 months",
                        "catalysts": ["Raised guidance"],
                        "risks": ["Gross margin compression"],
                        "financial_details": ["Gross margin expanded"],
                        "evidence": ["Raised FY guide", "Gross margin expanded"],
                        "investor_actions": ["Compare the growth outlook with the current valuation."],
                        "follow_up_checks": ["Monitor the next revenue guide and gross-margin outlook."],
                    }
                ],
                "actionable_signals": [
                    {
                        "ticker": "NVDA",
                        "signal_type": "guidance",
                        "signal": "Revenue outlook raised",
                        "value": "higher FY guide",
                        "direction": "positive",
                        "timeframe": "FY",
                        "source_text": "Raised FY guide",
                    }
                ],
            }
        )
    )
    analyzer = OpenAIArticleAnalyzer(client=client)

    result = analyzer.analyze_article(
        url="https://example.com/article",
        source_key="example",
        email_subject="NVDA raises guidance",
        article_title="NVDA raises guidance",
        article_text="Nvidia raised its revenue outlook. Gross margin expanded.",
        model="gpt-summary",
    )

    call = client.responses.calls[0]
    assert call["model"] == "gpt-summary"
    assert call["text"]["format"]["type"] == "json_schema"
    assert call["text"]["format"]["strict"] is True
    user_content = call["input"][1]["content"]
    assert "Article title: NVDA raises guidance" in user_content
    assert "Article text:" in user_content
    assert "Gross margin expanded" in user_content
    assert result.provider == "openai"
    assert result.model == "gpt-summary"
    assert result.summary == "Margins improved after a stronger guide."
    assert result.stance == "buy_watch"
    assert result.sentiment == "bullish"
    assert result.recommendation == "buy"
    assert result.confidence == 0.82
    assert result.supporting_evidence == ["Raised FY guide", "Gross margin expanded"]
    assert result.mentioned_tickers == ["NVDA"]
    assert result.price_targets == [
        {
            "ticker": "NVDA",
            "target_price": 150.0,
            "currency": "USD",
            "timeframe": "12 months",
            "source_text": "$150 price target",
        }
    ]
    assert result.actionable_data[0]["recommendation"] == "buy"
    assert result.actionable_data[0]["theme_summary"].startswith("The article argues")
    assert result.actionable_signals[0]["signal_type"] == "guidance"
    assert result.raw_response["rating_snapshots"][0]["rating"] == "Strong Buy"
    assert "price_targets" in call["text"]["format"]["schema"]["required"]
    assert "rating_snapshots" in call["text"]["format"]["schema"]["required"]
    assert "actionable_data" in call["text"]["format"]["schema"]["required"]
    assert "actionable_signals" in call["text"]["format"]["schema"]["required"]
    action_schema = call["text"]["format"]["schema"]["properties"]["actionable_data"]["items"]
    assert "theme_summary" in action_schema["required"]
    assert "key_points" in action_schema["required"]
    assert "source_recommendation_text" in action_schema["required"]
    assert "investor_actions" in action_schema["required"]
    assert "follow_up_checks" in action_schema["required"]
    assert "substantive article brief" in call["input"][0]["content"]


def test_openai_article_analyzer_rejects_high_confidence_without_two_evidence_items():
    client = FakeOpenAIClient(
        json.dumps(
            {
                "summary": "A bullish read.",
                "stance": "buy_watch",
                "sentiment": "bullish",
                "recommendation": "buy",
                "confidence": 0.81,
                "supporting_evidence": ["Raised guide"],
                "mentioned_tickers": ["NVDA"],
                "price_targets": [],
                "rating_snapshots": [],
                "actionable_data": [],
                "actionable_signals": [],
            }
        )
    )
    analyzer = OpenAIArticleAnalyzer(client=client)

    with pytest.raises(ValueError, match="at least 2 supporting evidence"):
        analyzer.analyze_article(
            url="https://example.com/article",
            source_key="example",
            email_subject="NVDA raises guidance",
            article_title=None,
            article_text="Raised guide.",
            model="gpt-summary",
        )


def test_openai_article_analyzer_uses_default_model_when_input_is_blank():
    client = FakeOpenAIClient(
        json.dumps(
            {
                "summary": "A neutral read.",
                "stance": "hold",
                "sentiment": "neutral",
                "recommendation": "hold",
                "confidence": 0.62,
                "supporting_evidence": ["Revenue guide was maintained"],
                "mentioned_tickers": ["NVDA"],
                "price_targets": [],
                "rating_snapshots": [],
                "actionable_data": [
                    {
                        "ticker": "NVDA",
                        "sentiment": "neutral",
                        "recommendation": "hold",
                        "timeframe": "unclear",
                        "catalysts": [],
                        "risks": [],
                        "financial_details": ["Revenue guide was maintained"],
                        "evidence": ["Revenue guide was maintained"],
                    }
                ],
                "actionable_signals": [
                    {
                        "ticker": "NVDA",
                        "signal_type": "guidance",
                        "signal": "Revenue guide maintained",
                        "value": "unchanged",
                        "direction": "neutral",
                        "timeframe": "unclear",
                        "source_text": "Revenue guide was maintained",
                    }
                ],
            }
        )
    )
    analyzer = OpenAIArticleAnalyzer(client=client)

    result = analyzer.analyze_article(
        url="https://example.com/article",
        source_key="example",
        email_subject="NVDA update",
        article_title=None,
        article_text="Revenue guide was maintained.",
        model=" ",
    )

    assert client.responses.calls[0]["model"] == DEFAULT_SUMMARY_MODEL
    assert result.model == DEFAULT_SUMMARY_MODEL


def test_openai_article_prechecker_uses_extraction_model_and_structured_output():
    client = FakeOpenAIClient(
        json.dumps(
            {
                "is_relevant": True,
                "confidence": 0.91,
                "tickers": ["CRDO"],
                "reason": "The article discusses CRDO price targets.",
            }
        )
    )
    prechecker = OpenAIArticlePrechecker(client=client)

    result = prechecker.precheck_article(
        url="https://example.com/crdo",
        source_key="seeking_alpha",
        email_subject="CRDO target raised",
        article_title="CRDO target raised",
        article_text="CRDO analysts increased targets.",
        model=" ",
    )

    call = client.responses.calls[0]
    assert call["model"] == DEFAULT_EXTRACTION_MODEL
    assert call["text"]["format"]["name"] == "stock_article_precheck"
    assert result.is_relevant is True
    assert result.confidence == 0.91
    assert result.tickers == ["CRDO"]


def test_openai_run_report_synthesizer_uses_report_model_and_structured_output():
    client = FakeOpenAIClient(
        json.dumps(
            {
                "executive_summary": "CRDO is the top review item.",
                "priority_tickers": [
                    {
                        "ticker": "CRDO",
                        "priority": "high",
                        "reason": "Multiple bullish signals.",
                        "evidence": ["Buy article", "Positive target spread"],
                    }
                ],
                "contradictions": [],
                "recommended_actions": ["Review CRDO target versus Polygon close."],
            }
        )
    )
    synthesizer = OpenAIRunReportSynthesizer(client=client)

    result = synthesizer.synthesize_run(
        run={"id": 7, "status": "completed"},
        articles=[
            {
                "subject": "CRDO article",
                "source_key": "zacks",
                "normalized_url": "https://example.com/crdo",
                "analysis": {
                    "stance": "buy_watch",
                    "sentiment": "bullish",
                    "recommendation": "buy",
                    "confidence": 0.8,
                    "summary": "Bullish CRDO article.",
                    "mentioned_tickers": ["CRDO"],
                    "supporting_evidence": ["Buy article"],
                },
            }
        ],
        ticker_enrichments=[],
        model=None,
    )

    call = client.responses.calls[0]
    assert call["model"] == DEFAULT_REPORT_MODEL
    assert call["text"]["format"]["name"] == "stock_run_report_synthesis"
    assert result.executive_summary == "CRDO is the top review item."
    assert result.priority_tickers[0]["ticker"] == "CRDO"

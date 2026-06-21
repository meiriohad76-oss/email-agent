import json

import pytest

from email_article_analyzer.article_analysis import OpenAIArticleAnalyzer
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
                "confidence": 0.82,
                "supporting_evidence": ["Raised FY guide", "Gross margin expanded"],
                "mentioned_tickers": ["NVDA"],
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
    assert result.confidence == 0.82
    assert result.supporting_evidence == ["Raised FY guide", "Gross margin expanded"]
    assert result.mentioned_tickers == ["NVDA"]


def test_openai_article_analyzer_rejects_high_confidence_without_two_evidence_items():
    client = FakeOpenAIClient(
        json.dumps(
            {
                "summary": "A bullish read.",
                "stance": "buy_watch",
                "confidence": 0.81,
                "supporting_evidence": ["Raised guide"],
                "mentioned_tickers": ["NVDA"],
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
                "confidence": 0.62,
                "supporting_evidence": ["Revenue guide was maintained"],
                "mentioned_tickers": ["NVDA"],
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

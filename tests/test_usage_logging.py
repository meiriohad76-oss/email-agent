import sqlite3
from types import SimpleNamespace

import pytest

from email_article_analyzer.article_analysis import _compact_articles_for_synthesis, _compact_enrichments_for_synthesis
from email_article_analyzer.usage_logging import UsageLoggingClient, estimate


class FakeResponses:
    def __init__(self, fail=False):
        self.fail = fail

    def create(self, **kw):
        if self.fail:
            raise RuntimeError("boom")
        usage = SimpleNamespace(input_tokens=1000, output_tokens=500,
                                input_tokens_details=SimpleNamespace(cached_tokens=200),
                                output_tokens_details=SimpleNamespace(reasoning_tokens=300))
        return SimpleNamespace(usage=usage, model=kw["model"], output_text="{}")


def test_usage_row_written_and_call_unchanged(tmp_path):
    db = str(tmp_path / "app.db")
    client = UsageLoggingClient(SimpleNamespace(responses=FakeResponses(), other="x"), db)
    r = client.responses.create(model="gpt-5.6-terra", input=[], text={"format": {"name": "stock_article_analysis"}})
    assert r.output_text == "{}" and client.other == "x"
    row = sqlite3.connect(db).execute("SELECT call_type, model, input_tokens, cached_tokens, output_tokens, reasoning_tokens, est_cost_usd FROM openai_usage").fetchone()
    assert row[:6] == ("stock_article_analysis", "gpt-5.6-terra", 1000, 200, 500, 300)
    assert row[6] == pytest.approx((800 * 2.0 + 200 * 0.2 + 500 * 12.0) / 1e6)


def test_failed_call_logged_and_reraised(tmp_path):
    db = str(tmp_path / "app.db")
    client = UsageLoggingClient(SimpleNamespace(responses=FakeResponses(fail=True)), db)
    with pytest.raises(RuntimeError):
        client.responses.create(model="gpt-5.6-sol", input=[])
    assert sqlite3.connect(db).execute("SELECT ok FROM openai_usage").fetchone() == (0,)


def test_long_context_price_and_unknown_model():
    assert estimate("gpt-5.6-sol", 300_000, 0, 0) == pytest.approx(300_000 * 8.0 / 1e6)
    assert estimate("other-model", 10, 0, 10) is None


def test_report_input_keeps_conclusions_drops_raw_tables():
    arts = [{"subject": "S", "source_key": "seeking_alpha", "normalized_url": "https://x/a?utm=1",
             "analysis": {"stance": "buy_watch", "summary": "y" * 2000, "mentioned_tickers": ["ORCL"],
                          "actionable_data": [{"huge": "z" * 50000}], "supporting_evidence": ["e1", "e2", "e3"]}}]
    a = _compact_articles_for_synthesis(arts)[0]
    assert "actionable_data" not in a and len(a["summary"]) <= 701 and a["url"] == "https://x/a" and len(a["evidence"]) == 2
    enr = [{"ticker": "ORCL", "provider": "zacks", "data_type": "rank", "status": "ready",
            "data": {"rating_type": "rank", "rating": "Rank #1 Strong Buy", "score": 1}},
           {"ticker": "ORCL", "provider": "zacks", "data_type": "options_chain", "status": "ready", "data": {"rows": [1] * 999}}]
    e = _compact_enrichments_for_synthesis(enr)
    assert e == [{"ticker": "ORCL", "provider": "zacks", "type": "rank", "rating": "Rank #1 Strong Buy", "score": 1}]

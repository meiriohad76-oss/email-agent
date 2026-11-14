import json

from email_article_analyzer.article_analysis import ArticleAnalysisResult
from email_article_analyzer.local_routing import LocalFirstArticleAnalyzer, OllamaArticleAnalyzer


def _ollama(payload):
    return OllamaArticleAnalyzer(post=lambda body: {"message": {"content": json.dumps(payload)}})


class Cloud:
    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    def analyze_article(self, *a, model=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("openai down")
        return ArticleAnalysisResult("openai", "gpt", "full", "buy_watch", "bullish", "buy", 0.9, ["a", "b"], ["ORCL"],
                                     [], [], [{"x": 1}], [], {"output_text": "{}"})


ARGS = ("u", "seeking_alpha", "subj", "title", "text")


def test_untracked_article_stays_local_and_free():
    cloud = Cloud()
    r = LocalFirstArticleAnalyzer(_ollama({"stance": "hold", "confidence": 0.6, "tickers": ["$xyz"], "summary": "s", "evidence": []}),
                                  cloud, lambda: {"ORCL"}).analyze_article(*ARGS)
    assert cloud.calls == 0 and r.provider == "ollama" and r.mentioned_tickers == ["XYZ"]
    assert r.raw_response["routing"]["path"] == "local"


def test_holding_article_gets_full_cloud_brief_and_keeps_local_stance():
    cloud = Cloud()
    r = LocalFirstArticleAnalyzer(_ollama({"stance": "hold", "confidence": 0.6, "tickers": ["ORCL"], "summary": "s", "evidence": []}),
                                  cloud, lambda: {"ORCL"}).analyze_article(*ARGS)
    assert cloud.calls == 1 and r.provider == "openai" and r.raw_response["routing"]["local_stance"] == "hold"


def test_fallbacks_both_ways():
    class Down:
        def analyze_article(self, *a, **k):
            raise ConnectionError("ollama down")
    cloud = Cloud()
    r = LocalFirstArticleAnalyzer(Down(), cloud, lambda: set()).analyze_article(*ARGS)
    assert r.provider == "openai" and r.raw_response["routing"]["path"] == "cloud_fallback"
    r2 = LocalFirstArticleAnalyzer(_ollama({"stance": "buy_watch", "confidence": 0.9, "tickers": ["ORCL"], "summary": "s",
                                            "evidence": ["e1"]}), Cloud(fail=True), lambda: {"ORCL"}).analyze_article(*ARGS)
    assert r2.provider == "ollama" and r2.raw_response["routing"]["path"] == "local_after_cloud_error"
    assert r2.confidence == 0.70   # high confidence capped without 2 evidence items


def test_bad_stance_becomes_unclear():
    r = _ollama({"stance": "moon", "confidence": 2, "tickers": [], "summary": "", "evidence": []}).analyze_article(*ARGS)
    assert r.stance == "unclear" and r.confidence <= 1

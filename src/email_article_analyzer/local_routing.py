"""Local-first article analysis (cost control, 2026-11-14).

Every article is classified by the local model (Ollama, $0): stance, confidence, tickers, short summary.
Only articles that mention a HOLDING (the active watchlist = current portfolio) also get the full OpenAI brief.
Fallbacks: Ollama down -> OpenAI as before; OpenAI error -> keep the local result.
Measured before switching: local stance == GPT stance on 18/20 recent articles, same tickers 20/20, ~10 s/article.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable

from email_article_analyzer.article_analysis import ArticleAnalysisResult

STANCES = ["buy_watch", "hold", "sell_watch", "avoid", "unclear"]
SENTIMENT = {"buy_watch": "bullish", "hold": "neutral", "sell_watch": "bearish", "avoid": "strong_bearish", "unclear": "unclear"}
SCHEMA = {"type": "object", "properties": {
    "stance": {"type": "string", "enum": STANCES},
    "confidence": {"type": "number"},
    "tickers": {"type": "array", "items": {"type": "string"}},
    "summary": {"type": "string"},
    "evidence": {"type": "array", "items": {"type": "string"}}},
    "required": ["stance", "confidence", "tickers", "summary", "evidence"]}
SYSTEM = ("You classify a stock-market newsletter article for an investor. stance = the AUTHOR's explicit view on the main "
          "ticker(s): buy_watch (bullish / buy / upgrade), hold (neutral, fairly valued, wait), sell_watch (bearish / downgrade / "
          "trim), avoid (strong sell / stay away), unclear (no explicit view, news only, or mixed). Do not infer a view the author "
          "did not give. tickers = symbols explicitly discussed. summary = 3 plain sentences grounded in the article. "
          "evidence = up to 3 short quotes or facts from the article supporting the stance. confidence 0-1 that the stance is right.")


class OllamaArticleAnalyzer:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", model: str = "gemma4:12b", timeout: float = 300,
                 post: Callable[[dict], dict] | None = None):
        self.base_url, self.model, self.timeout, self._post = base_url.rstrip("/"), model, timeout, post

    def _call(self, body: dict) -> dict:
        if self._post:
            return self._post(body)
        req = urllib.request.Request(f"{self.base_url}/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    def analyze_article(self, url, source_key, email_subject, article_title, article_text, model=None) -> ArticleAnalysisResult:
        body = {"model": self.model, "stream": False, "think": False, "format": SCHEMA,
                "options": {"num_ctx": 8192, "temperature": 0},
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": f"Source: {source_key}\nEmail headline: {email_subject}\n"
                                                         f"Title: {article_title or 'Unknown'}\nArticle:\n{(article_text or '')[:8000]}"}]}
        out = json.loads(self._call(body)["message"]["content"])
        stance = out["stance"] if out.get("stance") in STANCES else "unclear"
        tickers = sorted({str(t).upper().lstrip("$").strip() for t in out.get("tickers") or [] if str(t).strip()})
        conf = max(0.0, min(1.0, float(out.get("confidence") or 0)))
        evidence = [str(e) for e in (out.get("evidence") or [])][:3]
        if conf > 0.70 and len(evidence) < 2:
            conf = 0.70   # same rule as the OpenAI path: high confidence needs 2 evidence items
        return ArticleAnalysisResult(
            provider="ollama", model=self.model, summary=str(out.get("summary") or ""), stance=stance,
            sentiment=SENTIMENT[stance], recommendation="", confidence=conf, supporting_evidence=evidence,
            mentioned_tickers=tickers, price_targets=[], rating_snapshots=[], actionable_data=[], actionable_signals=[],
            raw_response={"output_text": json.dumps(out), "sentiment": SENTIMENT[stance], "recommendation": "",
                          "price_targets": [], "rating_snapshots": [], "actionable_data": [], "actionable_signals": []})


class LocalFirstArticleAnalyzer:
    """Local for every article; OpenAI only when a holding is mentioned."""

    def __init__(self, local, cloud, holdings: Callable[[], set[str]]):
        self.local, self.cloud, self.holdings = local, cloud, holdings

    def analyze_article(self, url, source_key, email_subject, article_title, article_text, model=None) -> ArticleAnalysisResult:
        args = (url, source_key, email_subject, article_title, article_text)
        try:
            loc = self.local.analyze_article(*args)
        except Exception as exc:  # Ollama down or bad output: behave exactly as before
            if self.cloud is None:
                raise
            res = self.cloud.analyze_article(*args, model=model)
            return _tag(res, {"path": "cloud_fallback", "local_error": str(exc)[:200]})
        held = {t.upper() for t in self.holdings()}
        hit = sorted(set(loc.mentioned_tickers) & held)
        if not hit or self.cloud is None:
            return _tag(loc, {"path": "local", "holdings_mentioned": hit})
        try:
            res = self.cloud.analyze_article(*args, model=model)
        except Exception as exc:
            return _tag(loc, {"path": "local_after_cloud_error", "holdings_mentioned": hit, "cloud_error": str(exc)[:200]})
        return _tag(res, {"path": "cloud", "holdings_mentioned": hit, "local_stance": loc.stance,
                          "local_tickers": loc.mentioned_tickers})


def _tag(res: ArticleAnalysisResult, routing: dict[str, Any]) -> ArticleAnalysisResult:
    from dataclasses import replace
    return replace(res, raw_response={**res.raw_response, "routing": routing})

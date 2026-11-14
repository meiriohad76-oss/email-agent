"""Record the real OpenAI token usage of every call (added 2026-11-14 for cost tracking).

Wraps the OpenAI client: `client.responses.create(...)` behaves exactly as before, then one row goes into the
`openai_usage` table of app.db. Cost is an ESTIMATE from the standard price list below (per 1M tokens, OpenAI pricing
page, 14 Nov 2026); the OpenAI usage dashboard stays the source of truth.
"""
from __future__ import annotations

import sqlite3
import threading
from typing import Any

PRICES = {  # model: (input, cached input, output) USD per 1M tokens, standard tier, short context (<=272K)
    "gpt-5.6-luna": (0.20, 0.02, 1.20),
    "gpt-5.6-terra": (2.00, 0.20, 12.00),
    "gpt-5.6-sol": (4.00, 0.40, 20.00),
}
LONG = {"gpt-5.6-luna": (0.40, 0.04, 1.80), "gpt-5.6-terra": (4.00, 0.40, 18.00), "gpt-5.6-sol": (8.00, 0.80, 30.00)}
_lock = threading.Lock()


def ensure_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS openai_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            call_type TEXT, model TEXT, input_tokens INTEGER, cached_tokens INTEGER, output_tokens INTEGER,
            reasoning_tokens INTEGER, est_cost_usd REAL, ok INTEGER NOT NULL DEFAULT 1, error TEXT)""")


def estimate(model: str, inp: int, cached: int, out: int) -> float | None:
    table = LONG if inp > 272_000 else PRICES
    p = table.get(model)
    if not p:
        return None
    return round(((inp - cached) * p[0] + cached * p[1] + out * p[2]) / 1e6, 6)


def _get(obj: Any, *names, default=0):
    for n in names:
        obj = getattr(obj, n, None) if not isinstance(obj, dict) else obj.get(n)
        if obj is None:
            return default
    return obj


class _Responses:
    def __init__(self, inner, db_path: str):
        self._inner, self._db = inner, db_path

    def create(self, **kwargs):
        call_type = _get(kwargs.get("text") or {}, "format", "name", default=None)
        model = kwargs.get("model")
        try:
            resp = self._inner.create(**kwargs)
        except Exception as exc:
            self._write(call_type, model, 0, 0, 0, 0, None, ok=0, error=str(exc)[:300])
            raise
        u = getattr(resp, "usage", None)
        inp = int(_get(u, "input_tokens") or 0)
        cached = int(_get(u, "input_tokens_details", "cached_tokens") or 0)
        out = int(_get(u, "output_tokens") or 0)
        reasoning = int(_get(u, "output_tokens_details", "reasoning_tokens") or 0)
        self._write(call_type, getattr(resp, "model", None) or model, inp, cached, out, reasoning, estimate(model, inp, cached, out))
        return resp

    def _write(self, call_type, model, inp, cached, out, reasoning, cost, ok=1, error=None):
        try:
            with _lock, sqlite3.connect(self._db) as c:
                c.execute("""INSERT INTO openai_usage (call_type, model, input_tokens, cached_tokens, output_tokens,
                             reasoning_tokens, est_cost_usd, ok, error) VALUES (?,?,?,?,?,?,?,?,?)""",
                          (call_type, model, inp, cached, out, reasoning, cost, ok, error))
        except sqlite3.Error:
            pass  # logging must never break an analysis


class UsageLoggingClient:
    def __init__(self, client, db_path: str):
        ensure_table(db_path)
        self._client = client
        self.responses = _Responses(client.responses, db_path)

    def __getattr__(self, name):
        return getattr(self._client, name)

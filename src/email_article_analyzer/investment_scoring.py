from __future__ import annotations

import math
import statistics
from typing import Any


CATEGORY_WEIGHTS = {
    "valuation": 20,
    "moat_evidence": 20,
    "fcf_quality": 15,
    "growth_revisions": 15,
    "pricing_power": 10,
    "downside_quality": 10,
    "cross_source_consensus": 5,
    "momentum": 5,
}


def score_company_research(
    records: list[dict[str, Any]],
    category_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Turn provider research records into auditable, coverage-aware factor scores."""
    weights = category_weights or CATEGORY_WEIGHTS
    by_key = {
        (str(record.get("provider")), str(record.get("rating_type"))): record
        for record in records
        if record
    }
    categories = {
        "valuation": _valuation(by_key),
        "moat_evidence": _moat(by_key),
        "fcf_quality": _fcf_quality(by_key),
        "growth_revisions": _growth_revisions(by_key),
        "pricing_power": _pricing_power(by_key),
        "downside_quality": _downside_quality(by_key),
        "cross_source_consensus": _consensus(by_key),
        "momentum": _grade_category(by_key, "momentum_metrics", "SA momentum grade"),
    }
    available = {
        name: value
        for name, value in categories.items()
        if value["score"] is not None and value["sufficient_evidence"]
    }
    available_weight = sum(weights[name] for name in available)
    composite = None
    if available_weight:
        composite = round(
            sum(value["score"] * weights[name] for name, value in available.items())
            / available_weight,
            2,
        )
    coverage = round(available_weight / sum(weights.values()), 4)
    comparable = coverage >= 0.70 and len(available) >= 6
    ticker = next((record.get("ticker") for record in records if record.get("ticker")), None)
    return {
        "ticker": ticker,
        "composite_score": composite,
        "score_coverage": coverage,
        "comparable_rank_eligible": comparable,
        "categories": categories,
        "methodology_note": (
            "Moat is a derived evidence score, not a provider-supplied moat rating. "
            "Missing categories are excluded and disclosed through score_coverage."
        ),
    }


def _valuation(records: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    signals = []
    _add_grade(signals, records, "seeking_alpha", "valuation_metrics", "SA valuation grade")
    zacks = _zacks_style_record(records)
    _add_grade_value(signals, (zacks.get("style_scores") or {}).get("value"), "Zacks value style")
    forecast = records.get(("investing_pro", "forecast"), {})
    upside = _number(forecast.get("fair_value_upside_pct"))
    if upside is not None:
        signals.append(_signal("InvestingPro Fair Value upside", _linear(upside, -25, 25), upside))
    ratios = _ratio_metrics(records)
    for label in ("P/E RatioTTM", "Price to Free Cash FlowTTM", "EV / EBITDA TTM"):
        metric = ratios.get(_norm(label))
        relative = _lower_is_better_ratio(metric)
        if relative is not None:
            signals.append(_signal(f"{label} vs industry", relative, metric))
    return _finish(signals, minimum_signals=3)


def _moat(records: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    signals = []
    _add_grade(signals, records, "seeking_alpha", "profitability_metrics", "SA profitability grade")
    ratios = _ratio_metrics(records)
    for label in ("Return on EquityTTM", "Return on AssetsTTM", "Return on InvestmentTTM"):
        metric = ratios.get(_norm(label))
        relative = _higher_is_better_ratio(metric)
        if relative is not None:
            signals.append(_signal(f"{label} vs industry", relative, metric))
    profitability = records.get(("seeking_alpha", "profitability_metrics"), {})
    for label in ("Gross Profit Margin (TTM)", "EBIT Margin (TTM)", "Levered FCF Margin (TTM)"):
        metric = _sa_metric(profitability, label)
        if metric:
            diff = _number((metric.get("difference_to_sector") or {}).get("value"))
            if diff is not None:
                signals.append(_signal(f"{label} premium vs sector", _linear(diff, -30, 30), diff))
    return _finish(signals, minimum_signals=3)


def _fcf_quality(records: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    signals = []
    profitability = records.get(("seeking_alpha", "profitability_metrics"), {})
    fcf_margin = _sa_metric(profitability, "Levered FCF Margin (TTM)")
    if fcf_margin:
        value = _number((fcf_margin.get("company") or {}).get("value"))
        if value is not None:
            signals.append(_signal("Levered FCF margin", _linear(value, 0, 25), value, weight=0.50))
    summary = records.get(("investing_pro", "financial_summary"), {})
    series = ((summary.get("metrics") or {}).get("Levered Free Cash Flow") or {})
    ordered_series = sorted(series.items(), key=lambda item: str(item[0]))
    values = [_number((item or {}).get("value")) for _, item in ordered_series]
    values = [value for value in values if value is not None]
    if values:
        positive_share = sum(value > 0 for value in values) / len(values)
        signals.append(_signal("Positive annual FCF persistence", positive_share * 100, positive_share, weight=0.25))
        if len(values) >= 6:
            early = statistics.median(values[:3])
            recent = statistics.median(values[-3:])
            if early != 0:
                trend = (recent - early) / abs(early) * 100
                signals.append(_signal("Median recent vs early FCF change", _linear(trend, -50, 100), trend, weight=0.25))
    return _finish(signals, minimum_signals=2)


def _growth_revisions(records: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    signals = []
    _add_grade(signals, records, "seeking_alpha", "growth_metrics", "SA growth grade")
    zacks = _zacks_style_record(records)
    _add_grade_value(signals, (zacks.get("style_scores") or {}).get("growth"), "Zacks growth style")
    revisions = records.get(("seeking_alpha", "revisions"), {})
    counts = revisions.get("revision_counts_3m") or {}
    observed = [counts.get(key) for key in ("eps_up", "eps_down", "revenue_up", "revenue_down")]
    if any(value is not None for value in observed):
        ups = (counts.get("eps_up") or 0) + (counts.get("revenue_up") or 0)
        downs = (counts.get("eps_down") or 0) + (counts.get("revenue_down") or 0)
        total = ups + downs
        if total:
            signals.append(_signal("3M estimate revision breadth", ups / total * 100, {"up": ups, "down": downs}))
    return _finish(signals, minimum_signals=2)


def _pricing_power(records: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    signals = []
    profitability = records.get(("seeking_alpha", "profitability_metrics"), {})
    gross_margin = _sa_metric(profitability, "Gross Profit Margin (TTM)")
    if gross_margin:
        sector_diff = _number((gross_margin.get("difference_to_sector") or {}).get("value"))
        history_diff = _number((gross_margin.get("difference_to_five_year_average") or {}).get("value"))
        if sector_diff is not None:
            signals.append(_signal("Gross margin premium vs sector", _linear(sector_diff, -25, 25), sector_diff))
        if history_diff is not None:
            signals.append(_signal("Gross margin stability vs 5Y average", _linear(-abs(history_diff), -15, 0), history_diff))
    ratios = _ratio_metrics(records)
    current = ratios.get(_norm("Gross marginTTM"))
    historical = ratios.get(_norm("Gross Margin5YA"))
    current_value = _company_value(current)
    historical_value = _company_value(historical)
    if current_value is not None and historical_value is not None:
        change = current_value - historical_value
        signals.append(_signal("Gross margin change vs 5Y", _linear(change, -10, 5), change))
    return _finish(signals, minimum_signals=2)


def _downside_quality(records: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    signals = []
    overview = records.get(("investing_pro", "overview"), {})
    health = str(overview.get("financial_health") or overview.get("rating") or "").lower()
    health_scores = {"excellent": 100, "great": 90, "good": 75, "fair": 50, "weak": 25, "poor": 10}
    for label, score in health_scores.items():
        if label in health:
            signals.append(_signal("InvestingPro financial health", score, health))
            break
    beta = _number((((overview.get("metrics") or {}).get("Beta") or {}).get("value")))
    if beta is not None:
        signals.append(_signal("Beta downside sensitivity", _linear(beta, 2.0, 0.5), beta, weight=0.40))
    ratios = _ratio_metrics(records)
    debt_equity = ratios.get(_norm("Total Debt to EquityMRQ"))
    relative = _lower_is_better_ratio(debt_equity)
    if relative is not None:
        signals.append(_signal("Debt/equity vs industry", relative, debt_equity, weight=0.60))
    return _finish(signals, minimum_signals=2)


def _consensus(records: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    signals = []
    rating_scores = {"strong buy": 100, "buy": 80, "outperform": 75, "hold": 50, "neutral": 50, "sell": 20, "underperform": 25, "strong sell": 0}
    for (provider, rating_type), record in records.items():
        if rating_type not in {"quant", "analysts", "wall_street", "forecast"}:
            continue
        rating = str(record.get("rating") or "").lower()
        if rating in rating_scores:
            signals.append(_signal(f"{provider} {rating_type}", rating_scores[rating], rating))
    zacks = records.get(("zacks", "detailed_estimates"), {}) or records.get(("zacks", "rank"), {})
    rank = _number(zacks.get("zacks_rank"))
    if rank is not None:
        signals.append(_signal("Zacks rank", (5 - rank) * 25, rank))
    return _finish(signals, minimum_signals=3)


def _zacks_style_record(records: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    detailed = records.get(("zacks", "detailed_estimates"), {})
    if detailed.get("style_scores"):
        return detailed
    return records.get(("zacks", "rank"), {})


def _grade_category(records, rating_type: str, label: str) -> dict[str, Any]:
    signals = []
    _add_grade(signals, records, "seeking_alpha", rating_type, label)
    return _finish(signals, minimum_signals=1)


def _add_grade(signals, records, provider: str, rating_type: str, label: str) -> None:
    record = records.get((provider, rating_type), {})
    _add_grade_value(signals, record.get("grade"), label)


def _add_grade_value(signals, grade: Any, label: str) -> None:
    score = {"A+": 100, "A": 96, "A-": 92, "B+": 85, "B": 80, "B-": 75, "C+": 67, "C": 60, "C-": 52, "D+": 43, "D": 35, "D-": 25, "F": 10}.get(str(grade or "").upper())
    if score is not None:
        signals.append(_signal(label, score, grade))


def _ratio_metrics(records) -> dict[str, dict[str, Any]]:
    result = {}
    ratios = records.get(("investing_pro", "ratios"), {})
    for metrics in (ratios.get("categories") or {}).values():
        for metric in metrics or []:
            result[_norm(str(metric.get("metric") or ""))] = metric
    return result


def _sa_metric(record: dict[str, Any], name: str) -> dict[str, Any] | None:
    normalized = _norm(name)
    return next((metric for metric in record.get("metrics") or [] if _norm(str(metric.get("metric"))) == normalized), None)


def _higher_is_better_ratio(metric: dict[str, Any] | None) -> float | None:
    company, industry = _company_value(metric), _industry_value(metric)
    if company is None or industry is None:
        return None
    scale = max(abs(industry), 1.0)
    return _clamp(50 + 35 * math.tanh((company - industry) / scale))


def _lower_is_better_ratio(metric: dict[str, Any] | None) -> float | None:
    company, industry = _company_value(metric), _industry_value(metric)
    if company is None or industry is None or company <= 0 or industry <= 0:
        return None
    return _clamp(50 + 35 * math.tanh(math.log(industry / company)))


def _company_value(metric):
    return _number(((metric or {}).get("company") or {}).get("value"))


def _industry_value(metric):
    return _number(((metric or {}).get("industry") or {}).get("value"))


def _finish(signals: list[dict[str, Any]], minimum_signals: int) -> dict[str, Any]:
    total_weight = sum(item["weight"] for item in signals)
    score = (
        round(sum(item["score"] * item["weight"] for item in signals) / total_weight, 2)
        if total_weight
        else None
    )
    return {
        "score": score,
        "signal_count": len(signals),
        "minimum_signal_count": minimum_signals,
        "sufficient_evidence": len(signals) >= minimum_signals,
        "evidence": signals,
    }


def _signal(label: str, score: float, raw: Any, weight: float = 1.0) -> dict[str, Any]:
    return {"label": label, "score": round(_clamp(score), 2), "weight": weight, "raw": raw}


def _linear(value: float, low: float, high: float) -> float:
    if high == low:
        return 50.0
    return _clamp((value - low) / (high - low) * 100)


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())

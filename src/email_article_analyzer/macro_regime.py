from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from typing import Any


DEFAULT_STALE_AFTER_DAYS = 45


def load_macro_regime(path: Path, today: date | None = None) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _unavailable_regime("Macro regime file has not been created yet.")
    except (OSError, json.JSONDecodeError) as exc:
        return _unavailable_regime(f"Macro regime file could not be read: {exc}")

    try:
        return prepare_macro_regime(payload, today=today)
    except (KeyError, TypeError, ValueError) as exc:
        return _unavailable_regime(f"Macro regime file is invalid: {exc}")


def prepare_macro_regime(
    payload: dict[str, Any],
    today: date | None = None,
) -> dict[str, Any]:
    regime = deepcopy(payload)
    as_of = date.fromisoformat(str(regime["as_of"]))
    scenarios = regime["scenarios"]
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("at least one macro scenario is required")

    probability_total = sum(float(scenario["probability"]) for scenario in scenarios)
    if abs(probability_total - 1.0) > 0.0001:
        raise ValueError("macro scenario probabilities must total 1.0")

    sectors = sorted(
        {
            str(sector)
            for scenario in scenarios
            for sector in scenario["sector_impacts"]
        }
    )
    max_impact = float(regime.get("model", {}).get("maximum_scenario_impact", 10))
    overlays = []
    notes = regime.get("sector_notes") or {}
    for sector in sectors:
        contributions = []
        adjustment = 0.0
        for scenario in scenarios:
            impact = float(scenario["sector_impacts"].get(sector, 0))
            if abs(impact) > max_impact:
                raise ValueError(
                    f"{sector} impact in {scenario.get('id', 'scenario')} exceeds {max_impact}"
                )
            weighted = float(scenario["probability"]) * impact
            adjustment += weighted
            contributions.append(
                {
                    "scenario_id": scenario["id"],
                    "impact": impact,
                    "weighted_impact": round(weighted, 2),
                }
            )
        overlays.append(
            {
                "sector": sector,
                "adjustment": round(adjustment, 1),
                "rationale": str(notes.get(sector) or "Scenario-weighted macro sensitivity."),
                "contributions": contributions,
            }
        )

    current_date = today or date.today()
    stale_after_days = int(
        regime.get("model", {}).get("stale_after_days", DEFAULT_STALE_AFTER_DAYS)
    )
    age_days = max(0, (current_date - as_of).days)
    regime["age_days"] = age_days
    regime["stale_after_days"] = stale_after_days
    regime["is_stale"] = age_days > stale_after_days
    regime["active"] = bool(regime.get("enabled", True)) and not regime["is_stale"]
    regime["sector_overlays"] = overlays
    regime["probability_total"] = round(probability_total, 4)
    return regime


def apply_macro_regime(
    companies: list[dict[str, Any]],
    regime: dict[str, Any],
) -> None:
    overlay_by_sector = {
        item["sector"]: item for item in regime.get("sector_overlays") or []
    }
    for company in companies:
        company.update(
            {
                "fundamental_model_score": company.get("sector_model_score"),
                "macro_adjustment": None,
                "macro_score": None,
                "macro_rank": None,
                "fundamental_global_rank": None,
                "macro_rank_change": None,
                "macro_percentile": None,
                "macro_cohort_size": 0,
                "macro_rank_eligible": False,
                "macro_overlay_as_of": regime.get("as_of"),
                "macro_overlay_rationale": None,
            }
        )

    if not regime.get("active"):
        return

    eligible = []
    for company in companies:
        overlay = overlay_by_sector.get(str(company.get("sector") or ""))
        score = company.get("sector_model_score")
        if overlay is None or score is None:
            continue
        adjustment = float(overlay["adjustment"])
        company["macro_adjustment"] = round(adjustment, 1)
        company["macro_score"] = round(max(0.0, min(100.0, float(score) + adjustment)), 1)
        company["macro_overlay_rationale"] = overlay["rationale"]
        if company.get("sector_model_rank_eligible"):
            eligible.append(company)

    fundamental_order = sorted(
        eligible,
        key=lambda item: (-item["sector_model_score"], item["ticker"]),
    )
    for rank, company in enumerate(fundamental_order, start=1):
        company["fundamental_global_rank"] = rank

    eligible.sort(key=lambda item: (-item["macro_score"], item["ticker"]))
    size = len(eligible)
    for rank, company in enumerate(eligible, start=1):
        company["macro_rank"] = rank
        company["macro_rank_change"] = company["fundamental_global_rank"] - rank
        company["macro_cohort_size"] = size
        company["macro_percentile"] = (
            round((size - rank) / (size - 1) * 100, 1) if size > 1 else 100.0
        )
        company["macro_rank_eligible"] = True


def _unavailable_regime(reason: str) -> dict[str, Any]:
    return {
        "enabled": False,
        "active": False,
        "is_stale": False,
        "status": "unavailable",
        "reason": reason,
        "scenarios": [],
        "sector_overlays": [],
        "sources": [],
    }

from __future__ import annotations

from typing import Any


SECTOR_MODEL_VERSION = "provisional_sector_v2"
MINIMUM_COHORT_SIZE = 5
MINIMUM_MODEL_COVERAGE = 0.70

SECTOR_WEIGHTS: dict[str, dict[str, float]] = {
    "Energy": {
        "valuation": 20,
        "moat_evidence": 10,
        "fcf_quality": 25,
        "growth_revisions": 10,
        "pricing_power": 0,
        "downside_quality": 20,
        "cross_source_consensus": 5,
        "momentum": 10,
    },
    "Materials": {
        "valuation": 20,
        "moat_evidence": 10,
        "fcf_quality": 25,
        "growth_revisions": 10,
        "pricing_power": 0,
        "downside_quality": 20,
        "cross_source_consensus": 5,
        "momentum": 10,
    },
    "Consumer Staples": {
        "valuation": 20,
        "moat_evidence": 20,
        "fcf_quality": 20,
        "growth_revisions": 10,
        "pricing_power": 15,
        "downside_quality": 5,
        "cross_source_consensus": 5,
        "momentum": 5,
    },
    "Healthcare": {
        "valuation": 15,
        "moat_evidence": 20,
        "fcf_quality": 10,
        "growth_revisions": 25,
        "pricing_power": 10,
        "downside_quality": 10,
        "cross_source_consensus": 5,
        "momentum": 5,
    },
    "Biotechnology": {
        "valuation": 10,
        "moat_evidence": 10,
        "fcf_quality": 5,
        "growth_revisions": 25,
        "pricing_power": 0,
        "downside_quality": 20,
        "cross_source_consensus": 20,
        "momentum": 10,
    },
    "Industrials": {
        "valuation": 15,
        "moat_evidence": 20,
        "fcf_quality": 15,
        "growth_revisions": 20,
        "pricing_power": 10,
        "downside_quality": 10,
        "cross_source_consensus": 5,
        "momentum": 5,
    },
    "Utilities": {
        "valuation": 20,
        "moat_evidence": 15,
        "fcf_quality": 0,
        "growth_revisions": 15,
        "pricing_power": 0,
        "downside_quality": 30,
        "cross_source_consensus": 10,
        "momentum": 10,
    },
}

SECTOR_LIMITATIONS = {
    "Energy": "Does not yet include reserve life, lifting costs, decline rates, or commodity-price sensitivity.",
    "Materials": "Does not yet include reserve grades, cost-curve position, mine life, or commodity-price sensitivity.",
    "Consumer Staples": "Does not yet separate price, volume, mix, and retailer concentration.",
    "Healthcare": "Does not yet model patent cliffs, pipeline probability, reimbursement, or trial catalysts.",
    "Biotechnology": (
        "Financial and market-evidence screen only. It does not yet score pipeline probability, "
        "clinical catalysts, patent life, regulatory risk, partnerships, or cash runway."
    ),
    "Industrials": "Does not yet include backlog quality, book-to-bill, cycle exposure, or program concentration.",
    "Utilities": "Generic FCF and pricing-power scores are excluded; rate-base growth, allowed ROE, regulation, and funding needs are not yet modeled.",
}

SECTOR_BENCHMARKS = {
    "Biotechnology": ["IBB", "XBI"],
}


def weighted_sector_score(
    categories: dict[str, float | None],
    weights: dict[str, float],
) -> tuple[float | None, float]:
    total_weight = sum(weight for weight in weights.values() if weight > 0)
    available = [
        (float(categories[name]), weight)
        for name, weight in weights.items()
        if weight > 0 and categories.get(name) is not None
    ]
    available_weight = sum(weight for _score, weight in available)
    coverage = available_weight / total_weight if total_weight else 0
    if not available_weight:
        return None, round(coverage, 4)
    score = sum(value * weight for value, weight in available) / available_weight
    return round(score, 1), round(coverage, 4)


def apply_sector_models(
    companies: list[dict[str, Any]],
    minimum_cohort_size: int = MINIMUM_COHORT_SIZE,
    minimum_coverage: float = MINIMUM_MODEL_COVERAGE,
    sector_weights: dict[str, dict[str, float]] | None = None,
    model_version: str = SECTOR_MODEL_VERSION,
) -> None:
    configured_weights = sector_weights or SECTOR_WEIGHTS
    cohorts: dict[str, list[dict[str, Any]]] = {}
    for company in companies:
        sector = str(company.get("sector") or "Unclassified")
        weights = configured_weights.get(sector)
        company.update(
            {
                "sector_model_version": model_version if weights else None,
                "sector_model_score": None,
                "sector_model_coverage": 0,
                "sector_model_rank": None,
                "sector_model_percentile": None,
                "sector_model_cohort_size": 0,
                "sector_model_rank_eligible": False,
                "sector_model_limitation": SECTOR_LIMITATIONS.get(sector),
            }
        )
        if not weights:
            continue
        score, coverage = weighted_sector_score(company.get("categories") or {}, weights)
        company["sector_model_score"] = score
        company["sector_model_coverage"] = coverage
        if score is not None and coverage >= minimum_coverage:
            cohorts.setdefault(sector, []).append(company)

    for cohort in cohorts.values():
        cohort.sort(key=lambda item: (-item["sector_model_score"], item["ticker"]))
        size = len(cohort)
        for company in cohort:
            company["sector_model_cohort_size"] = size
        if size < minimum_cohort_size:
            continue
        for rank, company in enumerate(cohort, start=1):
            company["sector_model_rank"] = rank
            company["sector_model_percentile"] = round((size - rank) / (size - 1) * 100, 1)
            company["sector_model_rank_eligible"] = True

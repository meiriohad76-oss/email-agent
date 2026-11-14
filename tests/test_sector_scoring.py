from email_article_analyzer.sector_scoring import SECTOR_WEIGHTS
from email_article_analyzer.sector_scoring import apply_sector_models
from email_article_analyzer.sector_scoring import weighted_sector_score


def _company(ticker, sector, score):
    return {
        "ticker": ticker,
        "sector": sector,
        "categories": {name: score for name in SECTOR_WEIGHTS[sector]},
    }


def test_utilities_model_ignores_generic_fcf_and_pricing_power():
    categories = {name: 50 for name in SECTOR_WEIGHTS["Utilities"]}
    categories["fcf_quality"] = 0
    categories["pricing_power"] = 100

    score, coverage = weighted_sector_score(categories, SECTOR_WEIGHTS["Utilities"])

    assert score == 50
    assert coverage == 1


def test_sector_score_reweights_missing_category_and_reports_coverage():
    weights = SECTOR_WEIGHTS["Energy"]
    categories = {name: 80 for name in weights}
    categories["fcf_quality"] = None

    score, coverage = weighted_sector_score(categories, weights)

    assert score == 80
    assert coverage == 0.75


def test_biotechnology_model_deemphasizes_fcf_and_excludes_pricing_power():
    weights = SECTOR_WEIGHTS["Biotechnology"]

    assert sum(weights.values()) == 100
    assert weights["growth_revisions"] == 25
    assert weights["cross_source_consensus"] == 20
    assert weights["downside_quality"] == 20
    assert weights["fcf_quality"] == 5
    assert weights["pricing_power"] == 0


def test_sector_rank_requires_five_eligible_companies():
    companies = [_company(f"U{index}", "Utilities", score) for index, score in enumerate((90, 80, 70, 60), 1)]
    apply_sector_models(companies)
    assert all(company["sector_model_rank"] is None for company in companies)

    companies.append(_company("U5", "Utilities", 50))
    apply_sector_models(companies)

    assert companies[0]["sector_model_rank"] == 1
    assert companies[0]["sector_model_percentile"] == 100
    assert companies[-1]["sector_model_rank"] == 5
    assert companies[-1]["sector_model_percentile"] == 0

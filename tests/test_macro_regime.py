from datetime import date

from email_article_analyzer.macro_regime import apply_macro_regime
from email_article_analyzer.macro_regime import prepare_macro_regime


def _regime():
    return {
        "enabled": True,
        "as_of": "2026-11-11",
        "model": {"maximum_scenario_impact": 10, "stale_after_days": 45},
        "sector_notes": {
            "Energy": "Inflation-sensitive cash flows.",
            "Healthcare": "Defensive cash flows.",
        },
        "scenarios": [
            {
                "id": "base",
                "probability": 0.75,
                "sector_impacts": {"Energy": 4, "Healthcare": 0},
            },
            {
                "id": "downside",
                "probability": 0.25,
                "sector_impacts": {"Energy": -4, "Healthcare": 4},
            },
        ],
    }


def test_prepare_macro_regime_probability_weights_sector_adjustments():
    regime = prepare_macro_regime(_regime(), today=date(2026, 11, 12))
    overlays = {item["sector"]: item for item in regime["sector_overlays"]}

    assert regime["active"] is True
    assert overlays["Energy"]["adjustment"] == 2.0
    assert overlays["Healthcare"]["adjustment"] == 1.0
    assert overlays["Energy"]["contributions"][0]["weighted_impact"] == 3.0


def test_apply_macro_regime_preserves_fundamentals_and_adds_cross_sector_rank():
    regime = prepare_macro_regime(_regime(), today=date(2026, 11, 12))
    companies = [
        {
            "ticker": "ENE",
            "sector": "Energy",
            "sector_model_score": 60.0,
            "sector_model_rank_eligible": True,
        },
        {
            "ticker": "HLT",
            "sector": "Healthcare",
            "sector_model_score": 61.0,
            "sector_model_rank_eligible": True,
        },
    ]

    apply_macro_regime(companies, regime)

    assert companies[0]["sector_model_score"] == 60.0
    assert companies[0]["macro_score"] == 62.0
    assert companies[0]["macro_rank"] == 1
    assert companies[0]["fundamental_global_rank"] == 2
    assert companies[0]["macro_rank_change"] == 1
    assert companies[1]["macro_score"] == 62.0
    assert companies[1]["macro_rank"] == 2
    assert companies[1]["fundamental_global_rank"] == 1
    assert companies[1]["macro_rank_change"] == -1


def test_stale_macro_regime_is_not_applied():
    regime = prepare_macro_regime(_regime(), today=date(2027, 1, 1))
    companies = [
        {
            "ticker": "ENE",
            "sector": "Energy",
            "sector_model_score": 60.0,
            "sector_model_rank_eligible": True,
        }
    ]

    apply_macro_regime(companies, regime)

    assert regime["is_stale"] is True
    assert companies[0]["macro_score"] is None
    assert companies[0]["macro_rank"] is None

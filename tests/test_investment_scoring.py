from email_article_analyzer.investment_scoring import score_company_research


def test_score_company_research_combines_provider_evidence_without_imputing_missing_categories():
    records = [
        {
            "ticker": "TEST",
            "provider": "seeking_alpha",
            "rating_type": "valuation_metrics",
            "grade": "B+",
        },
        {
            "ticker": "TEST",
            "provider": "seeking_alpha",
            "rating_type": "profitability_metrics",
            "grade": "A",
            "metrics": [
                {
                    "metric": "Gross Profit Margin (TTM)",
                    "company": {"value": 48.0},
                    "difference_to_sector": {"value": 20.0},
                    "difference_to_five_year_average": {"value": 1.0},
                },
                {
                    "metric": "Levered FCF Margin (TTM)",
                    "company": {"value": 18.0},
                    "difference_to_sector": {"value": 30.0},
                },
            ],
        },
        {
            "ticker": "TEST",
            "provider": "investing_pro",
            "rating_type": "ratios",
            "categories": {
                "valuation_ratios": [
                    {"metric": "P/E RatioTTM", "company": {"value": 14}, "industry": {"value": 20}},
                ],
                "profitability": [
                    {"metric": "Gross marginTTM", "company": {"value": 48}, "industry": {"value": 35}},
                    {"metric": "Gross Margin5YA", "company": {"value": 47}, "industry": {"value": 34}},
                    {"metric": "Return on EquityTTM", "company": {"value": 25}, "industry": {"value": 15}},
                ],
            },
        },
        {
            "ticker": "TEST",
            "provider": "investing_pro",
            "rating_type": "forecast",
            "rating": "Buy",
            "fair_value_upside_pct": 15,
        },
    ]

    result = score_company_research(records)

    assert result["ticker"] == "TEST"
    assert result["categories"]["valuation"]["score"] > 70
    assert result["categories"]["moat_evidence"]["score"] > 70
    assert result["categories"]["pricing_power"]["score"] > 50
    assert result["categories"]["growth_revisions"]["score"] is None
    assert result["score_coverage"] < 0.70
    assert result["comparable_rank_eligible"] is False


def test_score_company_research_labels_moat_as_derived_evidence():
    result = score_company_research([])

    assert result["composite_score"] is None
    assert result["score_coverage"] == 0
    assert "derived evidence" in result["methodology_note"].lower()


def test_zacks_rank_record_supplies_style_scores_when_detailed_estimates_are_unavailable():
    result = score_company_research(
        [
            {
                "ticker": "DANOY",
                "provider": "seeking_alpha",
                "rating_type": "growth_metrics",
                "grade": "B",
            },
            {
                "ticker": "DANOY",
                "provider": "zacks",
                "rating_type": "rank",
                "zacks_rank": 4,
                "style_scores": {"value": "C", "growth": "B", "momentum": "B", "vgm": "B"},
            },
        ]
    )

    evidence = result["categories"]["growth_revisions"]["evidence"]
    assert any(item["label"] == "Zacks growth style" for item in evidence)

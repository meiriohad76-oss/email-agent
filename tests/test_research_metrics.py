from email_article_analyzer.research_metrics import (
    parse_investing_research,
    parse_seeking_alpha_research,
    parse_seeking_alpha_options,
    parse_zacks_detailed_estimates,
    parse_zacks_insider_transactions,
    parse_zacks_options,
)


def test_parse_zacks_insider_transactions_preserves_codes_and_classification():
    text = """
    EQUITY_INSIDER_TXN {"insider_name":"Delaet Ingrid","relationship":"Chief Regulatory Officer","transaction_date":"2026-07-10","transaction_code":"DS","owner_type":"Indirect","security_type":"COM","shares":"4,367","price":"181.02","transaction_value":"790,514","shares_owned_after":"16,225"}
    EQUITY_INSIDER_TXN {"insider_name":"Delaet Ingrid","relationship":"Chief Regulatory Officer","transaction_date":"2026-07-10","transaction_code":"AM","owner_type":"Indirect","security_type":"COM","shares":"4,367","price":"106.02","transaction_value":"462,989","shares_owned_after":"20,592"}
    EQUITY_INSIDER_TXN {"insider_name":"Sanjay Keswani","relationship":"Chief Medical Officer","transaction_date":"2026-06-02","transaction_code":"DF","owner_type":"Indirect","security_type":"COM","shares":"1,733","price":"154.84","transaction_value":"268,338","shares_owned_after":"1,479"}
    """

    record = parse_zacks_insider_transactions("NBIX", text)[0]

    assert record["transaction_count"] == 3
    assert record["verification_status"] == "requires_sec_form4_cross_check"
    sale, exercise, withholding = record["transactions"]
    assert sale["classification"] == "open_market_sale"
    assert sale["transaction_value"] == 790514.0
    assert exercise["classification"] == "option_exercise_or_conversion"
    assert withholding["classification"] == "tax_or_exercise_withholding"


def test_parse_zacks_insider_transactions_rejects_invalid_rows():
    text = 'EQUITY_INSIDER_TXN {"insider_name":"Unknown","transaction_date":"2026-07-10","transaction_code":"XX"}'
    assert parse_zacks_insider_transactions("NBIX", text) == []


def test_parse_zacks_insider_transactions_maps_structured_table_headers():
    text = (
        'EQUITY_RESEARCH_TABLE {"provider":"zacks","data_type":"insider_transactions",'
        '"headers":["Filer\u0027s name","Relationship /Title","Tran Date","Tran Type",'
        '"Owner Type","Security Type","Shares","Price($)","Tran Value($)","Total Shares Owned"],'
        '"rows":[["Delaet Ingrid","Officer","7/10/26","DS","Indirect","COM",'
        '"4,367","181.02","790,514","16,225"]]}\n'
    )

    record = parse_zacks_insider_transactions("NBIX", text)[0]

    assert record["transactions"][0]["transaction_date"] == "2026-07-10"
    assert record["transactions"][0]["transaction_value"] == 790514.0


def test_parse_zacks_greeks_montage_preserves_iv_greeks_and_open_interest():
    text = """
    Last $166.80
    Updated Jul 31, 2026 04:00 PM ET
    Aug 21 CALLS / 19 Days to Expiration (Aug 21 2026)
    Strike Bid Ask Last Chng High Low Vol Open Int Imp Vol Theo Val Delta Gam Theta Vega Rho
    165
    \t5.10\t7.40\t6.40\t-16.80\t10.70\t5.80\t17\t57\t34.984\t6.18\t0.581\t0.031\t-0.1404\t0.1487\t0.0473
    Aug 21 PUTS / 19 Days to Expiration (Aug 21 2026)
    Strike Bid Ask Last Chng High Low Vol Open Int Imp Vol Theo Val Delta Gam Theta Vega Rho
    165
    \t2.60\t4.90\t4.30\t1.83\t4.96\t2.50\t4\t16\t35.072\t4.08\t-0.421\t0.031\t-0.1249\t0.1487\t-0.0385
    """

    record = parse_zacks_options("NBIX", "greeks_montage", text)[0]

    assert record["spot_price"] == 166.8
    assert record["as_of"] == "2026-07-31"
    assert record["rows"][0]["expiration"] == "2026-08-21"
    assert record["rows"][0]["implied_volatility_pct"] == 34.984
    assert record["rows"][0]["open_interest"] == 57.0
    assert record["rows"][1]["delta"] == -0.421


def test_structured_dynamic_table_fallback_preserves_visible_zacks_rows():
    text = (
        'EQUITY_RESEARCH_TABLE {"provider":"zacks","data_type":"options_chain",'
        '"headers":["Strike","Last","Volume"],'
        '"rows":[["100","4.20","310"],["105","2.10","90"]]}\n'
    )

    record = parse_zacks_options("NBIX", "options_chain", text)[0]

    assert record["rating"] == "2 visible table rows"
    assert record["rows"][0] == {"Strike": "100", "Last": "4.20", "Volume": "310"}


def test_structured_dynamic_table_rejects_header_echo_as_data():
    text = (
        'EQUITY_RESEARCH_TABLE {"provider":"zacks","data_type":"options_chain",'
        '"headers":["Strike","Last","Volume"],'
        '"rows":[["Strike","Last","Volume"]]}\n'
    )

    assert parse_zacks_options("ABBNY", "options_chain", text) == []


def test_parse_seeking_alpha_options_quote_and_open_interest_rows():
    text = """
    NBIX Summary $166.80 -18.70 4:00 PM 07/31/26
    Calls
    Strike\tPrice\tChange\t% Change\tBid\tAsk\tVolume\tOpen Int\tLast Trade Time
    Strike\tPrice\tChange\t% Change\tBid\tAsk\tVolume\tOpen Int\tLast Trade Time
    165.00
    6.40
    -16.80
    -72.41%
    5.10
    7.40
    17
    57
    3:54 PM 07/31/26
    Puts
    Strike\tPrice\tChange\t% Change\tBid\tAsk\tVolume\tOpen Int\tLast Trade Time
    Strike\tPrice\tChange\t% Change\tBid\tAsk\tVolume\tOpen Int\tLast Trade Time
    165.00
    4.30
    1.83
    74.09%
    2.60
    4.90
    4
    16
    11:32 AM 07/31/26
    Options data delayed by 15 minutes
    """

    record = parse_seeking_alpha_options("NBIX", text)[0]

    assert record["spot_price"] == 166.8
    assert record["as_of"] == "2026-07-31"
    assert [row["contract_type"] for row in record["rows"]] == ["call", "put"]
    assert record["rows"][0]["open_interest"] == 57.0


def test_parse_investing_options_combined_quote_table():
    text = """
    Neurocrine Option Chain
    Expiration Date: Aug 21, 2026 Sep 18, 2026
    Jul 31, 2026 07:59PM GMT
    Last Chg. Bid Ask Vol Strike Last Chg. Bid Ask Vol
    4.17\t-70.43%\t3.2\t4.5\t40\t170.00\t7\t0%\t5.8\t8.5\t5
    166.91
    Price @ Jul 31, 2026 07:59PM GMT
    """

    record = parse_investing_research("NBIX", "options_chain", text)[0]

    assert record["spot_price"] == 166.91
    assert record["as_of"] == "2026-07-31"
    assert record["rows"][0]["contract_type"] == "call"
    assert record["rows"][1]["contract_type"] == "put"
    assert record["rows"][1]["ask"] == 8.5


def test_parse_seeking_alpha_factor_metrics():
    text = """
    XOM Profitability Grade
    A+
    Type
    Sector Relative Grade XOM Sector Median % Diff. to Sector XOM 5Y Avg. % Diff. to 5Y Avg.
    Gross Profit Margin (TTM)
    C
    29.77%
    36.92%
    -19.37%
    31.62%
    -5.85%
    Levered FCF Margin (TTM)
    B+
    15.20%
    10.00%
    52.00%
    14.10%
    7.80%
    *Grades are relative to the Energy sector
    """

    record = parse_seeking_alpha_research("XOM", "profitability", text)[0]

    assert record["grade"] == "A+"
    assert record["score"] == 13
    assert record["metrics"][0]["company"]["value"] == 29.77
    assert record["metrics"][1]["metric"] == "Levered FCF Margin (TTM)"


def test_parse_seeking_alpha_news_listing_preserves_links_and_classifies_events():
    text = """
    EQUITY_NEWS_ITEM {"content_type":"news","title":"NBIX raises 2026 revenue guidance after earnings beat","url":"https://seekingalpha.com/news/1-test#tracking","published_at":"Thu, Jul 30","author":"SA News","author_rating":"","excerpt":"Revenue beat consensus and management lifted its outlook."}
    EQUITY_NEWS_ITEM {"content_type":"news","title":"FDA grants orphan status to NBIX asset","url":"https://seekingalpha.com/news/2-test","published_at":"Thu, May 07","author":"SA News","author_rating":"","excerpt":"The designation applies to a development-stage therapy."}
    EQUITY_NEWS_ITEM {not-json}
    """

    record = parse_seeking_alpha_research("NBIX", "news", text)[0]

    assert record["rating_type"] == "news_items"
    assert record["item_count"] == 2
    assert record["items"][0]["url"] == "https://seekingalpha.com/news/1-test"
    assert record["items"][0]["event_type"] == "earnings"
    assert record["items"][1]["event_type"] == "regulatory"


def test_parse_investing_analysis_listing_keeps_author_rating_and_deduplicates_urls():
    text = """
    EQUITY_NEWS_ITEM {"content_type":"analysis","title":"Neurocrine: pipeline upside is underappreciated","url":"https://www.investing.com/analysis/nbix-1","published_at":"Jul 31, 2026","author":"Research Desk","author_rating":"Buy","excerpt":"The article argues that consensus omits two pipeline assets."}
    EQUITY_NEWS_ITEM {"content_type":"analysis","title":"Duplicate","url":"https://www.investing.com/analysis/nbix-1#comments","published_at":"Jul 31, 2026","author":"Research Desk","author_rating":"Buy","excerpt":"Duplicate card."}
    """

    record = parse_investing_research("NBIX", "analysis", text)[0]

    assert record["rating_type"] == "analysis_items"
    assert record["item_count"] == 1
    assert record["items"][0]["author"] == "Research Desk"
    assert record["items"][0]["author_rating"] == "Buy"


def test_parse_seeking_alpha_factor_metrics_with_current_tabular_header():
    text = """
    Valuation Measures
    REGN Valuation Grade
    F
    Type\tGrade\tREGN\tSector Median\t% Diff. to Sector\tREGN 5Y Avg.\t% Diff. to 5Y Avg.
    P/E Non-GAAP (TTM)
    B
    16.22
    18.61
    -12.85%
    15.45
    4.98%
    P/E GAAP (FWD)
    B+
    18.09
    25.51
    -29.06%
    19.84
    -8.82%
    *Grades are relative to the Health Care sector
    """

    record = parse_seeking_alpha_research("REGN", "valuation", text)[0]

    assert record["grade"] == "F"
    assert len(record["metrics"]) == 2
    assert record["metrics"][0]["company"]["value"] == 16.22
    assert record["metrics"][1]["grade"] == "B+"


def test_parse_seeking_alpha_ungraded_foreign_listing_metrics():
    text = """
    ANCTF Growth Grade
    -
    RATING: NOT COVERED
    Type
    Sector Relative Grade ANCTF Sector Median % Diff. to Sector ANCTF 5Y Avg. % Diff. to 5Y Avg.
    Revenue Growth (YoY)
    -
    RATING: NOT COVERED
    5.01%
    10.13%
    -50.54%
    4.96%
    1.01%
    EPS Diluted Growth (YoY)
    -
    RATING: NOT COVERED
    24.35%
    3.27%
    644.65%
    6.67%
    265.07%
    *Grades are relative to the Consumer Staples sector
    """

    record = parse_seeking_alpha_research("ANCTF", "growth", text)[0]

    assert record.get("grade") is None
    assert record["rating"] == "Growth metrics"
    assert len(record["metrics"]) == 2
    assert record["metrics"][0]["company"]["value"] == 5.01
    assert record["metrics"][1]["sector_median"]["value"] == 3.27


def test_parse_seeking_alpha_statement_from_accessible_line_layout():
    text = """
    WMT Income Statement
    In Millions of USD
    TTM
    Jan 31, 2026
    Jan 31, 2025
    Total Revenues
    713,150
    680,985
    648,125
    Operating Income
    29,450
    27,012
    26,321
    Net Income
    22,100
    19,436
    15,511
    """

    record = parse_seeking_alpha_research("WMT", "income_statement", text)[0]

    assert record["periods"] == ["TTM", "Jan 31, 2026", "Jan 31, 2025"]
    assert record["rows"][0]["metric"] == "Total Revenues"
    assert record["rows"][0]["values"]["TTM"]["value"] == 713150.0
    assert record["statement_currency_label"] == "USD"


def test_parse_seeking_alpha_peers_from_current_chart_layout():
    text = """
    Key Stats Comparison
    Metric:
    Price Return
    REGN
    39.81%
    Price Return
    AMGN
    30.52%
    Price Return
    ALNY
    -47.60%
    Price Return
    REGN, AMGN and ALNY
    Line chart with 3 lines.
    """

    record = parse_seeking_alpha_research("REGN", "peers", text)[0]

    assert record["peer_symbols"] == ["REGN", "AMGN", "ALNY"]
    assert record["profile_metrics"]["Price Return"]["REGN"]["value"] == 39.81
    assert record["profile_metrics"]["Price Return"]["ALNY"]["value"] == -47.6


def test_parse_seeking_alpha_statement_with_price_chart_header_and_blank_cell():
    text = """
    SA_STATEMENT
    Line Item
    \t
    Price Chart\tTTM\tJan 2026\tFeb 2025\tFeb 2024
    Total Revenues\t\t113,102.0\t106,566.0\t107,412.0\t109,120.0
    Operating Income\t\t5,190.0\t5,566.0\t5,707.0\t5,372.0
    SA_DATA SSR_DATA.symbol.response.data.attributes.currency = USD
    """

    record = parse_seeking_alpha_research("TGT", "income_statement", text)[0]

    assert record["periods"] == ["TTM", "Jan 2026", "Feb 2025", "Feb 2024"]
    assert len(record["rows"]) == 2
    assert record["rows"][0]["values"]["TTM"]["value"] == 113102.0
    assert record["statement_currency_label"] == "USD"


def test_parse_investing_forecast_and_fair_value_models():
    text = """
    Advanced Equity Forecast
    Overall Consensus
    Buy
    25 Ratings
    10 Buy
    14 Hold
    1 Sell
    Analysts 12-Month Price Target
    Average 167.23
    (+6.53% Upside)
    Past 24 Months Low 130.00 High 185.00
    Fair Value Average 154.03 Downside -1.87% Uncertainty LOW
    Fair Value 15 models $94 $313 $154.03
    P/E Multiples $120.27
    10Y DCF EBITDA Exit $174.06
    """

    record = parse_investing_research("XOM", "forecast", text)[0]

    assert record["rating"] == "Buy"
    assert record["analyst_target_average"] == 167.23
    assert record["fair_value"] == 154.03
    assert record["fair_value_model_count"] == 15
    assert record["valuation_models"]["10Y DCF EBITDA Exit"] == 174.06


def test_parse_investing_forecast_treats_downside_as_negative_upside():
    text = """
    Advanced Equity Forecast
    Overall Consensus Hold
    Fair Value Average 90.00 Downside 12.50% Uncertainty MEDIUM
    """

    record = parse_investing_research("TEST", "forecast", text)[0]

    assert record["fair_value_upside_pct"] == -12.5


def test_parse_investing_company_vs_industry_ratios():
    text = """
    XOM Ratios
    Name Company Industry
    Valuation Ratios
    P/E RatioTTM
    Price to Free Cash FlowTTM
    26.43\t17.90
    49.11\t18.96
    Profitability
    Gross marginTTM
    Gross Margin5YA
    29.77%\t36.92%
    31.62%\t37.37%
    """

    record = parse_investing_research("XOM", "ratios", text)[0]

    valuation = record["categories"]["valuation_ratios"]
    assert valuation[1]["metric"] == "Price to Free Cash FlowTTM"
    assert valuation[1]["company"]["value"] == 49.11
    assert valuation[1]["industry"]["value"] == 18.96
    assert record["categories"]["profitability"][1]["metric"] == "Gross Margin5YA"


def test_parse_zacks_detailed_estimates_core_signals():
    text = """
    Detailed Earnings Estimates
    Current Quarter 3.80
    ABR 2.28
    Earnings ESP More Info 0.00%
    Current Year 11.39
    Next Year 10.90
    EPS (TTM) 6.39
    P/E (F1) 13.77
    Zacks Rank More Info Hold 3
    Zacks Industry Rank More Info Bottom 5% (235 out of 247)
    Zacks Sector Rank More Info Bottom 31% (11 out of 16)
    Style Scores More Info B Value | D Growth | D Momentum | C VGM
    """

    record = parse_zacks_detailed_estimates("XOM", text)[0]

    assert record["zacks_rank"] == 3
    assert record["style_scores"] == {
        "value": "B",
        "growth": "D",
        "momentum": "D",
        "vgm": "C",
    }
    assert record["forward_pe"] == 13.77
    assert record["industry_rank"] == "Bottom 5% (235 out of 247)"


def test_parse_zacks_four_column_tables_preserve_million_suffix_values():
    text = """
    Detailed Earnings Estimates
    Zacks Rank More Info Hold 3
    Sales Estimates
    Current Qtr (9/2026) Next Qtr (12/2026) Current Year (12/2026) Next Year (12/2027)
    Zacks Consensus Estimate 85.62M 93.20M 357.60M 458.22M
    # of Estimates 4 4 3 4
    Earnings Estimates
    Zacks Consensus Estimate 0.19 0.26 1.18 1.67
    Agreement - Estimate Revisions
    """

    record = parse_zacks_detailed_estimates("INOD", text)[0]

    assert record["sales_estimates"]["Zacks Consensus Estimate"]["current_quarter"]["value"] == 85620000.0
    assert record["sales_estimates"]["Zacks Consensus Estimate"]["next_quarter"]["value"] == 93200000.0
    assert record["earnings_estimates"]["Zacks Consensus Estimate"]["current_quarter"]["value"] == 0.19
    assert record["estimate_horizon_labels"] == {
        "current_quarter": "9/2026",
        "next_quarter": "12/2026",
        "current_year": "12/2026",
        "next_year": "12/2027",
    }


def test_parse_seeking_alpha_inod_estimates_current_layout_and_ssr_data():
    text = """
    SA_DATA SSR_DATA.estimatesSummary[0].estimates.6917.revenue_consensus_mean.1[0].effectivedate = 2026-08-07T18:54:24.000-04:00
    SA_DATA SSR_DATA.estimatesSummary[0].estimates.6917.revenue_consensus_mean.1[0].dataitemvalue = 359556500.0
    SA_DATA SSR_DATA.estimatesSummary[0].estimates.6917.revenue_consensus_mean.1[0].period.periodtypeid = annual
    SA_DATA SSR_DATA.estimatesSummary[0].estimates.6917.revenue_consensus_mean.1[0].period.fiscalyear = 2026
    SA_DATA SSR_DATA.estimatesSummary[0].estimates.6917.revenue_consensus_mean.1[0].period.periodenddate = 2026-12-31T00:00:00.000-05:00
    SA_DATA SSR_DATA.estimatesSummary[0].estimates.6917.eps_gaap_consensus_mean.1[0].dataitemvalue = 1.215
    SA_DATA SSR_DATA.estimatesSummary[0].estimates.6917.eps_gaap_consensus_mean.1[0].period.periodtypeid = annual
    SA_DATA SSR_DATA.estimatesSummary[0].estimates.6917.eps_gaap_consensus_mean.1[0].period.fiscalyear = 2026
    SA_DATA SSR_DATA.estimatesSummary[0].estimates.6917.eps_gaap_consensus_mean.1[0].period.periodenddate = 2026-12-31T00:00:00.000-05:00
    ANNUAL ESTIMATES SUMMARY
    CONSENSUS EPS ESTIMATES
    Fiscal Period Ending EPS Estimate YoY Growth Forward PE Low High # of Analysts
    Dec 2026 1.22 32.07% 52.92 1.06 1.32 4
    Dec 2027 1.69 39.36% 37.97 1.21 2.23 4
    CONSENSUS REVENUE ESTIMATES
    Fiscal Period Ending Revenue Estimate YoY Growth FWD Price/Sales Low High # of Analysts
    Dec 2026 359.56M 42.87% 6.15 352.49M 365.30M 4
    Dec 2027 460.04M 27.95% 4.81 429.94M 490.21M 4
    * EPS estimates are GAAP unless otherwise noted.
    """

    record = parse_seeking_alpha_research("INOD", "estimates", text)[0]

    assert record["extraction_method"] == "ssr_data_with_visible_table_enrichment"
    assert len(record["eps_estimates"]) == 2
    assert record["eps_estimates"][0]["estimate"]["value"] == 1.215
    assert record["eps_estimates"][0]["display_estimate"]["value"] == 1.22
    assert record["eps_estimates"][0]["forward_multiple"]["value"] == 52.92
    assert record["eps_estimates"][1]["analyst_count"] == 4
    assert len(record["revenue_estimates"]) == 2
    assert record["revenue_estimates"][0]["estimate"]["value"] == 359556500.0
    assert record["revenue_estimates"][1]["forward_multiple"]["value"] == 4.81


def test_parse_seeking_alpha_estimates_supports_ssr_only_fallback():
    text = """
    SA_DATA SSR_DATA.estimatesSummary[0].estimates.99.eps_normalized_consensus_mean.1[0].dataitemvalue = 2.5
    SA_DATA SSR_DATA.estimatesSummary[0].estimates.99.eps_normalized_consensus_mean.1[0].period.periodtypeid = annual
    SA_DATA SSR_DATA.estimatesSummary[0].estimates.99.eps_normalized_consensus_mean.1[0].period.fiscalyear = 2028
    SA_DATA SSR_DATA.estimatesSummary[0].estimates.99.eps_normalized_consensus_mean.1[0].period.periodenddate = 2028-06-30T00:00:00.000-04:00
    """

    record = parse_seeking_alpha_research("TEST", "estimates", text)[0]

    assert record["extraction_method"] == "ssr_data"
    assert record["eps_estimates"][0]["period"] == "Jun 2028"
    assert record["eps_estimates"][0]["estimate_basis"] == "normalized"
    assert record["eps_estimates"][0]["estimate"]["value"] == 2.5


def test_parse_seeking_alpha_inod_revisions_current_layout_and_ssr_data():
    text = """
    SA_DATA SSR_DATA.revisions.revisions.6917.revenue_consensus_mean.1[0].numanalysts = 4
    SA_DATA SSR_DATA.revisions.revisions.6917.revenue_consensus_mean.1[0].numanalystsup = 3
    SA_DATA SSR_DATA.revisions.revisions.6917.revenue_consensus_mean.1[0].numanalystsnochange = 1
    SA_DATA SSR_DATA.revisions.revisions.6917.revenue_consensus_mean.1[0].numanalystsdown = 0
    ANNUAL ESTIMATES REVISIONS
    Upcoming Fiscal Year End - Revisions for Last 3 Months
    EPS # of Up Revisions 2
    EPS # of Down Revisions 0
    Revenue # of Up Revisions 3
    Revenue # of Down Revisions 0
    CONSENSUS EPS REVISION TREND
    Fiscal Period Ending EPS Estimate YoY Growth 1M Trend 3M Trend 6M Trend
    Dec 2026 1.22 32.07% 12.55% 12.55% 8.53%
    Dec 2027 1.69 39.36% 2.11% 5.14% 30.25%
    CONSENSUS REVENUE REVISION TREND
    Fiscal Period Ending Revenue Estimate YoY Growth 1M Trend 3M Trend 6M Trend
    Dec 2026 $359.56M 42.87% 0.71% 0.71% 14.77%
    Dec 2027 $460.04M 27.95% 0.40% 1.29% 49.85%
    Seeking Alpha - Power to Investors
    """

    record = parse_seeking_alpha_research("INOD", "revisions", text)[0]

    assert record["revision_counts_3m"] == {
        "eps_up": 2,
        "eps_down": 0,
        "revenue_up": 3,
        "revenue_down": 0,
    }
    assert record["structured_revision_snapshot"]["revenue_analyst_count"] == 4
    assert record["score"] == 5
    assert len(record["eps_revision_trend"]) == 2
    assert record["eps_revision_trend"][0]["trend_3m"]["value"] == 12.55
    assert record["revenue_revision_trend"][1]["trend_6m"]["value"] == 49.85

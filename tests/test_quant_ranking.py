from email_article_analyzer.rating_enrichment import parse_seeking_alpha_quant_ranking, parse_seeking_alpha_ratings

PAGE = """QUANT RATING HISTORY
Date\tPrice\tQuant Rating\tQuant Score\tValuation\tGrowth\tProfitability\tMomentum\tEPS Rev.\t

11/14/2026\t123.41\t
HOLD
\t
RATING: HOLD
3.36
\t
B
\t
B+
\t
A+
\t
D+
\t
B-
\t
11/13/2026\t125.35\t
STRONG
BUY
\t
RATING: STRONG BUY
4.61
\t
B
\t
B+
\t
A+
\t
D+
\t
B-
\t
QUANT RANKING
Sector
Information Technology
Industry
Systems Software
Ranked Overall
1136 out of 4299
Ranked in Sector
167 out of 540
Ranked in Industry
24 out of 45
"""


def test_ranking_and_history_parsed():
    r = parse_seeking_alpha_quant_ranking("ORCL", PAGE)
    assert r["rating_type"] == "quant_ranking" and r["rank_sector"] == 167 and r["total_sector"] == 540
    assert r["rank_industry"] == 24 and r["sector"] == "Information Technology" and r["industry"] == "Systems Software"
    assert r["score"] == round((1 - 166 / 540) * 100, 1)
    h = r["history"]
    assert h[0] == {"date": "2026-11-14", "price": 123.41, "rating": "Hold", "score": 3.36, "valuation": "B", "growth": "B+",
                    "profitability": "A+", "momentum": "D+", "eps_revisions": "B-"}
    assert h[1]["rating"] == "Strong Buy" and h[1]["score"] == 4.61


def test_included_in_ratings_parse_and_absent_page_ignored():
    assert any(s["rating_type"] == "quant_ranking" for s in parse_seeking_alpha_ratings("ORCL", PAGE))
    assert parse_seeking_alpha_quant_ranking("X", "nothing here") is None

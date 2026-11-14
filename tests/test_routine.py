from email_article_analyzer.routine import build_email_body
from email_article_analyzer.routine import diff_snapshots
from email_article_analyzer.routine import split_recommendations


def test_diff_reports_stance_target_added_and_dropped_tickers():
    previous = {
        "ORCL": {"stance": "hold", "confidence": 0.8, "target_price": 150.0},
        "MSFT": {"stance": "buy_watch", "confidence": 0.9, "target_price": None},
    }
    current = {
        "ORCL": {"stance": "buy_watch", "confidence": 0.8, "target_price": 175.0},
        "NVDA": {"stance": "hold", "confidence": 0.75, "target_price": None},
    }

    changes = diff_snapshots(previous, current)

    assert changes["stance"] == ["ORCL: hold -> buy_watch"]
    assert changes["target"] == ["ORCL: 150 -> 175"]
    assert changes["added"] == ["NVDA"]
    assert changes["dropped"] == ["MSFT"]


def test_diff_without_previous_snapshot_reports_nothing():
    current = {"ORCL": {"stance": "hold", "confidence": 0.8, "target_price": None}}

    changes = diff_snapshots(None, current)

    assert all(items == [] for items in changes.values())


def test_recommendations_need_seventy_percent_for_a_call():
    snapshot = {
        "ORCL": {"stance": "buy_watch", "confidence": 0.70, "target_price": 175.0},
        "MSFT": {"stance": "sell_watch", "confidence": 0.69, "target_price": None},
        "NVDA": {"stance": "hold", "confidence": 0.9, "target_price": None},
        "AMD": {"stance": "unclear", "confidence": 0.95, "target_price": None},
    }

    actionable, watch = split_recommendations(snapshot)

    assert [line.split(":")[0] for line in actionable] == ["HOLD NVDA", "BUY ORCL"]
    assert [line.split(":")[0] for line in watch] == ["AMD", "MSFT"]


def test_first_report_says_there_is_no_baseline():
    body = build_email_body(
        run_id=7,
        changes={"stance": [], "target": [], "added": [], "dropped": []},
        news=[],
        actionable=[],
        watch=[],
        has_baseline=False,
    )

    assert "First routine report" in body
    assert "No actionable calls this run." in body

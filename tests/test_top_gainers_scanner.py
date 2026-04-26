import pandas as pd

from top_gainers_scanner import (
    aggregate_symbol_counts,
    build_daily_rankings,
    build_html_dashboard,
)


def make_prices():
    dates = pd.to_datetime(["2026-04-20", "2026-04-21", "2026-04-22"])
    return {
        "AAA": pd.DataFrame({"Close": [100.0, 110.0, 111.0]}, index=dates),
        "BBB": pd.DataFrame({"Close": [100.0, 106.0, 120.0]}, index=dates),
        "CCC": pd.DataFrame({"Close": [100.0, 103.0, 103.5]}, index=dates),
    }


def test_build_daily_rankings_orders_by_daily_percent_change():
    rankings = build_daily_rankings(make_prices(), top_n=2)

    rows = rankings[pd.Timestamp("2026-04-21")]
    assert [row["symbol"] for row in rows] == ["AAA", "BBB"]
    assert rows[0]["rank"] == 1
    assert rows[0]["day_change_pct"] == 10.0
    assert rows[1]["day_change_pct"] == 6.0


def test_build_daily_rankings_uses_each_date_independently():
    rankings = build_daily_rankings(make_prices(), top_n=2)

    rows = rankings[pd.Timestamp("2026-04-22")]
    assert [row["symbol"] for row in rows] == ["BBB", "AAA"]
    assert rows[0]["rank"] == 1
    assert round(rows[0]["day_change_pct"], 2) == 13.21


def test_build_daily_rankings_ignores_stocks_below_minimum_close():
    dates = pd.to_datetime(["2026-04-20", "2026-04-21"])
    prices = {
        "LOW": pd.DataFrame({"Close": [40.0, 48.0]}, index=dates),
        "OK": pd.DataFrame({"Close": [100.0, 106.0]}, index=dates),
    }

    rankings = build_daily_rankings(prices, top_n=50, min_close=50.0)

    rows = rankings[pd.Timestamp("2026-04-21")]
    assert [row["symbol"] for row in rows] == ["OK"]


def test_aggregate_symbol_counts_counts_repeats_per_window():
    rankings = {
        pd.Timestamp("2026-04-20"): [
            {"symbol": "AAA", "rank": 1, "day_change_pct": 5.0, "close": 105.0},
            {"symbol": "BBB", "rank": 2, "day_change_pct": 3.0, "close": 103.0},
        ],
        pd.Timestamp("2026-04-21"): [
            {"symbol": "AAA", "rank": 1, "day_change_pct": 4.5, "close": 110.0},
            {"symbol": "CCC", "rank": 2, "day_change_pct": 4.2, "close": 104.2},
        ],
        pd.Timestamp("2026-04-22"): [
            {"symbol": "BBB", "rank": 1, "day_change_pct": 8.0, "close": 111.24},
        ],
    }

    result = aggregate_symbol_counts(
        rankings,
        make_prices(),
        windows={"1w": 2, "1m": 3, "3m": 3},
    )
    by_symbol = {row["symbol"]: row for row in result}

    assert by_symbol["AAA"]["top50_1w_count"] == 1
    assert by_symbol["AAA"]["top50_1m_count"] == 2
    assert by_symbol["BBB"]["top50_1w_count"] == 1
    assert by_symbol["BBB"]["top50_1m_count"] == 2
    assert by_symbol["CCC"]["top50_1m_count"] == 1


def test_aggregate_symbol_counts_counts_four_percent_up_days_by_window():
    rankings = build_daily_rankings(make_prices(), top_n=2)

    result = aggregate_symbol_counts(
        rankings,
        make_prices(),
        windows={"1w": 2, "1m": 3, "3m": 3},
    )
    by_symbol = {row["symbol"]: row for row in result}

    assert by_symbol["AAA"]["up4_1w_count"] == 1
    assert by_symbol["AAA"]["up4_1m_count"] == 1
    assert by_symbol["BBB"]["up4_1w_count"] == 2
    assert by_symbol["BBB"]["up4_1m_count"] == 2


def test_aggregate_symbol_counts_counts_down_days_more_than_four_percent():
    dates = pd.to_datetime(["2026-04-20", "2026-04-21", "2026-04-22", "2026-04-23"])
    prices = {
        "AAA": pd.DataFrame({"Close": [100.0, 95.0, 91.0, 92.0]}, index=dates),
        "BBB": pd.DataFrame({"Close": [100.0, 97.0, 92.0, 88.0]}, index=dates),
    }
    rankings = build_daily_rankings(prices, top_n=2)

    result = aggregate_symbol_counts(
        rankings,
        prices,
        windows={"1w": 2, "1m": 3, "3m": 3},
    )
    by_symbol = {row["symbol"]: row for row in result}

    assert by_symbol["AAA"]["down4_1w_count"] == 1
    assert by_symbol["AAA"]["down4_1m_count"] == 2
    assert by_symbol["BBB"]["down4_1w_count"] == 2
    assert by_symbol["BBB"]["down4_1m_count"] == 2
    assert by_symbol["BBB"]["down4_1w_days"][0]["day_change_pct"] == -5.15


def test_build_html_dashboard_uses_dashboard_style_and_down_columns():
    summary = [
        {
            "symbol": "AAA",
            "top50_1w_count": 1,
            "top50_1m_count": 2,
            "top50_3m_count": 3,
            "up4_1w_count": 1,
            "up4_1m_count": 2,
            "up4_3m_count": 3,
            "down4_1w_count": 0,
            "down4_1m_count": 1,
            "down4_3m_count": 2,
            "top50_1w_days": [{"date": "2026-04-23", "rank": 1, "day_change_pct": 6.5, "close": 106.5}],
            "top50_1m_days": [],
            "top50_3m_days": [],
            "up4_1w_days": [{"date": "2026-04-23", "day_change_pct": 6.5}],
            "up4_1m_days": [],
            "up4_3m_days": [],
            "down4_1w_days": [],
            "down4_1m_days": [{"date": "2026-04-20", "day_change_pct": -4.5}],
            "down4_3m_days": [],
        }
    ]
    latest_rows = [
        {"symbol": "AAA", "rank": 1, "day_change_pct": 6.5, "close": 106.5},
    ]
    html = build_html_dashboard(summary, latest_date="2026-04-24", latest_rankings=latest_rows)

    assert "<title>NSE Top Gainers Dashboard - 2026-04-24</title>" in html
    assert "Today's Top 50 Gainers" in html
    assert "sortable" in html
    assert "sortTable" in html
    assert "Down &gt;4% 1M" in html
    assert "NSE:AAA" in html
    assert "<td class=\"num\">106.50</td>" in html
    assert "<td class=\"num pos\">+6.50%</td>" in html

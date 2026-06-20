import pandas as pd

from top_gainers_scanner import (
    aggregate_symbol_counts,
    build_common_html_dashboard,
    build_common_period_gainers,
    build_cumulative_gainers,
    build_daily_rankings,
    build_html_dashboard,
    build_monthly_gainers,
    build_monthly_html_dashboard,
    build_weekly_gainers,
    build_weekly_html_dashboard,
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


def make_weekly_prices():
    dates = pd.to_datetime([
        "2026-04-20",
        "2026-04-21",
        "2026-04-22",
        "2026-04-23",
        "2026-04-24",
        "2026-04-27",
    ])
    return {
        "AAA": pd.DataFrame({"Close": [100.0, 102.0, 104.0, 108.0, 110.0, 125.0]}, index=dates),
        "BBB": pd.DataFrame({"Close": [100.0, 101.0, 103.0, 105.0, 106.0, 115.0]}, index=dates),
        "CCC": pd.DataFrame({"Close": [100.0, 98.0, 99.0, 101.0, 103.0, 104.0]}, index=dates),
    }


def make_period_prices():
    dates = pd.date_range("2026-01-01", periods=64, freq="B")
    return {
        "AAA": pd.DataFrame({"Close": [100.0 + i for i in range(64)]}, index=dates),
        "BBB": pd.DataFrame({"Close": [100.0 + (i * 0.5) for i in range(64)]}, index=dates),
        "CCC": pd.DataFrame({"Close": [100.0 + (i * 0.2) for i in range(64)]}, index=dates),
        "LOW": pd.DataFrame({"Close": [40.0 + (i * 0.05) for i in range(64)]}, index=dates),
    }


def make_period_summary(symbol):
    return [
        {
            "symbol": symbol,
            "top50_1w_count": 1,
            "top50_1m_count": 2,
            "top50_3m_count": 3,
            "up4_1w_count": 1,
            "up4_1m_count": 2,
            "up4_3m_count": 3,
            "down4_1w_count": 0,
            "down4_1m_count": 1,
            "down4_3m_count": 2,
            "gain_1w_pct": 10.0,
            "gain_1m_pct": 20.0,
            "gain_3m_pct": 40.0,
        }
    ]


def test_build_weekly_gainers_orders_by_cumulative_five_day_gain():
    rows = build_weekly_gainers(make_weekly_prices(), top_n=2, window_days=5)

    assert [row["symbol"] for row in rows] == ["AAA", "BBB"]
    assert rows[0]["rank"] == 1
    assert rows[0]["weekly_gain_pct"] == 25.0
    assert rows[0]["day_change_pct"] == 13.64
    assert rows[0]["start_close"] == 100.0
    assert rows[0]["close"] == 125.0
    assert rows[1]["weekly_gain_pct"] == 15.0


def test_build_weekly_gainers_skips_short_histories_and_low_latest_close():
    dates = pd.to_datetime([
        "2026-04-20",
        "2026-04-21",
        "2026-04-22",
        "2026-04-23",
        "2026-04-24",
        "2026-04-27",
    ])
    prices = {
        "SHORT": pd.DataFrame({"Close": [100.0, 105.0, 110.0]}, index=dates[:3]),
        "LOW": pd.DataFrame({"Close": [10.0, 11.0, 12.0, 13.0, 14.0, 20.0]}, index=dates),
        "OK": pd.DataFrame({"Close": [100.0, 101.0, 102.0, 103.0, 104.0, 120.0]}, index=dates),
    }

    rows = build_weekly_gainers(prices, top_n=50, window_days=5, min_close=50.0)

    assert [row["symbol"] for row in rows] == ["OK"]


def test_build_cumulative_gainers_uses_requested_gain_field_and_window():
    rows = build_cumulative_gainers(
        make_period_prices(),
        window_days=21,
        gain_field="monthly_gain_pct",
        top_n=2,
    )

    assert [row["symbol"] for row in rows] == ["AAA", "BBB"]
    assert rows[0]["rank"] == 1
    assert rows[0]["monthly_gain_pct"] == 14.79
    assert rows[0]["close"] == 163.0
    assert rows[0]["start_close"] == 142.0


def test_build_monthly_gainers_uses_twenty_one_sessions():
    rows = build_monthly_gainers(make_period_prices(), top_n=1)

    assert rows[0]["symbol"] == "AAA"
    assert rows[0]["monthly_gain_pct"] == 14.79


def test_build_common_period_gainers_returns_intersection_with_gain_2m():
    rows = build_common_period_gainers(make_period_prices(), top_n=3)

    assert [row["symbol"] for row in rows] == ["AAA", "BBB", "CCC"]
    assert rows[0]["rank"] == 1
    assert rows[0]["monthly_gain_pct"] == 14.79
    assert rows[0]["gain_2m_pct"] == 34.71
    assert rows[0]["gain_3m_pct"] == 63.0


def test_build_weekly_html_dashboard_uses_weekly_rows_with_existing_columns():
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
            "gain_1w_pct": 20.0,
            "gain_1m_pct": 30.0,
            "gain_3m_pct": 40.0,
        }
    ]
    weekly_rows = [
        {
            "symbol": "AAA",
            "rank": 1,
            "weekly_gain_pct": 20.0,
            "day_change_pct": -1.25,
            "start_close": 100.0,
            "close": 120.0,
        }
    ]

    html = build_weekly_html_dashboard(summary, latest_date="2026-04-27", weekly_rankings=weekly_rows)

    assert "<title>NSE Top Week Gainers Dashboard - 2026-04-27</title>" in html
    assert "Top 50 Weekly Gainers - sortable counts" in html
    assert "Gain 1W" in html
    assert "Gain 1M" in html
    assert "Gain 3M" in html
    assert "Down &gt;4% 3M" in html
    assert "NSE:AAA" in html
    assert "<td class=\"num neg\">-1.25%</td>" in html
    assert "<td class=\"num pos\">+20.00%</td>" in html


def test_build_monthly_html_dashboard_uses_monthly_gain_column():
    summary = make_period_summary("AAA")
    monthly_rows = [
        {
            "symbol": "AAA",
            "rank": 1,
            "monthly_gain_pct": 30.0,
            "day_change_pct": 2.0,
            "start_close": 100.0,
            "close": 130.0,
        }
    ]

    html = build_monthly_html_dashboard(summary, latest_date="2026-04-27", monthly_rankings=monthly_rows)

    assert "<title>NSE Top Month Gainers Dashboard - 2026-04-27</title>" in html
    assert "Top 50 Monthly Gainers - sortable counts" in html
    assert "<td class=\"num pos\">+30.00%</td>" in html


def test_build_common_html_dashboard_adds_gain_2m_and_common_rows():
    summary = [make_period_summary("AAA")[0], make_period_summary("BBB")[0]]
    common_rows = [
        {
            "symbol": "AAA",
            "rank": 1,
            "monthly_gain_pct": 30.0,
            "gain_2m_pct": 45.0,
            "gain_3m_pct": 60.0,
            "day_change_pct": -1.0,
            "start_close": 100.0,
            "close": 130.0,
        }
    ]

    html = build_common_html_dashboard(summary, latest_date="2026-04-27", common_rankings=common_rows)

    assert "<title>NSE Common Period Gainers Dashboard - 2026-04-27</title>" in html
    assert "Common 1M / 2M / 3M Gainers - sortable counts" in html
    assert "Gain 2M" in html
    assert "NSE:AAA" in html
    assert "NSE:BBB" not in html
    assert "<td class=\"num neg\">-1.00%</td>" in html
    assert "<td class=\"num pos\">+45.00%</td>" in html

#!/usr/bin/env python3
"""
NSE Top Gainers Repeat Scanner.

Builds daily top-50 gainers for the latest 1 week, 1 month, and 3 months,
then counts repeat appearances and >=4% up days per stock.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import os
import re
from html import escape
from typing import Any

import pandas as pd


REPO_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(REPO_DIR, "top_gainers")
SUMMARY_MD = os.path.join(OUT_DIR, "top_gainers_summary.md")
SUMMARY_CSV = os.path.join(OUT_DIR, "top_gainers_summary.csv")
SUMMARY_JSON = os.path.join(OUT_DIR, "top_gainers_summary.json")
DAILY_MD = os.path.join(OUT_DIR, "top_gainers_daily.md")
HTML_DASHBOARD = os.path.join(OUT_DIR, "top_gainers_dashboard.html")
WEEKLY_HTML_DASHBOARD = os.path.join(OUT_DIR, "top_week_gainers_dashboard.html")
MONTHLY_HTML_DASHBOARD = os.path.join(OUT_DIR, "top_month_gainers_dashboard.html")
COMMON_HTML_DASHBOARD = os.path.join(OUT_DIR, "top_common_gainers_dashboard.html")
WATCHLIST_FILE = os.path.join(OUT_DIR, "watchlist.json")
JOURNAL_DIR = os.path.join(OUT_DIR, "journal")

WINDOWS = {
    "1w": 5,
    "1m": 21,
    "3m": 63,
}


_CIRCUIT_EMOJI: dict[tuple[str, str], str] = {
    ("20", "10"): "🟨",
    ("10", "5"): "🟥",
    ("5", "10"): "🟩",
    ("10", "20"): "🟦",
}

_NSE_CSV_PATHS = [
    os.path.join(REPO_DIR, "nse.csv"),
    r"C:\Users\satya\.gemini\antigravity\scratch\circuit_dashboard\nse.csv",
]


def load_circuit_map() -> dict[str, str]:
    import csv as _csv
    from datetime import datetime as _dt

    for csv_path in _NSE_CSV_PATHS:
        if not os.path.exists(csv_path):
            continue
        try:
            latest: dict[str, dict] = {}
            with open(csv_path, encoding="utf-8-sig") as fh:
                for raw in _csv.DictReader(fh):
                    row = {k.strip(): v.strip() for k, v in raw.items()}
                    sym = row.get("SYMBOL", "")
                    dte = row.get("EFFECTIVE DATE", "")
                    frm = row.get("FROM", "")
                    to_ = row.get("TO", "")
                    if not sym or not dte:
                        continue
                    try:
                        parsed = _dt.strptime(dte, "%d-%b-%Y")
                    except ValueError:
                        continue
                    if sym not in latest or parsed > latest[sym]["parsed"]:
                        latest[sym] = {"parsed": parsed, "from": frm, "to": to_}
            circuit_map: dict[str, str] = {}
            for sym, d in latest.items():
                to_ = d["to"]
                if not to_ or to_ == "-":
                    continue
                emoji = _CIRCUIT_EMOJI.get((d["from"], to_), "")
                circuit_map[sym] = f"{to_}% {emoji}".strip()
            return circuit_map
        except Exception:
            continue

    # Fallback: NSE_Circuit_Limits.md (watchlist changes only)
    md_path = os.path.join(REPO_DIR, "NSE_Circuit_Limits.md")
    if not os.path.exists(md_path):
        return {}
    circuit_map = {}
    with open(md_path, encoding="utf-8") as fh:
        in_table = False
        for line in fh:
            line = line.strip()
            if line.startswith("| Date"):
                in_table = True
                continue
            if line.startswith("|---"):
                continue
            if in_table and line.startswith("|"):
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 5:
                    sym = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", parts[1]).replace("**", "").strip()
                    if sym and sym not in circuit_map:
                        circuit_map[sym] = parts[4]
            elif in_table and not line.startswith("|"):
                break
    return circuit_map


def _normalize_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "Close" not in df.columns:
        return pd.DataFrame(columns=["Close"])
    normalized = df[["Close"]].dropna().copy()
    normalized.index = pd.to_datetime([idx.date() for idx in normalized.index])
    return normalized[~normalized.index.duplicated(keep="last")]


def build_daily_rankings(
    price_by_symbol: dict[str, pd.DataFrame],
    top_n: int = 50,
    min_close: float = 50.0,
) -> dict[pd.Timestamp, list[dict[str, Any]]]:
    rows_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)

    for symbol, raw_df in price_by_symbol.items():
        df = _normalize_price_frame(raw_df)
        if len(df) < 2:
            continue
        changes = df["Close"].pct_change() * 100
        for trade_date, day_change_pct in changes.dropna().items():
            if pd.isna(day_change_pct):
                continue
            close = float(df.loc[trade_date, "Close"])
            if close < min_close:
                continue
            rows_by_date[pd.Timestamp(trade_date)].append(
                {
                    "symbol": symbol,
                    "day_change_pct": round(float(day_change_pct), 2),
                    "close": round(close, 2),
                }
            )

    rankings: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    for trade_date, rows in rows_by_date.items():
        positive_rows = [row for row in rows if row["day_change_pct"] > 0]
        sorted_rows = sorted(
            positive_rows,
            key=lambda row: (row["day_change_pct"], row["symbol"]),
            reverse=True,
        )[:top_n]
        for rank, row in enumerate(sorted_rows, start=1):
            row["rank"] = rank
        rankings[trade_date] = sorted_rows

    return dict(sorted(rankings.items()))


def build_cumulative_gainers(
    price_by_symbol: dict[str, pd.DataFrame],
    window_days: int,
    gain_field: str,
    top_n: int = 50,
    min_close: float = 50.0,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, raw_df in price_by_symbol.items():
        df = _normalize_price_frame(raw_df)
        if len(df) <= window_days:
            continue
        latest_close = float(df["Close"].iloc[-1])
        start_close = float(df["Close"].iloc[-(window_days + 1)])
        prev_close = float(df["Close"].iloc[-2])
        if latest_close < min_close or start_close <= 0 or prev_close <= 0:
            continue
        rows.append(
            {
                "symbol": symbol,
                gain_field: round((latest_close / start_close - 1) * 100, 2),
                "day_change_pct": round((latest_close / prev_close - 1) * 100, 2),
                "start_close": round(start_close, 2),
                "close": round(latest_close, 2),
            }
        )

    ranked_rows = sorted(
        rows,
        key=lambda row: (row[gain_field], row["symbol"]),
        reverse=True,
    )[:top_n]
    for rank, row in enumerate(ranked_rows, start=1):
        row["rank"] = rank
    return ranked_rows


def build_weekly_gainers(
    price_by_symbol: dict[str, pd.DataFrame],
    top_n: int = 50,
    window_days: int = WINDOWS["1w"],
    min_close: float = 50.0,
) -> list[dict[str, Any]]:
    return build_cumulative_gainers(
        price_by_symbol,
        window_days=window_days,
        gain_field="weekly_gain_pct",
        top_n=top_n,
        min_close=min_close,
    )


def build_monthly_gainers(
    price_by_symbol: dict[str, pd.DataFrame],
    top_n: int = 50,
    window_days: int = WINDOWS["1m"],
    min_close: float = 50.0,
) -> list[dict[str, Any]]:
    return build_cumulative_gainers(
        price_by_symbol,
        window_days=window_days,
        gain_field="monthly_gain_pct",
        top_n=top_n,
        min_close=min_close,
    )


def build_common_period_gainers(
    price_by_symbol: dict[str, pd.DataFrame],
    top_n: int = 50,
    min_close: float = 50.0,
) -> list[dict[str, Any]]:
    one_month_rows = build_cumulative_gainers(
        price_by_symbol,
        window_days=WINDOWS["1m"],
        gain_field="monthly_gain_pct",
        top_n=top_n,
        min_close=min_close,
    )
    two_month_rows = build_cumulative_gainers(
        price_by_symbol,
        window_days=42,
        gain_field="gain_2m_pct",
        top_n=top_n,
        min_close=min_close,
    )
    three_month_rows = build_cumulative_gainers(
        price_by_symbol,
        window_days=WINDOWS["3m"],
        gain_field="gain_3m_pct",
        top_n=top_n,
        min_close=min_close,
    )

    one_by_symbol = {row["symbol"]: row for row in one_month_rows}
    two_by_symbol = {row["symbol"]: row for row in two_month_rows}
    three_by_symbol = {row["symbol"]: row for row in three_month_rows}
    common_symbols = set(one_by_symbol) & set(two_by_symbol) & set(three_by_symbol)

    rows: list[dict[str, Any]] = []
    for symbol in common_symbols:
        base = dict(one_by_symbol[symbol])
        base["gain_2m_pct"] = two_by_symbol[symbol]["gain_2m_pct"]
        base["gain_3m_pct"] = three_by_symbol[symbol]["gain_3m_pct"]
        rows.append(base)

    ranked_rows = sorted(
        rows,
        key=lambda row: (row["monthly_gain_pct"], row["symbol"]),
        reverse=True,
    )
    for rank, row in enumerate(ranked_rows, start=1):
        row["rank"] = rank
    return ranked_rows


def _latest_dates(rankings: dict[pd.Timestamp, list[dict[str, Any]]], count: int) -> set[pd.Timestamp]:
    return set(sorted(rankings.keys())[-count:])


def _daily_changes_by_symbol(price_by_symbol: dict[str, pd.DataFrame]) -> dict[str, dict[pd.Timestamp, float]]:
    changes_by_symbol: dict[str, dict[pd.Timestamp, float]] = {}
    for symbol, raw_df in price_by_symbol.items():
        df = _normalize_price_frame(raw_df)
        if len(df) < 2:
            changes_by_symbol[symbol] = {}
            continue
        changes = (df["Close"].pct_change() * 100).dropna()
        changes_by_symbol[symbol] = {
            pd.Timestamp(trade_date): round(float(value), 2)
            for trade_date, value in changes.items()
            if not pd.isna(value)
        }
    return changes_by_symbol


def aggregate_symbol_counts(
    rankings: dict[pd.Timestamp, list[dict[str, Any]]],
    price_by_symbol: dict[str, pd.DataFrame],
    windows: dict[str, int] | None = None,
    up_threshold_pct: float = 4.0,
) -> list[dict[str, Any]]:
    active_windows = windows or WINDOWS
    changes_by_symbol = _daily_changes_by_symbol(price_by_symbol)
    symbols = set(changes_by_symbol)
    for rows in rankings.values():
        symbols.update(row["symbol"] for row in rows)

    top50_lookup: dict[str, dict[str, list[dict[str, Any]]]] = {
        symbol: {window: [] for window in active_windows}
        for symbol in symbols
    }
    up4_lookup: dict[str, dict[str, list[dict[str, Any]]]] = {
        symbol: {window: [] for window in active_windows}
        for symbol in symbols
    }
    down4_lookup: dict[str, dict[str, list[dict[str, Any]]]] = {
        symbol: {window: [] for window in active_windows}
        for symbol in symbols
    }

    for window_name, day_count in active_windows.items():
        window_dates = _latest_dates(rankings, day_count)

        for trade_date in sorted(window_dates):
            for row in rankings.get(trade_date, []):
                top50_lookup[row["symbol"]][window_name].append(
                    {
                        "date": trade_date.strftime("%Y-%m-%d"),
                        "rank": row["rank"],
                        "day_change_pct": row["day_change_pct"],
                        "close": row["close"],
                    }
                )

        for symbol, changes in changes_by_symbol.items():
            for trade_date in sorted(window_dates):
                day_change = changes.get(trade_date)
                if day_change is not None and day_change >= up_threshold_pct:
                    up4_lookup[symbol][window_name].append(
                        {
                            "date": trade_date.strftime("%Y-%m-%d"),
                            "day_change_pct": day_change,
                        }
                    )
                if day_change is not None and day_change < -up_threshold_pct:
                    down4_lookup[symbol][window_name].append(
                        {
                            "date": trade_date.strftime("%Y-%m-%d"),
                            "day_change_pct": day_change,
                        }
                    )

    gains: dict[str, dict[str, float | None]] = {}
    for symbol in symbols:
        df = _normalize_price_frame(price_by_symbol.get(symbol, pd.DataFrame()))
        today_close = float(df["Close"].iloc[-1]) if not df.empty else None
        symbol_gains: dict[str, float | None] = {}
        for window_name, day_count in active_windows.items():
            if today_close and len(df) > day_count:
                past = float(df["Close"].iloc[-(day_count + 1)])
                symbol_gains[window_name] = round((today_close / past - 1) * 100, 2)
            else:
                symbol_gains[window_name] = None
        gains[symbol] = symbol_gains

    summary: list[dict[str, Any]] = []
    for symbol in sorted(symbols):
        row: dict[str, Any] = {"symbol": symbol}
        for window_name in active_windows:
            row[f"top50_{window_name}_count"] = len(top50_lookup[symbol][window_name])
            row[f"up4_{window_name}_count"] = len(up4_lookup[symbol][window_name])
            row[f"down4_{window_name}_count"] = len(down4_lookup[symbol][window_name])
            row[f"top50_{window_name}_days"] = top50_lookup[symbol][window_name]
            row[f"up4_{window_name}_days"] = up4_lookup[symbol][window_name]
            row[f"down4_{window_name}_days"] = down4_lookup[symbol][window_name]
            row[f"gain_{window_name}_pct"] = gains[symbol].get(window_name)
        summary.append(row)

    return sorted(
        summary,
        key=lambda row: (
            row.get("top50_3m_count", 0),
            row.get("top50_1m_count", 0),
            row.get("top50_1w_count", 0),
            row.get("up4_3m_count", 0),
            -row.get("down4_3m_count", 0),
            row["symbol"],
        ),
        reverse=True,
    )


def get_nse_equity_universe(limit: int = 2000) -> list[str]:
    from tradingview_screener import Query, col

    _, df = (
        Query()
        .set_markets("india")
        .select("name", "close")
        .where(
            col("exchange") == "NSE",
            col("type") == "stock",
            col("typespecs").has(["common"]),
            col("close") > 0,
        )
        .limit(limit)
        .get_scanner_data()
    )
    return sorted(df["name"].dropna().astype(str).unique().tolist())


def get_sector_map(limit: int = 2000) -> dict[str, dict[str, str]]:
    from tradingview_screener import Query, col

    _, df = (
        Query()
        .set_markets("india")
        .select("name", "sector", "industry")
        .where(
            col("exchange") == "NSE",
            col("type") == "stock",
            col("typespecs").has(["common"]),
        )
        .limit(limit)
        .get_scanner_data()
    )
    result: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        sym = str(row.get("name", ""))
        if sym:
            result[sym] = {
                "sector": str(row.get("sector") or ""),
                "industry": str(row.get("industry") or ""),
            }
    return result


def fetch_price_history(symbols: list[str], period: str = "4mo") -> dict[str, pd.DataFrame]:
    import yfinance as yf

    price_by_symbol: dict[str, pd.DataFrame] = {}
    ticker_to_symbol = {f"{symbol}.NS": symbol for symbol in symbols}
    tickers = list(ticker_to_symbol)
    chunk_size = 120
    chunks = [
        tickers[index:index + chunk_size]
        for index in range(0, len(tickers), chunk_size)
    ]

    for chunk_index, chunk in enumerate(chunks, start=1):
        print(f"  Batch {chunk_index}/{len(chunks)} ({len(chunk)} symbols)")
        try:
            downloaded = yf.download(
                chunk,
                period=period,
                auto_adjust=False,
                group_by="ticker",
                threads=True,
                progress=False,
            )
        except Exception:
            continue

        if downloaded.empty:
            continue

        for ticker in chunk:
            if isinstance(downloaded.columns, pd.MultiIndex):
                if ticker not in downloaded.columns.get_level_values(0):
                    continue
                df = downloaded[ticker]
            else:
                df = downloaded
            normalized = _normalize_price_frame(df)
            if len(normalized) >= 2:
                price_by_symbol[ticker_to_symbol[ticker]] = normalized
    return price_by_symbol


def _format_top50_days(days: list[dict[str, Any]]) -> str:
    if not days:
        return "-"
    return ", ".join(
        f"{day['date']} #{day['rank']} ({day['day_change_pct']:+.2f}%)"
        for day in days
    )


def _format_up4_days(days: list[dict[str, Any]]) -> str:
    if not days:
        return "-"
    return ", ".join(
        f"{day['date']} ({day['day_change_pct']:+.2f}%)"
        for day in days
    )


def _format_down4_days(days: list[dict[str, Any]]) -> str:
    return _format_up4_days(days)


def build_summary_markdown(
    summary: list[dict[str, Any]],
    rankings: dict[pd.Timestamp, list[dict[str, Any]]],
) -> str:
    latest_date = max(rankings).strftime("%Y-%m-%d") if rankings else ""
    lines = [
        f"# NSE Top Gainers Repeat Analysis - {latest_date}",
        f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} IST*",
        "",
        "Counts are based on daily top 50 gainers. Windows use latest 5, 21, and 63 trading sessions.",
        "",
        "| Symbol | Top50 1W | Top50 1M | Top50 3M | Up >=4% 1W | Up >=4% 1M | Up >=4% 3M | Down >4% 1W | Down >4% 1M | Down >4% 3M | 1W Top50 Days | 1M Top50 Days | 3M Top50 Days |",
        "|--------|----------:|----------:|----------:|-----------:|-----------:|-----------:|-------------:|-------------:|-------------:|---------------|---------------|---------------|",
    ]
    visible_rows = [
        row for row in summary
        if row["top50_1w_count"] or row["top50_1m_count"] or row["top50_3m_count"]
    ]
    for row in visible_rows:
        tv = f"https://in.tradingview.com/chart/?symbol=NSE:{row['symbol']}"
        lines.append(
            f"| [{row['symbol']}]({tv}) "
            f"| {row['top50_1w_count']} "
            f"| {row['top50_1m_count']} "
            f"| {row['top50_3m_count']} "
            f"| {row['up4_1w_count']} "
            f"| {row['up4_1m_count']} "
            f"| {row['up4_3m_count']} "
            f"| {row['down4_1w_count']} "
            f"| {row['down4_1m_count']} "
            f"| {row['down4_3m_count']} "
            f"| {_format_top50_days(row['top50_1w_days'])} "
            f"| {_format_top50_days(row['top50_1m_days'])} "
            f"| {_format_top50_days(row['top50_3m_days'])} |"
        )
    return "\n".join(lines) + "\n"


def _count_total(summary: list[dict[str, Any]], key: str) -> int:
    return sum(int(row.get(key, 0)) for row in summary)


def _td_num(value: Any, css_class: str = "num") -> str:
    return f'<td class="{css_class}">{int(value)}</td>'


def _td_pct(value: float | None) -> str:
    if value is None:
        return '<td class="num">-</td>'
    css = "num pos" if value >= 0 else "num neg"
    return f'<td class="{css}">{value:+.2f}%</td>'


def _circuit_cls(s: str) -> str:
    if "🟨" in s:
        return "ccy"
    if "🟥" in s:
        return "ccr"
    if "🟩" in s:
        return "ccg"
    if "🟦" in s:
        return "ccb"
    return ""


def _html_days(days: list[dict[str, Any]], include_rank: bool = False) -> str:
    if not days:
        return "-"
    parts = []
    for day in days:
        pct = float(day["day_change_pct"])
        pct_class = "pos" if pct >= 0 else "neg"
        rank = f" #{day['rank']}" if include_rank and "rank" in day else ""
        parts.append(
            f'<span class="{pct_class}">{escape(day["date"])}{rank} ({pct:+.2f}%)</span>'
        )
    return "<br>".join(parts)


def _html_day_text(text: Any) -> str:
    value = "" if pd.isna(text) else str(text)
    if not value or value == "-":
        return "-"
    parts = []
    for item in value.split(", "):
        css_class = "neg" if "(-" in item else ("pos" if "(+" in item else "")
        parts.append(f'<span class="{css_class}">{escape(item)}</span>')
    return "<br>".join(parts)


def _summary_to_csv_rows(
    summary: list[dict[str, Any]],
    sector_map: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for row in summary:
        sym = row["symbol"]
        sec = (sector_map or {}).get(sym, {})
        rows.append(
            {
                "symbol": sym,
                "sector": sec.get("sector", ""),
                "industry": sec.get("industry", ""),
                "top50_1w_count": row["top50_1w_count"],
                "top50_1m_count": row["top50_1m_count"],
                "top50_3m_count": row["top50_3m_count"],
                "up4_1w_count": row["up4_1w_count"],
                "up4_1m_count": row["up4_1m_count"],
                "up4_3m_count": row["up4_3m_count"],
                "down4_1w_count": row["down4_1w_count"],
                "down4_1m_count": row["down4_1m_count"],
                "down4_3m_count": row["down4_3m_count"],
                "top50_1w_days": _format_top50_days(row["top50_1w_days"]),
                "top50_1m_days": _format_top50_days(row["top50_1m_days"]),
                "top50_3m_days": _format_top50_days(row["top50_3m_days"]),
                "up4_1w_days": _format_up4_days(row["up4_1w_days"]),
                "up4_1m_days": _format_up4_days(row["up4_1m_days"]),
                "up4_3m_days": _format_up4_days(row["up4_3m_days"]),
                "down4_1w_days": _format_down4_days(row["down4_1w_days"]),
                "down4_1m_days": _format_down4_days(row["down4_1m_days"]),
                "down4_3m_days": _format_down4_days(row["down4_3m_days"]),
                "gain_1w_pct": row.get("gain_1w_pct"),
                "gain_1m_pct": row.get("gain_1m_pct"),
                "gain_3m_pct": row.get("gain_3m_pct"),
            }
        )
    return rows


def build_html_dashboard_from_csv_rows(
    rows: list[dict[str, Any]],
    latest_date: str,
    latest_rankings: list[dict[str, Any]] | None = None,
    circuit_map: dict[str, str] | None = None,
    sector_map: dict[str, dict[str, str]] | None = None,
    *,
    page_title: str = "NSE Top Gainers Dashboard",
    source_label: str = "top_gainers_summary.csv",
    table_title: str = "Today's Top 50 Gainers - sortable counts",
    use_weekly_gain: bool = False,
    gain_1w_field: str | None = None,
    gain_1m_field: str | None = None,
    gain_2m_field: str | None = None,
    gain_3m_field: str | None = None,
    include_gain_2m: bool = False,
    row_count_label: str = "Today Top50",
) -> str:
    def as_int(row: dict[str, Any], key: str) -> int:
        value = row.get(key, 0)
        if pd.isna(value) or value == "":
            return 0
        return int(value)

    def as_float(row: dict[str, Any], key: str) -> float | None:
        value = row.get(key)
        if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    summary_like = []
    for row in rows:
        sym = str(row["symbol"])
        sec_fallback = (sector_map or {}).get(sym, {})
        summary_like.append(
            {
                "symbol": sym,
                "sector": str(row.get("sector") or sec_fallback.get("sector", "")),
                "industry": str(row.get("industry") or sec_fallback.get("industry", "")),
                "top50_1w_count": as_int(row, "top50_1w_count"),
                "top50_1m_count": as_int(row, "top50_1m_count"),
                "top50_3m_count": as_int(row, "top50_3m_count"),
                "up4_1w_count": as_int(row, "up4_1w_count"),
                "up4_1m_count": as_int(row, "up4_1m_count"),
                "up4_3m_count": as_int(row, "up4_3m_count"),
                "down4_1w_count": as_int(row, "down4_1w_count"),
                "down4_1m_count": as_int(row, "down4_1m_count"),
                "down4_3m_count": as_int(row, "down4_3m_count"),
                "top50_1w_days_html": _html_day_text(row.get("top50_1w_days", "-")),
                "up4_1w_days_html": _html_day_text(row.get("up4_1w_days", "-")),
                "down4_1w_days_html": _html_day_text(row.get("down4_1w_days", "-")),
                "down4_1m_days_html": _html_day_text(row.get("down4_1m_days", "-")),
                "gain_1w_pct": as_float(row, "gain_1w_pct"),
                "gain_1m_pct": as_float(row, "gain_1m_pct"),
                "gain_3m_pct": as_float(row, "gain_3m_pct"),
            }
        )
    return _build_html_dashboard(
        summary_like,
        latest_date,
        latest_rankings or [],
        rows_are_csv=True,
        circuit_map=circuit_map,
        page_title=page_title,
        source_label=source_label,
        table_title=table_title,
        use_weekly_gain=use_weekly_gain,
        gain_1w_field=gain_1w_field,
        gain_1m_field=gain_1m_field,
        gain_2m_field=gain_2m_field,
        gain_3m_field=gain_3m_field,
        include_gain_2m=include_gain_2m,
        row_count_label=row_count_label,
    )


def build_weekly_html_dashboard_from_csv_rows(
    rows: list[dict[str, Any]],
    latest_date: str,
    weekly_rankings: list[dict[str, Any]] | None = None,
    circuit_map: dict[str, str] | None = None,
    sector_map: dict[str, dict[str, str]] | None = None,
) -> str:
    return build_html_dashboard_from_csv_rows(
        rows,
        latest_date,
        weekly_rankings or [],
        circuit_map=circuit_map,
        sector_map=sector_map,
        page_title="NSE Top Week Gainers Dashboard",
        source_label="top_gainers_summary.csv",
        table_title="Top 50 Weekly Gainers - sortable counts",
        gain_1w_field="weekly_gain_pct",
        row_count_label="Top 50",
    )


def build_monthly_html_dashboard_from_csv_rows(
    rows: list[dict[str, Any]],
    latest_date: str,
    monthly_rankings: list[dict[str, Any]] | None = None,
    circuit_map: dict[str, str] | None = None,
    sector_map: dict[str, dict[str, str]] | None = None,
) -> str:
    return build_html_dashboard_from_csv_rows(
        rows,
        latest_date,
        monthly_rankings or [],
        circuit_map=circuit_map,
        sector_map=sector_map,
        page_title="NSE Top Month Gainers Dashboard",
        source_label="top_gainers_summary.csv",
        table_title="Top 50 Monthly Gainers - sortable counts",
        gain_1m_field="monthly_gain_pct",
        row_count_label="Top 50",
    )


def build_common_html_dashboard_from_csv_rows(
    rows: list[dict[str, Any]],
    latest_date: str,
    common_rankings: list[dict[str, Any]] | None = None,
    circuit_map: dict[str, str] | None = None,
    sector_map: dict[str, dict[str, str]] | None = None,
) -> str:
    return build_html_dashboard_from_csv_rows(
        rows,
        latest_date,
        common_rankings or [],
        circuit_map=circuit_map,
        sector_map=sector_map,
        page_title="NSE Common Period Gainers Dashboard",
        source_label="top_gainers_summary.csv",
        table_title="Common 1M / 2M / 3M Gainers - sortable counts",
        gain_1m_field="monthly_gain_pct",
        gain_2m_field="gain_2m_pct",
        gain_3m_field="gain_3m_pct",
        include_gain_2m=True,
        row_count_label="Common",
    )


def build_html_dashboard(
    summary: list[dict[str, Any]],
    latest_date: str,
    latest_rankings: list[dict[str, Any]] | None = None,
    circuit_map: dict[str, str] | None = None,
) -> str:
    return _build_html_dashboard(summary, latest_date, latest_rankings or [], rows_are_csv=False, circuit_map=circuit_map)


def build_weekly_html_dashboard(
    summary: list[dict[str, Any]],
    latest_date: str,
    weekly_rankings: list[dict[str, Any]] | None = None,
    circuit_map: dict[str, str] | None = None,
) -> str:
    return _build_html_dashboard(
        summary,
        latest_date,
        weekly_rankings or [],
        rows_are_csv=False,
        circuit_map=circuit_map,
        page_title="NSE Top Week Gainers Dashboard",
        source_label="top_gainers_summary.csv",
        table_title="Top 50 Weekly Gainers - sortable counts",
        gain_1w_field="weekly_gain_pct",
        row_count_label="Top 50",
    )


def build_monthly_html_dashboard(
    summary: list[dict[str, Any]],
    latest_date: str,
    monthly_rankings: list[dict[str, Any]] | None = None,
    circuit_map: dict[str, str] | None = None,
) -> str:
    return _build_html_dashboard(
        summary,
        latest_date,
        monthly_rankings or [],
        rows_are_csv=False,
        circuit_map=circuit_map,
        page_title="NSE Top Month Gainers Dashboard",
        source_label="top_gainers_summary.csv",
        table_title="Top 50 Monthly Gainers - sortable counts",
        gain_1m_field="monthly_gain_pct",
        row_count_label="Top 50",
    )


def build_common_html_dashboard(
    summary: list[dict[str, Any]],
    latest_date: str,
    common_rankings: list[dict[str, Any]] | None = None,
    circuit_map: dict[str, str] | None = None,
) -> str:
    return _build_html_dashboard(
        summary,
        latest_date,
        common_rankings or [],
        rows_are_csv=False,
        circuit_map=circuit_map,
        page_title="NSE Common Period Gainers Dashboard",
        source_label="top_gainers_summary.csv",
        table_title="Common 1M / 2M / 3M Gainers - sortable counts",
        gain_1m_field="monthly_gain_pct",
        gain_2m_field="gain_2m_pct",
        gain_3m_field="gain_3m_pct",
        include_gain_2m=True,
        row_count_label="Common",
    )


def _load_watchlist() -> dict:
    if not os.path.exists(WATCHLIST_FILE):
        return {"config": {"capital": 500000, "risk_pct": 0.5}, "universe": [], "ready_to_trade": [], "held": []}
    with open(WATCHLIST_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def _load_recent_journals(journal_dir: str, n: int = 7) -> list[dict]:
    if not os.path.isdir(journal_dir):
        return []
    files = sorted((f for f in os.listdir(journal_dir) if f.endswith(".json")), reverse=True)[:n]
    result = []
    for fname in files:
        with open(os.path.join(journal_dir, fname), encoding="utf-8") as fh:
            result.append(json.load(fh))
    return result


_CHAR_BADGE: dict[str, str] = {
    "Tennis-Ball": '<span class="badge badge-tb">Tennis-Ball</span>',
    "Wet-Floor": '<span class="badge badge-wf">Wet-Floor</span>',
    "Eating-Bottom": '<span class="badge badge-eb">Eating-Bottom</span>',
    "Linear-Pole": '<span class="badge badge-lp">Linear-Pole</span>',
    "Choppy": '<span class="badge badge-ch">Choppy</span>',
}


def _char_badge(char: str) -> str:
    return _CHAR_BADGE.get(char, escape(char) if char and char != "-" else "—")


def _build_watchlist_tab_html(data: dict) -> str:
    cfg = data.get("config", {})
    capital = float(cfg.get("capital", 500000))
    risk_pct = float(cfg.get("risk_pct", 0.5))
    risk_amount = capital * risk_pct / 100

    def tv_link(sym: str) -> str:
        s = escape(sym)
        return f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{s}" target="_blank" rel="noopener">{s}</a>'

    held = data.get("held", [])
    ready = data.get("ready_to_trade", [])
    universe = data.get("universe", [])

    if held:
        held_rows = []
        for e in held:
            entry_p = float(e.get("entry", 0))
            stop_p = float(e.get("stop", 0))
            risk = entry_p - stop_p
            stop_pct = (stop_p - entry_p) / entry_p * 100 if entry_p else 0
            held_rows.append(
                f'<tr>'
                f'<td class="sym">{tv_link(e.get("symbol", ""))}</td>'
                f'<td>{_char_badge(e.get("character", "-"))}</td>'
                f'<td class="num">₹{entry_p:.2f}</td>'
                f'<td class="num">₹{stop_p:.2f} <span class="neg">({stop_pct:.1f}%)</span></td>'
                f'<td class="num">{e.get("size", 0)}</td>'
                f'<td class="num neg">₹{risk:.2f}</td>'
                f'<td class="num">{escape(e.get("entry_date", ""))}</td>'
                f'<td style="max-width:160px;font-size:11px;color:var(--mu)">{escape(e.get("notes", ""))}</td>'
                f'</tr>'
            )
        held_body = "\n".join(held_rows)
    else:
        held_body = '<tr><td colspan="8" class="empty">No held positions</td></tr>'

    if ready:
        ready_rows = []
        for e in ready:
            anchor = float(e.get("anchor_point", 0))
            stop_p = float(e.get("stop_level", 0))
            calc_sz = int(risk_amount / (anchor - stop_p)) if anchor > stop_p else 0
            ready_rows.append(
                f'<tr>'
                f'<td class="sym">{tv_link(e.get("symbol", ""))}</td>'
                f'<td>{escape(e.get("sector", ""))}</td>'
                f'<td class="num">₹{anchor:.2f}</td>'
                f'<td class="num">₹{stop_p:.2f}</td>'
                f'<td class="num">{calc_sz}</td>'
                f'<td class="num">{escape(e.get("added_date", ""))}</td>'
                f'<td style="max-width:160px;font-size:11px;color:var(--mu)">{escape(e.get("notes", ""))}</td>'
                f'</tr>'
            )
        ready_body = "\n".join(ready_rows)
    else:
        ready_body = '<tr><td colspan="7" class="empty">No ready-to-trade names</td></tr>'

    if universe:
        uni_rows = [
            f'<tr>'
            f'<td class="sym">{tv_link(e.get("symbol", ""))}</td>'
            f'<td>{escape(e.get("sector", ""))}</td>'
            f'<td class="num">{escape(e.get("added_date", ""))}</td>'
            f'<td style="max-width:220px;font-size:11px;color:var(--mu)">{escape(e.get("notes", ""))}</td>'
            f'</tr>'
            for e in universe
        ]
        uni_body = "\n".join(uni_rows)
    else:
        uni_body = '<tr><td colspan="4" class="empty">Universe is empty — add stocks with: python watchlist_manager.py add SYMBOL --sector Sector</td></tr>'

    return (
        f'<div class="section">'
        f'<div class="stitle" style="margin-bottom:6px">'
        f'Capital ₹{capital:,.0f} &nbsp;|&nbsp; Risk {risk_pct}% = ₹{risk_amount:,.0f}/trade'
        f'&nbsp;<span style="color:var(--mu);font-size:10px">· edit: python watchlist_manager.py set-capital &lt;amount&gt; --risk &lt;pct&gt;</span>'
        f'</div></div>'
        f'<div class="section"><div class="stitle">Held ({len(held)})</div>'
        f'<div class="scroll"><table>'
        f'<thead><tr><th>Symbol</th><th>Character</th><th>Entry</th><th>Stop</th><th>Size</th><th>Risk/Share</th><th>Entry Date</th><th>Notes</th></tr></thead>'
        f'<tbody>{held_body}</tbody></table></div></div>'
        f'<div class="section"><div class="stitle">Ready to Trade ({len(ready)})</div>'
        f'<div class="scroll"><table>'
        f'<thead><tr><th>Symbol</th><th>Sector</th><th>Anchor Pt</th><th>Stop</th><th>Calc Size</th><th>Added</th><th>Notes</th></tr></thead>'
        f'<tbody>{ready_body}</tbody></table></div></div>'
        f'<div class="section"><div class="stitle">Universe ({len(universe)})</div>'
        f'<div class="scroll"><table>'
        f'<thead><tr><th>Symbol</th><th>Sector</th><th>Added</th><th>Notes</th></tr></thead>'
        f'<tbody>{uni_body}</tbody></table></div></div>'
    )


def _build_journal_tab_html(journal_dir: str) -> str:
    journals = _load_recent_journals(journal_dir, n=7)
    if not journals:
        return (
            '<div class="section"><div class="empty" style="padding:24px">'
            'No journal entries yet. Run: <code>python journal_manager.py new</code>'
            '</div></div>'
        )

    today_j = journals[0]
    history = journals[1:]

    regime = escape(today_j.get("market_regime", "") or "—")
    leading = escape(", ".join(today_j.get("sectors_leading", [])) or "—")
    lagging = escape(", ".join(today_j.get("sectors_lagging", [])) or "—")

    trades = today_j.get("trades_taken", [])
    total_r = sum(t.get("r_result", 0) or 0 for t in trades)
    violations = sum(1 for t in trades if not t.get("followed_plan", True))

    trade_rows = ""
    for t in trades:
        exit_str = f'₹{t["exit"]:.2f}' if t.get("exit") else "open"
        r = t.get("r_result")
        r_str = f'{r:+.2f}R' if r is not None else "—"
        r_cls = "pos" if (r or 0) > 0 else ("neg" if (r or 0) < 0 else "")
        plan_icon = "✓" if t.get("followed_plan", True) else '<span class="neg">✗</span>'
        trade_rows += (
            f'<tr><td class="sym">{escape(t["symbol"])}</td>'
            f'<td style="font-size:11px">{escape(t.get("setup", ""))}</td>'
            f'<td class="num">₹{t["entry"]:.2f}</td><td class="num">₹{t["stop"]:.2f}</td>'
            f'<td class="num">{t.get("size", "")}</td><td class="num">{exit_str}</td>'
            f'<td class="num {r_cls}">{r_str}</td>'
            f'<td style="text-align:center">{plan_icon}</td></tr>'
        )
    if not trade_rows:
        trade_rows = '<tr><td colspan="8" class="empty">No trades today</td></tr>'

    missed_rows = "".join(
        f'<tr><td class="sym">{escape(m["symbol"])}</td>'
        f'<td style="font-size:11px;color:var(--mu)">{escape(m.get("reason", ""))}</td></tr>'
        for m in today_j.get("trades_missed", [])
    ) or '<tr><td colspan="2" class="empty">—</td></tr>'

    char_rows = "".join(
        f'<tr><td class="sym">{escape(p["symbol"])}</td><td>{_char_badge(p.get("character", ""))}</td></tr>'
        for p in today_j.get("positions_character", [])
    ) or '<tr><td colspan="2" class="empty">—</td></tr>'

    em = today_j.get("emotion", {})
    did_well = escape(today_j.get("did_well", "") or "—")
    fix_tmrw = escape(today_j.get("fix_tomorrow", "") or "—")
    r_cls = "pos" if total_r >= 0 else "neg"
    v_cls = "neg" if violations else "grn"

    today_card = (
        f'<div class="section">'
        f'<div class="stitle">Today — {escape(today_j.get("date", ""))}</div>'
        f'<div class="bar" style="margin-bottom:12px">'
        f'<div class="stat"><div class="sv">{regime}</div><div class="sl">Regime</div></div>'
        f'<div class="stat"><div class="sv grn" style="font-size:13px">{leading}</div><div class="sl">Leading</div></div>'
        f'<div class="stat"><div class="sv red" style="font-size:13px">{lagging}</div><div class="sl">Lagging</div></div>'
        f'<div class="stat"><div class="sv {r_cls}">{total_r:+.2f}R</div><div class="sl">Day R</div></div>'
        f'<div class="stat"><div class="sv {v_cls}">{violations}</div><div class="sl">Violations</div></div>'
        f'</div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">'
        f'<div><div class="stitle" style="font-size:10px">Trades Taken</div>'
        f'<div class="scroll"><table><thead><tr><th>Symbol</th><th>Setup</th><th>Entry</th><th>Stop</th><th>Size</th><th>Exit</th><th>R</th><th>Plan</th></tr></thead>'
        f'<tbody>{trade_rows}</tbody></table></div></div>'
        f'<div style="display:flex;flex-direction:column;gap:12px">'
        f'<div><div class="stitle" style="font-size:10px">Missed</div>'
        f'<table><thead><tr><th>Symbol</th><th>Reason</th></tr></thead><tbody>{missed_rows}</tbody></table></div>'
        f'<div><div class="stitle" style="font-size:10px">Open Position Character</div>'
        f'<table><thead><tr><th>Symbol</th><th>Character</th></tr></thead><tbody>{char_rows}</tbody></table></div>'
        f'</div></div>'
        f'<div style="display:flex;gap:12px;flex-wrap:wrap;font-size:12px">'
        f'<div style="flex:1;background:var(--bg2);padding:8px 12px;border-radius:6px;border:1px solid var(--bd)">'
        f'<div style="color:var(--mu);font-size:10px;margin-bottom:3px">Did well</div>{did_well}</div>'
        f'<div style="flex:1;background:var(--bg2);padding:8px 12px;border-radius:6px;border:1px solid var(--bd)">'
        f'<div style="color:var(--mu);font-size:10px;margin-bottom:3px">Fix tomorrow</div>{fix_tmrw}</div>'
        f'<div style="background:var(--bg2);padding:8px 12px;border-radius:6px;border:1px solid var(--bd)">'
        f'<div style="color:var(--mu);font-size:10px;margin-bottom:3px">Emotions (1-10)</div>'
        f'Hesitation <b>{em.get("hesitation", 0)}</b> &nbsp;Greed <b>{em.get("greed", 0)}</b> &nbsp;Regret <b>{em.get("regret", 0)}</b>'
        f'</div></div></div>'
    )

    if history:
        hist_rows = ""
        for j in history:
            jt = j.get("trades_taken", [])
            j_r = sum(t.get("r_result", 0) or 0 for t in jt)
            j_viol = sum(1 for t in jt if not t.get("followed_plan", True))
            jr_cls = "pos" if j_r > 0 else ("neg" if j_r < 0 else "")
            hist_rows += (
                f'<tr><td class="num">{escape(j.get("date", ""))}</td>'
                f'<td>{escape(j.get("market_regime", "") or "—")}</td>'
                f'<td class="num">{len(jt)}</td>'
                f'<td class="num {jr_cls}">{j_r:+.2f}R</td>'
                f'<td class="num {"neg" if j_viol else ""}">{j_viol}</td></tr>'
            )
        history_section = (
            f'<div class="section"><div class="stitle">History (last {len(history)} days)</div>'
            f'<table><thead><tr><th>Date</th><th>Regime</th><th>Trades</th><th>R Total</th><th>Violations</th></tr></thead>'
            f'<tbody>{hist_rows}</tbody></table></div>'
        )
    else:
        history_section = ""

    return today_card + history_section


def _build_html_dashboard(
    summary: list[dict[str, Any]],
    latest_date: str,
    latest_rankings: list[dict[str, Any]],
    rows_are_csv: bool,
    circuit_map: dict[str, str] | None = None,
    *,
    page_title: str = "NSE Top Gainers Dashboard",
    source_label: str = "top_gainers_summary.csv",
    table_title: str = "Today's Top 50 Gainers - sortable counts",
    use_weekly_gain: bool = False,
    gain_1w_field: str | None = None,
    gain_1m_field: str | None = None,
    gain_2m_field: str | None = None,
    gain_3m_field: str | None = None,
    include_gain_2m: bool = False,
    row_count_label: str = "Today Top50",
) -> str:
    if use_weekly_gain and gain_1w_field is None:
        gain_1w_field = "weekly_gain_pct"

    summary_by_symbol = {row["symbol"]: row for row in summary}
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    watchlist_data = _load_watchlist()
    watchlist_html = _build_watchlist_tab_html(watchlist_data)
    journal_html = _build_journal_tab_html(JOURNAL_DIR)

    gain_2m_header = '<th class="sortable" data-sort="num">Gain 2M</th>' if include_gain_2m else ""
    empty_colspan = 19 if include_gain_2m else 18

    body_rows = []
    for row in sorted(latest_rankings, key=lambda item: item["rank"]):
        counts = summary_by_symbol.get(row["symbol"])
        if counts is None:
            continue
        row_class = "r3" if counts["top50_3m_count"] >= 10 else ("r2" if counts["top50_1m_count"] >= 5 else "")
        symbol = escape(row["symbol"])
        tv = f"https://in.tradingview.com/chart/?symbol=NSE:{symbol}"
        day_change = float(row["day_change_pct"])
        circ = (circuit_map or {}).get(row["symbol"], "")
        circ_cls = _circuit_cls(circ)
        circ_cell = f'<td class="{circ_cls}">{escape(circ) if circ else "-"}</td>'
        sector = counts.get("sector", "")
        industry = counts.get("industry", "")
        sector_inner = escape(sector) if sector else "-"
        if industry:
            sector_inner += f'<br><span style="font-size:10px;color:var(--mu)">{escape(industry)}</span>'
        sector_cell = f'<td>{sector_inner}</td>'
        gain_1w_value = row.get(gain_1w_field) if gain_1w_field else counts.get("gain_1w_pct")
        gain_1m_value = row.get(gain_1m_field) if gain_1m_field else counts.get("gain_1m_pct")
        gain_2m_cell = _td_pct(row.get(gain_2m_field)) if include_gain_2m and gain_2m_field else ""
        gain_3m_value = row.get(gain_3m_field) if gain_3m_field else counts.get("gain_3m_pct")
        body_rows.append(
            f'<tr class="{row_class}">'
            f'<td class="num">{int(row["rank"])}</td>'
            f'<td class="sym"><a href="{tv}" target="_blank" rel="noopener">{symbol}</a></td>'
            f'{sector_cell}'
            f'<td class="num">{float(row["close"]):.2f}</td>'
            f'{_td_pct(day_change)}'
            f'{_td_pct(gain_1w_value)}'
            f'{_td_pct(gain_1m_value)}'
            f'{gain_2m_cell}'
            f'{_td_pct(gain_3m_value)}'
            f'{circ_cell}'
            f'{_td_num(counts["top50_1w_count"])}'
            f'{_td_num(counts["top50_1m_count"])}'
            f'{_td_num(counts["top50_3m_count"])}'
            f'{_td_num(counts["up4_1w_count"], "num pos")}'
            f'{_td_num(counts["up4_1m_count"], "num pos")}'
            f'{_td_num(counts["up4_3m_count"], "num pos")}'
            f'{_td_num(counts["down4_1w_count"], "num neg")}'
            f'{_td_num(counts["down4_1m_count"], "num neg")}'
            f'{_td_num(counts["down4_3m_count"], "num neg")}'
            "</tr>"
        )

    table_body = "\n".join(body_rows) if body_rows else f'<tr><td colspan="{empty_colspan}" class="empty">No top gainer rows</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(page_title)} - {escape(latest_date)}</title>
<style>
:root{{
  --bg:#0d1117;--bg2:#161b22;--bg3:#21262d;
  --bd:#30363d;--tx:#e6edf3;--mu:#8b949e;
  --gld:#ffd700;--grn:#3fb950;--red:#f85149;--blu:#58a6ff;--pur:#a371f7;--ylw:#e3b341;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--tx);font-family:'Segoe UI',system-ui,sans-serif;font-size:13px;padding:16px;line-height:1.4}}
h1{{font-size:1.25rem;color:var(--blu);margin-bottom:3px}}
.sub{{color:var(--mu);font-size:11px;margin-bottom:16px}}
.bar{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}}
.stat{{background:var(--bg2);border:1px solid var(--bd);border-radius:6px;padding:7px 14px;text-align:center;min-width:84px}}
.sv{{font-size:1.5rem;font-weight:700;line-height:1.1}}
.sl{{color:var(--mu);font-size:10px;text-transform:uppercase;letter-spacing:.5px}}
.grn{{color:var(--grn)}}.red{{color:var(--red)}}.blu{{color:var(--blu)}}.pur{{color:var(--pur)}}.gld{{color:var(--gld)}}
.section{{margin-bottom:18px}}
.stitle{{font-size:.78rem;font-weight:600;color:var(--mu);text-transform:uppercase;letter-spacing:.7px;margin-bottom:6px;border-bottom:1px solid var(--bd);padding-bottom:3px}}
table{{width:100%;border-collapse:collapse;background:var(--bg2);border-radius:6px;overflow:hidden;font-size:12px}}
th{{background:var(--bg3);color:var(--mu);font-size:10px;text-transform:uppercase;letter-spacing:.5px;padding:5px 9px;text-align:left;border-bottom:1px solid var(--bd);position:sticky;top:0;z-index:1}}
th.sortable{{cursor:pointer;user-select:none}}
th.sortable::after{{content:"  ↕";color:var(--mu);font-size:9px}}
th.sorted{{color:var(--gld)!important}}
th.sorted::after{{content:" ↑"!important;color:var(--gld)}}
th.sorted[data-asc="false"]::after{{content:" ↓"!important;color:var(--gld)}}
td{{padding:4px 9px;border-bottom:1px solid var(--bd);vertical-align:top}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:var(--bg3)}}
.r3{{background:rgba(255,215,0,.07)}}.r3:hover td{{background:rgba(255,215,0,.13)}}
.r2{{background:rgba(88,166,255,.05)}}
.sym{{font-weight:600;font-family:monospace;font-size:12px;white-space:nowrap}}
.sym a{{color:inherit;text-decoration:none}}.sym a:hover{{text-decoration:underline;color:var(--blu)}}
.num{{font-family:monospace;font-size:12px;color:var(--mu);text-align:right}}
.pos{{color:var(--grn)}}.neg{{color:var(--red)}}
.ccy{{color:var(--ylw)}}.ccr{{color:var(--red)}}.ccg{{color:var(--grn)}}.ccb{{color:var(--blu)}}
td.sorted-col{{background:rgba(255,215,0,.04)}}
.days{{font-size:11px;color:var(--mu);min-width:150px;max-width:260px}}
.empty{{color:var(--mu);font-style:italic;text-align:center;padding:8px}}
.scroll{{overflow:auto;max-height:78vh;border-radius:6px}}
@media(max-width:900px){{body{{padding:10px}}.days{{min-width:180px}}}}
.tab-nav{{display:flex;gap:6px;margin-bottom:14px}}
.tab-btn{{background:var(--bg2);border:1px solid var(--bd);color:var(--mu);padding:5px 14px;border-radius:4px;cursor:pointer;font-size:12px;font-weight:600;letter-spacing:.4px;transition:color .15s,border-color .15s}}
.tab-btn.active{{background:var(--bg3);border-color:var(--blu);color:var(--blu)}}
.tab-content{{display:block}}
.badge{{display:inline-block;padding:1px 7px;border-radius:10px;font-size:10px;font-weight:700}}
.badge-tb{{background:rgba(63,185,80,.2);color:var(--grn)}}.badge-wf{{background:rgba(248,81,73,.2);color:var(--red)}}.badge-eb{{background:rgba(227,179,65,.2);color:var(--ylw)}}.badge-lp{{background:rgba(88,166,255,.2);color:var(--blu)}}.badge-ch{{background:rgba(139,148,158,.2);color:var(--mu)}}
</style>
</head>
<body>
<h1>{escape(page_title)} - {escape(latest_date)}</h1>
<div class="sub">Generated {escape(generated)} IST from {escape(source_label)}</div>
<div class="bar">
  <div class="stat"><div class="sv blu">{len(body_rows)}</div><div class="sl">{escape(row_count_label)}</div></div>
  <div class="stat"><div class="sv gld">{_count_total(summary, "top50_1w_count")}</div><div class="sl">Top50 1W</div></div>
  <div class="stat"><div class="sv gld">{_count_total(summary, "top50_1m_count")}</div><div class="sl">Top50 1M</div></div>
  <div class="stat"><div class="sv gld">{_count_total(summary, "top50_3m_count")}</div><div class="sl">Top50 3M</div></div>
  <div class="stat"><div class="sv grn">{_count_total(summary, "up4_1m_count")}</div><div class="sl">Up >=4% 1M</div></div>
  <div class="stat"><div class="sv red">{_count_total(summary, "down4_1m_count")}</div><div class="sl">Down &gt;4% 1M</div></div>
</div>
<nav class="tab-nav">
  <button class="tab-btn active" onclick="showTab('gainers',this)">Top Gainers</button>
  <button class="tab-btn" onclick="showTab('watchlist',this)">Watchlist</button>
  <button class="tab-btn" onclick="showTab('journal',this)">Journal</button>
</nav>
<div id="tab-gainers" class="tab-content">
<div class="section">
  <div class="stitle">{table_title}</div>
  <div class="scroll">
    <table id="todayTopGainers">
      <thead><tr><th class="sortable" data-sort="num">Rank</th><th class="sortable" data-sort="text">Symbol</th><th class="sortable" data-sort="text">Sector</th><th class="sortable" data-sort="num">Close</th><th class="sortable" data-sort="num">Day Chg</th><th class="sortable" data-sort="num">Gain 1W</th><th class="sortable" data-sort="num">Gain 1M</th>{gain_2m_header}<th class="sortable" data-sort="num">Gain 3M</th><th class="sortable" data-sort="text">Circuit</th><th class="sortable" data-sort="num">Top50 1W</th><th class="sortable" data-sort="num">Top50 1M</th><th class="sortable" data-sort="num">Top50 3M</th><th class="sortable" data-sort="num">Up >=4% 1W</th><th class="sortable" data-sort="num">Up >=4% 1M</th><th class="sortable" data-sort="num">Up >=4% 3M</th><th class="sortable" data-sort="num">Down &gt;4% 1W</th><th class="sortable" data-sort="num">Down &gt;4% 1M</th><th class="sortable" data-sort="num">Down &gt;4% 3M</th></tr></thead>
      <tbody>{table_body}</tbody>
    </table>
  </div>
</div>
</div>
<div id="tab-watchlist" class="tab-content" style="display:none">
{watchlist_html}
</div>
<div id="tab-journal" class="tab-content" style="display:none">
{journal_html}
</div>
<script>
function showTab(name, btn) {{
  document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
  document.getElementById('tab-' + name).style.display = 'block';
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}}
function cellValue(row, index) {{
  return row.children[index].innerText.trim().replace('%', '').replace('+', '');
}}
function sortTable(table, column, type, ascending) {{
  const tbody = table.tBodies[0];
  const rows = Array.from(tbody.rows);
  rows.sort((a, b) => {{
    const av = cellValue(a, column);
    const bv = cellValue(b, column);
    if (type === 'num') {{
      return (parseFloat(av) || 0) - (parseFloat(bv) || 0);
    }}
    return av.localeCompare(bv);
  }});
  if (!ascending) rows.reverse();
  rows.forEach(row => tbody.appendChild(row));
}}
document.querySelectorAll('#todayTopGainers th.sortable').forEach((th, index) => {{
  th.addEventListener('click', () => {{
    const ascending = th.dataset.asc !== 'true';
    document.querySelectorAll('#todayTopGainers th.sortable').forEach(h => {{
      h.dataset.asc = ''; h.classList.remove('sorted');
    }});
    document.querySelectorAll('#todayTopGainers td.sorted-col').forEach(td => td.classList.remove('sorted-col'));
    th.dataset.asc = String(ascending);
    th.classList.add('sorted');
    document.querySelectorAll(`#todayTopGainers tbody tr td:nth-child(${{index + 1}})`).forEach(td => td.classList.add('sorted-col'));
    sortTable(document.getElementById('todayTopGainers'), index, th.dataset.sort, ascending);
  }});
}});
</script>
</body>
</html>
"""


def build_daily_markdown(rankings: dict[pd.Timestamp, list[dict[str, Any]]]) -> str:
    lines = [
        "# NSE Daily Top 50 Gainers",
        f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} IST*",
        "",
    ]
    for trade_date in sorted(rankings.keys(), reverse=True):
        lines.extend(
            [
                f"## {trade_date.strftime('%Y-%m-%d')}",
                "",
                "| Rank | Symbol | Day Change | Close |",
                "|-----:|--------|-----------:|------:|",
            ]
        )
        for row in rankings[trade_date]:
            tv = f"https://in.tradingview.com/chart/?symbol=NSE:{row['symbol']}"
            lines.append(
                f"| {row['rank']} | [{row['symbol']}]({tv}) | {row['day_change_pct']:+.2f}% | {row['close']:.2f} |"
            )
        lines.append("")
    return "\n".join(lines)


def write_outputs(
    summary: list[dict[str, Any]],
    rankings: dict[pd.Timestamp, list[dict[str, Any]]],
    price_by_symbol: dict[str, pd.DataFrame],
) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    with open(SUMMARY_MD, "w", encoding="utf-8") as fh:
        fh.write(build_summary_markdown(summary, rankings))

    sector_map = get_sector_map()

    csv_rows = _summary_to_csv_rows(summary, sector_map=sector_map)
    pd.DataFrame(csv_rows).to_csv(SUMMARY_CSV, index=False)

    with open(SUMMARY_JSON, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    with open(DAILY_MD, "w", encoding="utf-8") as fh:
        fh.write(build_daily_markdown(rankings))

    latest_date = max(rankings).strftime("%Y-%m-%d") if rankings else ""
    csv_rows = pd.read_csv(SUMMARY_CSV).to_dict("records")
    latest_rankings = rankings[max(rankings)] if rankings else []
    weekly_rankings = build_weekly_gainers(price_by_symbol)
    monthly_rankings = build_monthly_gainers(price_by_symbol)
    common_rankings = build_common_period_gainers(price_by_symbol)
    circuit_map = load_circuit_map()
    with open(HTML_DASHBOARD, "w", encoding="utf-8") as fh:
        fh.write(build_html_dashboard_from_csv_rows(csv_rows, latest_date, latest_rankings, circuit_map=circuit_map, sector_map=sector_map))
    with open(WEEKLY_HTML_DASHBOARD, "w", encoding="utf-8") as fh:
        fh.write(build_weekly_html_dashboard_from_csv_rows(csv_rows, latest_date, weekly_rankings, circuit_map=circuit_map, sector_map=sector_map))
    with open(MONTHLY_HTML_DASHBOARD, "w", encoding="utf-8") as fh:
        fh.write(build_monthly_html_dashboard_from_csv_rows(csv_rows, latest_date, monthly_rankings, circuit_map=circuit_map, sector_map=sector_map))
    with open(COMMON_HTML_DASHBOARD, "w", encoding="utf-8") as fh:
        fh.write(build_common_html_dashboard_from_csv_rows(csv_rows, latest_date, common_rankings, circuit_map=circuit_map, sector_map=sector_map))


def main() -> None:
    print("\nFetching NSE equity universe...")
    symbols = get_nse_equity_universe()
    print(f"  Universe: {len(symbols)} symbols")

    print("\nFetching 4 months of daily price history...")
    price_by_symbol = fetch_price_history(symbols)
    print(f"  Price histories: {len(price_by_symbol)} symbols")

    print("\nBuilding daily top 50 gainers...")
    rankings = build_daily_rankings(price_by_symbol, top_n=50)
    if not rankings:
        raise RuntimeError("No daily rankings were generated.")
    latest_date = max(rankings)
    print(f"  Trading dates: {len(rankings)} | Latest: {latest_date.date()}")

    print("\nAggregating repeat and >=4% counts...")
    summary = aggregate_symbol_counts(rankings, price_by_symbol)

    write_outputs(summary, rankings, price_by_symbol)
    print(f"\n  Saved -> {SUMMARY_MD}")
    print(f"  Saved -> {SUMMARY_CSV}")
    print(f"  Saved -> {SUMMARY_JSON}")
    print(f"  Saved -> {DAILY_MD}")
    print(f"  Saved -> {HTML_DASHBOARD}")
    print(f"  Saved -> {WEEKLY_HTML_DASHBOARD}")
    print(f"  Saved -> {MONTHLY_HTML_DASHBOARD}")
    print(f"  Saved -> {COMMON_HTML_DASHBOARD}")


if __name__ == "__main__":
    main()

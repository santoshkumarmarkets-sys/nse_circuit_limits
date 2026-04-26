# Top Gainers Repeat Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a scanner that finds daily top 50 NSE gainers across the latest 1 week, 1 month, and 3 months, then counts how often each stock repeats and how many days it closes up at least 4%.

**Architecture:** Add a new focused `top_gainers_scanner.py` module that fetches an NSE equity universe, downloads recent OHLC data, builds daily top-50 gainers lists, and aggregates per-symbol repeat counts. Keep pure ranking/counting logic testable without network calls, and write Markdown/CSV/JSON outputs into a new `top_gainers/` directory.

**Tech Stack:** Python 3, pandas, yfinance, tradingview-screener, pytest for local unit tests.

---

## File Structure

- Create: `top_gainers_scanner.py`
  - Owns universe fetch, OHLC fetch, ranking logic, per-symbol count aggregation, Markdown/CSV/JSON rendering, and CLI entrypoint.
- Create: `tests/test_top_gainers_scanner.py`
  - Covers ranking, date-window selection, repeat counting, 4% up-day counting, and empty/missing-data cases using deterministic pandas fixtures.
- Create: `run_top_gainers_scanner.ps1`
  - Runs the scanner consistently on Windows PowerShell.
- Create output directory at runtime: `top_gainers/`
  - `top_gainers_summary.md`: human-readable report.
  - `top_gainers_summary.csv`: one row per symbol with counts.
  - `top_gainers_summary.json`: structured data for future dashboards.
  - `top_gainers_daily.md`: date-by-date top 50 lists for audit.
- Modify: `requirements.txt`
  - Add `pytest` so the test suite can run locally.
- Optional later modify: `dashboard_generator.py`
  - Only after scanner output is stable, add this report into `dashboard.html`.

## Definitions

- `top 50 gainers`: For each trading date, rank stocks by daily percent change: `(Close / Previous Close - 1) * 100`, descending, and keep the first 50 positive movers.
- `last 1 week`: latest 5 available trading sessions ending at the latest downloaded trading date.
- `last 1 month`: latest 21 available trading sessions.
- `last 3 months`: latest 63 available trading sessions.
- `repeat count`: number of trading dates where a symbol appeared in that window's daily top 50 list.
- `up 4% count`: number of trading dates where a symbol's daily percent change was greater than or equal to `4.0` in that window, whether or not it was in the daily top 50.
- `per-day detail`: for each symbol, store dates where it appeared in the top 50 and dates where it was up at least 4%, including day change and rank when available.

---

### Task 1: Add Pure Ranking And Aggregation Tests

**Files:**
- Create: `tests/test_top_gainers_scanner.py`
- Create later in Task 2: `top_gainers_scanner.py`

- [ ] **Step 1: Write failing tests for daily ranking**

```python
import pandas as pd

from top_gainers_scanner import build_daily_rankings


def make_prices():
    dates = pd.to_datetime(["2026-04-20", "2026-04-21", "2026-04-22"])
    return {
        "AAA": pd.DataFrame({"Close": [100.0, 110.0, 111.0]}, index=dates),
        "BBB": pd.DataFrame({"Close": [100.0, 106.0, 120.0]}, index=dates),
        "CCC": pd.DataFrame({"Close": [100.0, 103.0, 104.0]}, index=dates),
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_top_gainers_scanner.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'top_gainers_scanner'`.

- [ ] **Step 3: Commit test**

```bash
git add tests/test_top_gainers_scanner.py
git commit -m "test: cover top gainer daily rankings"
```

---

### Task 2: Implement Daily Ranking Logic

**Files:**
- Create: `top_gainers_scanner.py`
- Test: `tests/test_top_gainers_scanner.py`

- [ ] **Step 1: Add minimal ranking implementation**

```python
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
from typing import Any

import pandas as pd
import yfinance as yf
from tradingview_screener import Query, col


REPO_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(REPO_DIR, "top_gainers")
SUMMARY_MD = os.path.join(OUT_DIR, "top_gainers_summary.md")
SUMMARY_CSV = os.path.join(OUT_DIR, "top_gainers_summary.csv")
SUMMARY_JSON = os.path.join(OUT_DIR, "top_gainers_summary.json")
DAILY_MD = os.path.join(OUT_DIR, "top_gainers_daily.md")

WINDOWS = {
    "1w": 5,
    "1m": 21,
    "3m": 63,
}


def _normalize_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "Close" not in df.columns:
        return pd.DataFrame(columns=["Close"])
    normalized = df[["Close"]].dropna().copy()
    normalized.index = pd.to_datetime([idx.date() for idx in normalized.index])
    return normalized[~normalized.index.duplicated(keep="last")]


def build_daily_rankings(
    price_by_symbol: dict[str, pd.DataFrame],
    top_n: int = 50,
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
            rows_by_date[pd.Timestamp(trade_date)].append(
                {
                    "symbol": symbol,
                    "day_change_pct": round(float(day_change_pct), 2),
                    "close": round(float(df.loc[trade_date, "Close"]), 2),
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
```

- [ ] **Step 2: Run ranking tests**

Run: `pytest tests/test_top_gainers_scanner.py -v`

Expected: PASS for both ranking tests.

- [ ] **Step 3: Commit implementation**

```bash
git add top_gainers_scanner.py tests/test_top_gainers_scanner.py
git commit -m "feat: build daily top gainer rankings"
```

---

### Task 3: Add Window Selection And Repeat Counts

**Files:**
- Modify: `top_gainers_scanner.py`
- Modify: `tests/test_top_gainers_scanner.py`

- [ ] **Step 1: Write failing aggregation tests**

Append to `tests/test_top_gainers_scanner.py`:

```python
from top_gainers_scanner import aggregate_symbol_counts


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
    price_by_symbol = make_prices()

    result = aggregate_symbol_counts(rankings, price_by_symbol, windows={"1w": 2, "1m": 3, "3m": 3})
    by_symbol = {row["symbol"]: row for row in result}

    assert by_symbol["AAA"]["top50_1w_count"] == 1
    assert by_symbol["AAA"]["top50_1m_count"] == 2
    assert by_symbol["BBB"]["top50_1w_count"] == 1
    assert by_symbol["BBB"]["top50_1m_count"] == 2
    assert by_symbol["CCC"]["top50_1m_count"] == 1


def test_aggregate_symbol_counts_counts_four_percent_up_days_by_window():
    rankings = build_daily_rankings(make_prices(), top_n=2)

    result = aggregate_symbol_counts(rankings, make_prices(), windows={"1w": 2, "1m": 3, "3m": 3})
    by_symbol = {row["symbol"]: row for row in result}

    assert by_symbol["AAA"]["up4_1w_count"] == 0
    assert by_symbol["AAA"]["up4_1m_count"] == 1
    assert by_symbol["BBB"]["up4_1w_count"] == 1
    assert by_symbol["BBB"]["up4_1m_count"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_top_gainers_scanner.py -v`

Expected: FAIL with `ImportError` for `aggregate_symbol_counts`.

- [ ] **Step 3: Implement aggregation**

Append to `top_gainers_scanner.py`:

```python
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

    summary: list[dict[str, Any]] = []
    for symbol in sorted(symbols):
        row: dict[str, Any] = {"symbol": symbol}
        for window_name in active_windows:
            row[f"top50_{window_name}_count"] = len(top50_lookup[symbol][window_name])
            row[f"up4_{window_name}_count"] = len(up4_lookup[symbol][window_name])
            row[f"top50_{window_name}_days"] = top50_lookup[symbol][window_name]
            row[f"up4_{window_name}_days"] = up4_lookup[symbol][window_name]
        summary.append(row)

    return sorted(
        summary,
        key=lambda row: (
            row.get("top50_3m_count", 0),
            row.get("top50_1m_count", 0),
            row.get("top50_1w_count", 0),
            row.get("up4_3m_count", 0),
            row["symbol"],
        ),
        reverse=True,
    )
```

- [ ] **Step 4: Run aggregation tests**

Run: `pytest tests/test_top_gainers_scanner.py -v`

Expected: PASS.

- [ ] **Step 5: Commit aggregation**

```bash
git add top_gainers_scanner.py tests/test_top_gainers_scanner.py
git commit -m "feat: count repeated top gainers by window"
```

---

### Task 4: Add Network Fetching And CLI

**Files:**
- Modify: `top_gainers_scanner.py`

- [ ] **Step 1: Add NSE universe fetch**

Append to `top_gainers_scanner.py` before output functions:

```python
def get_nse_equity_universe(limit: int = 2000) -> list[str]:
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
```

- [ ] **Step 2: Add yfinance download**

Append to `top_gainers_scanner.py`:

```python
def fetch_price_history(symbols: list[str], period: str = "4mo") -> dict[str, pd.DataFrame]:
    price_by_symbol: dict[str, pd.DataFrame] = {}
    for index, symbol in enumerate(symbols, start=1):
        print(f"  {symbol:<20} ({index}/{len(symbols)})", end="\r")
        try:
            df = yf.Ticker(f"{symbol}.NS").history(period=period, auto_adjust=False)
        except Exception:
            df = pd.DataFrame()
        normalized = _normalize_price_frame(df)
        if len(normalized) >= 2:
            price_by_symbol[symbol] = normalized
    print("")
    return price_by_symbol
```

- [ ] **Step 3: Add CLI main**

Append to `top_gainers_scanner.py`:

```python
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

    write_outputs(summary, rankings)
    print(f"\n  Saved -> {SUMMARY_MD}")
    print(f"  Saved -> {SUMMARY_CSV}")
    print(f"  Saved -> {SUMMARY_JSON}")
    print(f"  Saved -> {DAILY_MD}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_top_gainers_scanner.py -v`

Expected: PASS.

- [ ] **Step 5: Commit fetch and CLI**

```bash
git add top_gainers_scanner.py
git commit -m "feat: fetch NSE histories for top gainers"
```

---

### Task 5: Render Markdown, CSV, And JSON Outputs

**Files:**
- Modify: `top_gainers_scanner.py`
- Output runtime creates: `top_gainers/top_gainers_summary.md`
- Output runtime creates: `top_gainers/top_gainers_summary.csv`
- Output runtime creates: `top_gainers/top_gainers_summary.json`
- Output runtime creates: `top_gainers/top_gainers_daily.md`

- [ ] **Step 1: Add compact date list helper**

Append above `write_outputs` in `top_gainers_scanner.py`:

```python
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
```

- [ ] **Step 2: Add summary writer**

Append to `top_gainers_scanner.py`:

```python
def build_summary_markdown(summary: list[dict[str, Any]], rankings: dict[pd.Timestamp, list[dict[str, Any]]]) -> str:
    latest_date = max(rankings).strftime("%Y-%m-%d") if rankings else ""
    lines = [
        f"# NSE Top Gainers Repeat Analysis - {latest_date}",
        f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} IST*",
        "",
        "Counts are based on daily top 50 gainers. Windows use latest 5, 21, and 63 trading sessions.",
        "",
        "| Symbol | Top50 1W | Top50 1M | Top50 3M | Up >=4% 1W | Up >=4% 1M | Up >=4% 3M | 1W Top50 Days | 1M Top50 Days | 3M Top50 Days |",
        "|--------|----------:|----------:|----------:|-----------:|-----------:|-----------:|---------------|---------------|---------------|",
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
            f"| {_format_top50_days(row['top50_1w_days'])} "
            f"| {_format_top50_days(row['top50_1m_days'])} "
            f"| {_format_top50_days(row['top50_3m_days'])} |"
        )
    return "\n".join(lines) + "\n"
```

- [ ] **Step 3: Add daily audit writer**

Append to `top_gainers_scanner.py`:

```python
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
```

- [ ] **Step 4: Add file writer**

Append to `top_gainers_scanner.py`:

```python
def write_outputs(summary: list[dict[str, Any]], rankings: dict[pd.Timestamp, list[dict[str, Any]]]) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    with open(SUMMARY_MD, "w", encoding="utf-8") as fh:
        fh.write(build_summary_markdown(summary, rankings))

    csv_rows = []
    for row in summary:
        csv_rows.append(
            {
                "symbol": row["symbol"],
                "top50_1w_count": row["top50_1w_count"],
                "top50_1m_count": row["top50_1m_count"],
                "top50_3m_count": row["top50_3m_count"],
                "up4_1w_count": row["up4_1w_count"],
                "up4_1m_count": row["up4_1m_count"],
                "up4_3m_count": row["up4_3m_count"],
                "top50_1w_days": _format_top50_days(row["top50_1w_days"]),
                "top50_1m_days": _format_top50_days(row["top50_1m_days"]),
                "top50_3m_days": _format_top50_days(row["top50_3m_days"]),
                "up4_1w_days": _format_up4_days(row["up4_1w_days"]),
                "up4_1m_days": _format_up4_days(row["up4_1m_days"]),
                "up4_3m_days": _format_up4_days(row["up4_3m_days"]),
            }
        )
    pd.DataFrame(csv_rows).to_csv(SUMMARY_CSV, index=False)

    with open(SUMMARY_JSON, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    with open(DAILY_MD, "w", encoding="utf-8") as fh:
        fh.write(build_daily_markdown(rankings))
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_top_gainers_scanner.py -v`

Expected: PASS.

- [ ] **Step 6: Commit output rendering**

```bash
git add top_gainers_scanner.py
git commit -m "feat: render top gainer reports"
```

---

### Task 6: Add PowerShell Runner And Dependency

**Files:**
- Create: `run_top_gainers_scanner.ps1`
- Modify: `requirements.txt`

- [ ] **Step 1: Add runner**

Create `run_top_gainers_scanner.ps1`:

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

python .\top_gainers_scanner.py
```

- [ ] **Step 2: Add test dependency**

Append to `requirements.txt`:

```text
pytest
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_top_gainers_scanner.py -v`

Expected: PASS.

- [ ] **Step 4: Run scanner**

Run: `powershell -ExecutionPolicy Bypass -File .\run_top_gainers_scanner.ps1`

Expected:
- Console prints universe count, downloaded price history count, trading date count, and saved file paths.
- `top_gainers/top_gainers_summary.md` exists.
- `top_gainers/top_gainers_summary.csv` exists.
- `top_gainers/top_gainers_summary.json` exists.
- `top_gainers/top_gainers_daily.md` exists.

- [ ] **Step 5: Commit runner and dependency**

```bash
git add requirements.txt run_top_gainers_scanner.ps1 top_gainers_scanner.py tests/test_top_gainers_scanner.py
git commit -m "chore: add top gainers runner"
```

---

### Task 7: Validate Real Output Quality

**Files:**
- Runtime outputs in `top_gainers/`

- [ ] **Step 1: Inspect generated summary**

Run: `Get-Content .\top_gainers\top_gainers_summary.md -TotalCount 80`

Expected:
- Header date equals latest available market date.
- Table contains symbols with non-zero top50 counts.
- Counts are integers.
- Day detail columns show dates, ranks, and daily percent changes.

- [ ] **Step 2: Inspect generated CSV**

Run: `Import-Csv .\top_gainers\top_gainers_summary.csv | Select-Object -First 10 | Format-Table`

Expected:
- Rows have `symbol`, `top50_1w_count`, `top50_1m_count`, `top50_3m_count`, `up4_1w_count`, `up4_1m_count`, and `up4_3m_count`.

- [ ] **Step 3: Confirm repeated-count consistency**

Run:

```powershell
Import-Csv .\top_gainers\top_gainers_summary.csv |
  Where-Object { [int]$_.top50_3m_count -lt [int]$_.top50_1m_count -or [int]$_.top50_1m_count -lt [int]$_.top50_1w_count } |
  Format-Table
```

Expected: no rows, because a 3-month window contains the 1-month window, and a 1-month window contains the 1-week window.

- [ ] **Step 4: Commit generated outputs only if this repo tracks scan artifacts**

If existing generated scan outputs are normally committed, run:

```bash
git add top_gainers/top_gainers_summary.md top_gainers/top_gainers_summary.csv top_gainers/top_gainers_summary.json top_gainers/top_gainers_daily.md
git commit -m "data: add latest top gainer repeat report"
```

If generated outputs should remain local, leave them uncommitted.

---

## Self-Review

- Spec coverage:
  - Top 50 gainers in last one week: Task 3 counts latest 5 trading sessions; Task 5 renders `top50_1w_count` and dates.
  - Top gainers in last one month: Task 3 counts latest 21 trading sessions; Task 5 renders `top50_1m_count` and dates.
  - Top gainers in last three months: Task 3 counts latest 63 trading sessions; Task 5 renders `top50_3m_count` and dates.
  - Repeated count: Task 3 implements per-window top50 repeat counts.
  - Count of days up by 4%: Task 3 implements `up4_*_count` and detailed dates.
  - Each-day visibility: Task 5 writes both per-symbol day details and `top_gainers_daily.md`.
- Placeholder scan: no task uses TBD, TODO, or undefined later work.
- Type consistency: `rankings` is consistently `dict[pd.Timestamp, list[dict[str, Any]]]`; summary rows consistently use `top50_{window}_count`, `top50_{window}_days`, `up4_{window}_count`, and `up4_{window}_days`.


# Top Week Gainers Dashboard Design

## Goal

Create a new dashboard for NSE top week gainers that mirrors the existing top gainers dashboard, but ranks rows by cumulative percent gain over the latest 5 trading days instead of today's daily gain.

## Scope

The new output file is `top_gainers/top_week_gainers_dashboard.html`.

The existing `top_gainers/top_gainers_dashboard.html` stays focused on today's daily top 50 gainers. The new weekly dashboard uses the same data pipeline and visual style, but its table contains the top 50 symbols by 5-trading-day cumulative gain.

## User-Facing Behavior

The weekly dashboard shows the top 50 NSE stocks by cumulative gain over the latest 5 available trading sessions. Cumulative gain is calculated from the latest close divided by the close from 5 sessions earlier, minus 1.

Rows are sorted by `Gain 1W` descending by default. The table keeps sortable columns like the existing dashboard.

The weekly dashboard uses the same columns as the current top gainers dashboard:

| Column | Meaning |
| --- | --- |
| Rank | Rank in the weekly top 50 list |
| Symbol | NSE symbol linked to TradingView |
| Sector | TradingView sector and industry |
| Close | Latest close |
| Day Chg | Latest daily percent change |
| Gain 1W | Cumulative 5-trading-day gain |
| Gain 1M | Existing 21-trading-session gain |
| Gain 3M | Existing 63-trading-session gain |
| Circuit | Current circuit limit label from existing circuit map |
| Top50 1W | Existing latest-5-session daily top-50 appearance count |
| Top50 1M | Existing latest-21-session daily top-50 appearance count |
| Top50 3M | Existing latest-63-session daily top-50 appearance count |
| Up >=4% 1W | Existing latest-5-session up-day count |
| Up >=4% 1M | Existing latest-21-session up-day count |
| Up >=4% 3M | Existing latest-63-session up-day count |
| Down >4% 1W | Existing latest-5-session down-day count |
| Down >4% 1M | Existing latest-21-session down-day count |
| Down >4% 3M | Existing latest-63-session down-day count |

The table title should clearly say `Top 50 Weekly Gainers - sortable counts`.

## Architecture

Keep the feature inside `top_gainers_scanner.py` because the current scanner already owns universe fetching, price history fetching, sector enrichment, circuit enrichment, summary aggregation, and HTML rendering.

Add a pure weekly ranking function that accepts `price_by_symbol` and returns weekly ranking rows. This function should not perform network calls. It should use normalized daily close data, require at least 6 close points for a 5-session cumulative return, and skip symbols whose latest close is below the existing minimum close threshold.

Extend the HTML rendering layer with a weekly dashboard builder. The weekly dashboard must reuse the existing dashboard styling, watchlist tab, journal tab, sector display, circuit display, percentage formatting, and sortable table JavaScript.

## Data Flow

1. `main()` fetches the NSE equity universe.
2. `main()` fetches 4 months of daily price history.
3. Existing code builds daily top-50 rankings.
4. Existing code aggregates repeat counts and 1W, 1M, and 3M gains.
5. New code builds weekly top-50 rows from the same `price_by_symbol`.
6. `write_outputs()` writes the existing Markdown, CSV, JSON, daily Markdown, and daily dashboard.
7. `write_outputs()` also writes `top_gainers/top_week_gainers_dashboard.html`.

## Weekly Row Contract

Each weekly row should include:

| Field | Description |
| --- | --- |
| `symbol` | NSE symbol |
| `rank` | Weekly rank, starting at 1 |
| `weekly_gain_pct` | Cumulative 5-trading-day gain, rounded to 2 decimals |
| `close` | Latest close, rounded to 2 decimals |
| `day_change_pct` | Latest one-day percent change, rounded to 2 decimals |
| `start_close` | Close from 5 sessions before the latest close, rounded to 2 decimals |

The dashboard must display `weekly_gain_pct` through the existing `Gain 1W` column so the visible columns stay aligned with the current dashboard.

## Error Handling

Symbols are skipped when they have fewer than 6 valid closes, missing latest close, missing lookback close, zero or negative lookback close, or latest close below the minimum close threshold.

If no weekly rows are available, the dashboard should still render a table with the same empty-state behavior as the existing dashboard.

## Testing

Add tests before implementation:

- Weekly ranking calculates cumulative gain from the close 5 sessions earlier to the latest close.
- Weekly ranking orders symbols by cumulative 5-day gain descending and assigns ranks.
- Weekly ranking skips symbols with fewer than 6 close values.
- Weekly dashboard HTML uses the weekly title and includes the same column labels as the existing dashboard.
- Existing top gainers dashboard tests continue to pass.

## Out Of Scope

This change does not add a new data source, change the existing daily dashboard behavior, alter watchlist or journal behavior, or create a separate runner script. The existing `run_top_gainers_scanner.ps1` should generate both dashboards through the current scanner.

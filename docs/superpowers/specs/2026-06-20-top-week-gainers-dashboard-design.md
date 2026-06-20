# Top Period Gainers Dashboards Design

## Goal

Create new NSE period-gainers dashboards that mirror the existing top gainers dashboard, but rank rows by cumulative percent gain over longer trading windows instead of today's daily gain.

## Scope

The new output files are:

- `top_gainers/top_week_gainers_dashboard.html`
- `top_gainers/top_month_gainers_dashboard.html`
- `top_gainers/top_common_gainers_dashboard.html`

The existing `top_gainers/top_gainers_dashboard.html` stays focused on today's daily top 50 gainers. The new period dashboards use the same data pipeline and visual style, but their row sets come from cumulative return rankings.

## User-Facing Behavior

The weekly dashboard shows the top 50 NSE stocks by cumulative gain over the latest 5 available trading sessions. Cumulative gain is calculated from the latest close divided by the close from 5 sessions earlier, minus 1.

The monthly dashboard shows the top 50 NSE stocks by cumulative gain over the latest 21 available trading sessions. Cumulative gain is calculated from the latest close divided by the close from 21 sessions earlier, minus 1.

The common dashboard shows only stocks that appear in all three cumulative-gainer lists:

- Top 50 by 1M cumulative gain, using 21 trading sessions.
- Top 50 by 2M cumulative gain, using 42 trading sessions.
- Top 50 by 3M cumulative gain, using 63 trading sessions.

Weekly rows are sorted by `Gain 1W` descending by default. Monthly rows are sorted by `Gain 1M` descending by default. Common rows are sorted by `Gain 1M` descending by default. All tables keep sortable columns like the existing dashboard.

The weekly and monthly dashboards use the same columns as the current top gainers dashboard:

| Column | Meaning |
| --- | --- |
| Rank | Rank in the dashboard's row set |
| Symbol | NSE symbol linked to TradingView |
| Sector | TradingView sector and industry |
| Close | Latest close |
| Day Chg | Latest daily percent change |
| Gain 1W | Existing 5-trading-session gain, or the active ranking value on the weekly dashboard |
| Gain 1M | Existing 21-trading-session gain, or the active ranking value on the monthly dashboard |
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

The common dashboard uses the same columns and adds `Gain 2M` between `Gain 1M` and `Gain 3M`.

Table titles:

- Weekly dashboard: `Top 50 Weekly Gainers - sortable counts`
- Monthly dashboard: `Top 50 Monthly Gainers - sortable counts`
- Common dashboard: `Common 1M / 2M / 3M Gainers - sortable counts`

## Architecture

Keep the feature inside `top_gainers_scanner.py` because the current scanner already owns universe fetching, price history fetching, sector enrichment, circuit enrichment, summary aggregation, and HTML rendering.

Add a pure cumulative ranking function that accepts `price_by_symbol`, a window length, and a gain field name. This function should not perform network calls. It should use normalized daily close data, require enough close points for the requested window, and skip symbols whose latest close is below the existing minimum close threshold.

Use the cumulative ranking function to build:

- Weekly rows: 5 trading sessions, top 50, ranking field `weekly_gain_pct`.
- Monthly rows: 21 trading sessions, top 50, ranking field `monthly_gain_pct`.
- Two-month rows: 42 trading sessions, top 50, ranking field `gain_2m_pct`.
- Three-month rows: 63 trading sessions, top 50, ranking field `gain_3m_pct`.
- Common rows: intersection of symbols from the 1M, 2M, and 3M top-50 lists.

Extend the HTML rendering layer with configurable period dashboard builders. These dashboards must reuse the existing dashboard styling, watchlist tab, journal tab, sector display, circuit display, percentage formatting, and sortable table JavaScript.

## Data Flow

1. `main()` fetches the NSE equity universe.
2. `main()` fetches 4 months of daily price history.
3. Existing code builds daily top-50 rankings.
4. Existing code aggregates repeat counts and 1W, 1M, and 3M gains.
5. New code builds weekly, monthly, two-month, and three-month cumulative top-50 rows from the same `price_by_symbol`.
6. New code derives common rows from the 1M, 2M, and 3M cumulative top-50 symbol intersection.
7. `write_outputs()` writes the existing Markdown, CSV, JSON, daily Markdown, and daily dashboard.
8. `write_outputs()` also writes the weekly, monthly, and common dashboard HTML files.

## Period Row Contract

Each cumulative ranking row should include:

| Field | Description |
| --- | --- |
| `symbol` | NSE symbol |
| `rank` | Rank in the relevant row set, starting at 1 |
| active gain field | Cumulative gain for the active window, rounded to 2 decimals |
| `close` | Latest close, rounded to 2 decimals |
| `day_change_pct` | Latest one-day percent change, rounded to 2 decimals |
| `start_close` | Close from the requested window length before the latest close, rounded to 2 decimals |

The weekly dashboard must display `weekly_gain_pct` through `Gain 1W`. The monthly dashboard must display `monthly_gain_pct` through `Gain 1M`. The common dashboard must display `gain_2m_pct` through the extra `Gain 2M` column while retaining `Gain 1W`, `Gain 1M`, and `Gain 3M`.

## Error Handling

Symbols are skipped when they have too few valid closes for the requested window, missing latest close, missing lookback close, zero or negative lookback close, or latest close below the minimum close threshold.

If no rows are available for any new dashboard, that dashboard should still render a table with the same empty-state behavior as the existing dashboard.

## Testing

Add tests before implementation:

- Cumulative ranking calculates gain from the requested lookback close to the latest close.
- Cumulative ranking orders symbols by requested-window gain descending and assigns ranks.
- Cumulative ranking skips symbols with insufficient close values.
- Weekly dashboard HTML uses the weekly title and includes the same column labels as the existing dashboard.
- Monthly dashboard HTML uses the monthly title and displays the monthly ranking value in `Gain 1M`.
- Common dashboard HTML uses the common title, includes `Gain 2M`, and only contains symbols common to the 1M, 2M, and 3M top-50 cumulative lists.
- Existing top gainers dashboard tests continue to pass.

## Out Of Scope

This change does not add a new data source, change the existing daily dashboard behavior, alter watchlist or journal behavior, or create a separate runner script. The existing `run_top_gainers_scanner.ps1` should generate all dashboards through the current scanner.

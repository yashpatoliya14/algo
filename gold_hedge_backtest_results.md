# XAUTUSD SuperTrend + PAXGUSD Hedge-Grid — Backtest Results

_Generated 2026-09-27 10:56 UTC_

## Strategy

SuperTrend(10, 3) on **XAUTUSD 4H** is the only signal generator.

- **Bullish flip** → LONG 10 lots XAUTUSD (trailing SuperTrend stop). Each +1% step shorts 1 lot PAXGUSD (grid +1%…+5%, max 5). A 1% retrace closes the top PAXGUSD lot in profit; a re-cross re-adds it. +10% on XAUTUSD closes everything.

- **Bearish flip** → mirror: SHORT XAUTUSD, LONG PAXGUSD on each −1% step.

- Exits also trigger on SuperTrend flip against the position, which closes all hedges.

## Setup

| Parameter | Value |
|---|---|
| Signal / data source | Delta Exchange, 4H candles |
| Main / hedge symbols | XAUTUSD / PAXGUSD |
| SuperTrend | period 10, multiplier 3 |
| Starting capital | $100.00 |
| Lot size | 0.001 oz (XAUTUSD: 10 lots = 0.01 oz; PAXGUSD: 0.001 oz/lot) |
| Grid step / max lots / TP | 1% / 5 / 10% |
| Backtest window | 2026-04-17 → 2026-09-27 (977 bars) |
| Decision basis | 4H close prices |

## Headline Results

| Metric | Value |
|---|---|
| **Final equity** | $107.66 |
| **Total return** | +7.66% |
| Net P&L | $+7.6574 |
| — XAUTUSD (main) P&L | $+6.9260 |
| — PAXGUSD (hedge) P&L | $+0.7314 |
| Total trades | 78 (23 main / 55 hedge) |
| Win rate | 64.1% |
| Profit factor | 2.10 |
| Sharpe / Sortino (ann.) | 2.30 / 3.00 |
| Max drawdown | -2.09% |
| Largest win / loss | $+2.7280 / $-1.4079 |

## Equity Curve

`▁▁▁▂▁▂▁▁▂▂▂▂▂▃▄▅▅▄▄▄▅▅▅▅▆▅▅▅▆▆▆▅▆▆▇▇▇▇█▇▇`  $100.00 → $107.66

## Monthly Returns

| Month | Return |
|---|--:|
| 2026-04 | +0.65% |
| 2026-05 | +1.52% |
| 2026-06 | +2.37% |
| 2026-07 | +0.36% |
| 2026-08 | +3.09% |
| 2026-09 | -0.52% |

## Main (XAUTUSD) Trades

| # | Dir | Entry | Entry $ | Exit | Exit $ | P&L $ | Reason |
|--:|:--|:--|--:|:--|--:|--:|:--|
| 1 | short | 2026-04-21 16:00 | 4,665.86 | 2026-05-06 00:00 | 4,627.60 | +0.3826 | supertrend_stop |
| 2 | long | 2026-05-06 00:00 | 4,627.60 | 2026-05-11 00:00 | 4,672.21 | +0.4461 | supertrend_stop |
| 3 | short | 2026-05-11 00:00 | 4,672.21 | 2026-05-11 12:00 | 4,720.33 | -0.4812 | supertrend_stop |
| 4 | long | 2026-05-11 12:00 | 4,720.33 | 2026-05-14 16:00 | 4,650.11 | -0.7022 | supertrend_stop |
| 5 | short | 2026-05-14 16:00 | 4,650.11 | 2026-05-28 16:00 | 4,485.96 | +1.6415 | supertrend_stop |
| 6 | long | 2026-05-28 16:00 | 4,485.96 | 2026-06-01 12:00 | 4,468.33 | -0.1763 | supertrend_stop |
| 7 | short | 2026-06-01 12:00 | 4,468.33 | 2026-06-11 16:00 | 4,195.53 | +2.7280 | supertrend_stop |
| 8 | long | 2026-06-11 16:00 | 4,195.53 | 2026-06-17 16:00 | 4,225.98 | +0.3045 | supertrend_stop |
| 9 | short | 2026-06-17 16:00 | 4,225.98 | 2026-06-22 08:00 | 4,198.44 | +0.2754 | supertrend_stop |
| 10 | long | 2026-06-22 08:00 | 4,198.44 | 2026-06-23 04:00 | 4,092.98 | -1.0546 | supertrend_stop |
| 11 | short | 2026-06-23 04:00 | 4,092.98 | 2026-07-01 12:00 | 4,073.28 | +0.1970 | supertrend_stop |
| 12 | long | 2026-07-01 12:00 | 4,073.28 | 2026-07-07 00:00 | 4,129.64 | +0.5636 | supertrend_stop |
| 13 | short | 2026-07-07 00:00 | 4,129.64 | 2026-07-21 00:00 | 4,049.10 | +0.8054 | supertrend_stop |
| 14 | long | 2026-07-21 00:00 | 4,049.10 | 2026-07-23 12:00 | 4,046.81 | -0.0229 | supertrend_stop |
| 15 | short | 2026-07-23 12:00 | 4,046.81 | 2026-07-30 12:00 | 4,089.26 | -0.4245 | supertrend_stop |
| 16 | long | 2026-07-30 12:00 | 4,089.26 | 2026-08-18 20:00 | 4,332.01 | +2.4275 | supertrend_stop |
| 17 | short | 2026-08-18 20:00 | 4,332.01 | 2026-08-19 12:00 | 4,472.80 | -1.4079 | supertrend_stop |
| 18 | long | 2026-08-19 12:00 | 4,472.80 | 2026-08-28 00:00 | 4,573.36 | +1.0056 | supertrend_stop |
| 19 | short | 2026-08-28 00:00 | 4,573.36 | 2026-09-03 00:00 | 4,429.29 | +1.4407 | supertrend_stop |
| 20 | long | 2026-09-03 00:00 | 4,429.29 | 2026-09-08 16:00 | 4,366.40 | -0.6289 | supertrend_stop |
| 21 | short | 2026-09-08 16:00 | 4,366.40 | 2026-09-17 12:00 | 4,371.83 | -0.0543 | supertrend_stop |
| 22 | long | 2026-09-17 12:00 | 4,371.83 | 2026-09-22 04:00 | 4,313.18 | -0.5865 | supertrend_stop |
| 23 | short | 2026-09-22 04:00 | 4,313.18 | 2026-09-27 08:00 | 4,288.44 | +0.2474 | end_of_data |

## Hedge (PAXGUSD) Trades

| # | Side | Step | Entry | Entry $ | Exit | Exit $ | P&L $ | Reason |
|--:|:--|--:|:--|--:|:--|--:|--:|:--|
| 1 | long | 2 | 2026-04-28 08:00 | 4,557.00 | 2026-04-30 08:00 | 4,620.70 | +0.0637 | retrace_1pct |
| 2 | long | 2 | 2026-05-01 04:00 | 4,570.50 | 2026-05-01 12:00 | 4,630.00 | +0.0595 | retrace_1pct |
| 3 | long | 3 | 2026-05-04 12:00 | 4,516.30 | 2026-05-05 20:00 | 4,581.20 | +0.0649 | retrace_1pct |
| 4 | long | 2 | 2026-05-04 08:00 | 4,554.00 | 2026-05-06 00:00 | 4,631.40 | +0.0774 | supertrend_stop |
| 5 | long | 1 | 2026-04-28 08:00 | 4,557.00 | 2026-05-06 00:00 | 4,631.40 | +0.0744 | supertrend_stop |
| 6 | short | 2 | 2026-05-07 04:00 | 4,729.30 | 2026-05-11 00:00 | 4,671.30 | +0.0580 | supertrend_stop |
| 7 | short | 1 | 2026-05-06 08:00 | 4,679.80 | 2026-05-11 00:00 | 4,671.30 | +0.0085 | supertrend_stop |
| 8 | long | 3 | 2026-05-19 16:00 | 4,490.30 | 2026-05-24 20:00 | 4,563.30 | +0.0730 | retrace_1pct |
| 9 | long | 5 | 2026-05-28 00:00 | 4,377.90 | 2026-05-28 12:00 | 4,473.60 | +0.0957 | retrace_1pct |
| 10 | long | 4 | 2026-05-27 08:00 | 4,437.40 | 2026-05-28 16:00 | 4,487.20 | +0.0498 | supertrend_stop |
| 11 | long | 3 | 2026-05-26 08:00 | 4,509.00 | 2026-05-28 16:00 | 4,487.20 | -0.0218 | supertrend_stop |
| 12 | long | 2 | 2026-05-15 12:00 | 4,542.00 | 2026-05-28 16:00 | 4,487.20 | -0.0548 | supertrend_stop |
| 13 | long | 1 | 2026-05-15 04:00 | 4,571.00 | 2026-05-28 16:00 | 4,487.20 | -0.0838 | supertrend_stop |
| 14 | short | 1 | 2026-05-29 12:00 | 4,557.00 | 2026-06-01 12:00 | 4,470.70 | +0.0863 | supertrend_stop |
| 15 | long | 5 | 2026-06-09 20:00 | 4,214.50 | 2026-06-11 16:00 | 4,200.10 | -0.0144 | supertrend_stop |
| 16 | long | 4 | 2026-06-06 12:00 | 4,288.10 | 2026-06-11 16:00 | 4,200.10 | -0.0880 | supertrend_stop |
| 17 | long | 3 | 2026-06-05 12:00 | 4,330.50 | 2026-06-11 16:00 | 4,200.10 | -0.1304 | supertrend_stop |
| 18 | long | 2 | 2026-06-05 12:00 | 4,330.50 | 2026-06-11 16:00 | 4,200.10 | -0.1304 | supertrend_stop |
| 19 | long | 1 | 2026-06-05 00:00 | 4,430.90 | 2026-06-11 16:00 | 4,200.10 | -0.2308 | supertrend_stop |
| 20 | short | 3 | 2026-06-15 12:00 | 4,343.90 | 2026-06-17 16:00 | 4,229.20 | +0.1147 | supertrend_stop |
| 21 | short | 2 | 2026-06-14 20:00 | 4,285.90 | 2026-06-17 16:00 | 4,229.20 | +0.0567 | supertrend_stop |
| 22 | short | 1 | 2026-06-14 20:00 | 4,285.90 | 2026-06-17 16:00 | 4,229.20 | +0.0567 | supertrend_stop |
| 23 | long | 2 | 2026-06-21 20:00 | 4,132.90 | 2026-06-22 08:00 | 4,200.30 | +0.0674 | supertrend_stop |
| 24 | long | 1 | 2026-06-18 20:00 | 4,181.10 | 2026-06-22 08:00 | 4,200.30 | +0.0192 | supertrend_stop |
| 25 | long | 2 | 2026-06-24 12:00 | 3,998.90 | 2026-06-26 12:00 | 4,083.30 | +0.0844 | retrace_1pct |
| 26 | long | 2 | 2026-06-30 00:00 | 3,966.20 | 2026-07-01 12:00 | 4,073.00 | +0.1068 | supertrend_stop |
| 27 | long | 1 | 2026-06-24 08:00 | 4,045.20 | 2026-07-01 12:00 | 4,073.00 | +0.0278 | supertrend_stop |
| 28 | short | 2 | 2026-07-03 00:00 | 4,164.70 | 2026-07-07 00:00 | 4,123.00 | +0.0417 | supertrend_stop |
| 29 | short | 1 | 2026-07-02 12:00 | 4,120.30 | 2026-07-07 00:00 | 4,123.00 | -0.0027 | supertrend_stop |
| 30 | long | 2 | 2026-07-08 12:00 | 4,030.90 | 2026-07-09 04:00 | 4,098.70 | +0.0678 | retrace_1pct |
| 31 | long | 3 | 2026-07-13 20:00 | 3,996.50 | 2026-07-14 12:00 | 4,057.80 | +0.0613 | retrace_1pct |
| 32 | long | 3 | 2026-07-16 16:00 | 3,979.90 | 2026-07-21 00:00 | 4,039.20 | +0.0593 | supertrend_stop |
| 33 | long | 2 | 2026-07-13 12:00 | 4,013.00 | 2026-07-21 00:00 | 4,039.20 | +0.0262 | supertrend_stop |
| 34 | long | 1 | 2026-07-08 08:00 | 4,057.10 | 2026-07-21 00:00 | 4,039.20 | -0.0179 | supertrend_stop |
| 35 | short | 2 | 2026-07-22 12:00 | 4,145.00 | 2026-07-23 04:00 | 4,086.80 | +0.0582 | retrace_1pct |
| 36 | short | 1 | 2026-07-22 00:00 | 4,116.20 | 2026-07-23 12:00 | 4,044.30 | +0.0719 | supertrend_stop |
| 37 | long | 1 | 2026-07-29 12:00 | 4,008.20 | 2026-07-29 20:00 | 4,076.40 | +0.0682 | retrace_1pct |
| 38 | short | 5 | 2026-08-07 08:00 | 4,312.10 | 2026-08-18 20:00 | 4,335.20 | -0.0231 | supertrend_stop |
| 39 | short | 4 | 2026-08-05 20:00 | 4,267.40 | 2026-08-18 20:00 | 4,335.20 | -0.0678 | supertrend_stop |
| 40 | short | 3 | 2026-08-05 12:00 | 4,220.60 | 2026-08-18 20:00 | 4,335.20 | -0.1146 | supertrend_stop |
| 41 | short | 2 | 2026-08-05 08:00 | 4,179.04 | 2026-08-18 20:00 | 4,335.20 | -0.1562 | supertrend_stop |
| 42 | short | 1 | 2026-08-05 04:00 | 4,163.50 | 2026-08-18 20:00 | 4,335.20 | -0.1717 | supertrend_stop |
| 43 | short | 4 | 2026-08-24 20:00 | 4,670.10 | 2026-08-26 12:00 | 4,589.59 | +0.0805 | retrace_1pct |
| 44 | short | 3 | 2026-08-23 20:00 | 4,612.50 | 2026-08-28 00:00 | 4,571.10 | +0.0414 | supertrend_stop |
| 45 | short | 2 | 2026-08-21 08:00 | 4,587.50 | 2026-08-28 00:00 | 4,571.10 | +0.0164 | supertrend_stop |
| 46 | short | 1 | 2026-08-21 04:00 | 4,553.90 | 2026-08-28 00:00 | 4,571.10 | -0.0172 | supertrend_stop |
| 47 | long | 5 | 2026-09-01 16:00 | 4,338.60 | 2026-09-02 16:00 | 4,399.60 | +0.0610 | retrace_1pct |
| 48 | long | 4 | 2026-09-01 08:00 | 4,380.80 | 2026-09-03 00:00 | 4,435.50 | +0.0547 | supertrend_stop |
| 49 | long | 3 | 2026-08-31 00:00 | 4,418.50 | 2026-09-03 00:00 | 4,435.50 | +0.0170 | supertrend_stop |
| 50 | long | 2 | 2026-08-28 16:00 | 4,459.90 | 2026-09-03 00:00 | 4,435.50 | -0.0244 | supertrend_stop |
| 51 | long | 1 | 2026-08-28 12:00 | 4,518.80 | 2026-09-03 00:00 | 4,435.50 | -0.0833 | supertrend_stop |
| 52 | short | 1 | 2026-09-03 12:00 | 4,493.40 | 2026-09-05 12:00 | 4,431.30 | +0.0621 | retrace_1pct |
| 53 | long | 1 | 2026-09-11 00:00 | 4,313.20 | 2026-09-11 12:00 | 4,369.90 | +0.0567 | retrace_1pct |
| 54 | long | 1 | 2026-09-14 04:00 | 4,316.90 | 2026-09-17 12:00 | 4,367.00 | +0.0501 | supertrend_stop |
| 55 | long | 1 | 2026-09-24 12:00 | 4,255.10 | 2026-09-27 08:00 | 4,280.40 | +0.0253 | end_of_data |

## Notes & Caveats

- **Short history.** XAUTUSD on Delta only lists from ~2026-04, so the overlapping window with PAXG is a few months — too short for statistically robust conclusions. Treat this as a mechanics check, not an edge validation.

- All decisions use 4H **close** prices (no intrabar fills), so the 10% TP and 1% grid levels are recognised at the first close beyond the level.

- P&L is tiny in absolute terms because 10 lots = 0.01 oz (~$40 notional) against $100 capital — by design, this keeps the account survivable. Scale `main_lots`/`contract_oz` in `GoldHedgeParams` to change notional.

- Fees, funding, and slippage are **not** modelled.

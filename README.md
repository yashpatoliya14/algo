# Gold Hedge-Grid — Delta Exchange Algo Trading

A two-leg gold strategy for Delta Exchange: **SuperTrend(10, 3) on XAUTUSD 4H** is the
only signal, and a **PAXGUSD hedge grid** scalps the intra-trend retracements. Backtest
and live trader share one decision core (`gold_hedge_engine.GoldHedgeStrategy`), so their
logic can never diverge — they differ only in how often price is sampled (backtest = 4H
close, live = mark price each poll).

## Strategy

- **Bullish flip** → LONG `MAIN_LOTS` lots XAUTUSD. Stop = the trailing SuperTrend line
  (exit on the opposite flip); take-profit at **+10%**. Each **+1%** the price travels in
  trend shorts 1 lot PAXGUSD (grid +1%…+5%, max 5). A 1% retrace closes the top hedge lot
  in profit; a re-cross re-adds it. +10% or a bear flip flattens everything.
- **Bearish flip** → exact mirror (SHORT XAUTUSD, LONG PAXGUSD on each −1% step, TP at −10%).
- Sizing: 1 lot = 0.001 oz = 1 Delta contract (both symbols have `contract_value = 0.001`).

## Quick start

1. Create a Python 3.10+ venv and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in API keys + (optional) Telegram credentials.
3. Run the backtest (writes `gold_hedge_backtest_results.md`):
   ```bash
   python gold_hedge_backtest.py
   ```
4. Start the trader — **paper mode by default** (`DRY_RUN="true"`):
   ```bash
   python delta_trader.py
   ```
   Real orders fire only when you set `DRY_RUN="false"`. Paper-run first.

## Configuration

All settings live in `.env` (see `.env.example` for the full list): instruments
(`MAIN_SYMBOL`, `HEDGE_SYMBOL`), signal (`TIMEFRAME`, `ST_PERIOD`, `ST_MULT`), sizing/grid
(`MAIN_LOTS`, `HEDGE_LOTS_PER_STEP`, `HEDGE_MAX_LOTS`, `STEP_PCT`, `TP_PCT`, `LEVERAGE`),
operation (`DRY_RUN`, `POLL_INTERVAL_SEC`), Delta API keys, and Telegram settings.

## Telegram

When configured, the trader sends startup/execution/exit messages and accepts control
commands (`status`, `open long|short`, `close`, `clear`, `/stop`).

## Layout

- `gold_hedge_engine.py` — indicators, `GoldHedgeStrategy` decision core, backtest driver, metrics.
- `gold_hedge_backtest.py` — data fetch + report generator (`gold_hedge_backtest_results.md`).
- `delta_trader.py` — live/paper executor (`DeltaClient` REST wrapper + `GoldHedgeTrader`).
- `telegram_notifier.py` — notifications and remote control.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design.

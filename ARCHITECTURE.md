# 🏛️ Architecture Documentation: 4H Crypto Trend Rider

## Simple explanation (plain language)

This project is a 4-hour trend-following trading system for Bitcoin. It watches 4-hour candles, decides whether the market is in an uptrend or downtrend, and looks for simple entry signals (a pullback to a moving average, a breakout, or a trend flip). When a signal appears, it sizes the trade using a risk-per-trade rule and manages exits with ATR-based stops and a small percentage trailing stop.

In short: detect trend → wait for clean signal in that trend → enter with controlled risk → trail stop to protect profits.

---

## Architecture (components)

- **Strategy engine**: `trend_rider_engine.py` — computes indicators (EMA21/55, ATR, Supertrend, Donchian), generates signals, and updates stop/trail logic.
- **Backtest & indicator helpers**: `crypto_trend_backtest.py` — data helpers and indicator math used for testing.
- **CLI backtester**: `backtest_cli.py` — run historical simulations and view performance summaries.
- **Live trader**: `delta_trader.py` — connects to Delta Exchange, reads signals, and places orders.
- **Tests**: `test_delta_order.py` — unit tests for order logic.
- **Cache**: `cache/` — stores downloaded or computed datasets for faster backtests (e.g., `rider_2022.json`).

Diagram (logical):

```
Market Data (4H) --> Backtest / Live Adapter --> Trend Engine --> Risk & Order Manager --> Exchange
```

---

## How the algorithm decides (step-by-step)

1. Compute short and long EMAs (21 & 55), Supertrend, ATR, and Donchian channels on 4H candles.
2. Determine regime:
   - Bullish if EMA21 > EMA55, Supertrend is bullish, and EMA21 slope is upward.
   - Bearish if EMA21 < EMA55, Supertrend is bearish, and EMA21 slope is downward.
3. Generate entry signals only when signal matches the current regime:
   - Pullback to EMA21 and a confirming candle in trend direction.
   - Breakout above/below Donchian channel when aligned with regime.
   - Supertrend flip that confirms EMA alignment.
4. Calculate position size with a fixed risk percent of account equity and the distance from entry to stop.
5. Place entry + initial stop (stop = entry ± 2 × ATR). When price moves a small profit amount, enable a tight trailing stop (e.g., 0.4% behind peak).

---

## Key parameters to tune (where to look)

- Trend EMAs: `21`, `55` in `trend_rider_engine.py`.
- Supertrend: look for its length & multiplier (e.g., `10, 3`).
- Donchian length: `30` periods (used for breakouts).
- ATR multiplier for stops: `2.0` (initial stop), trail activation & trail distance in engine.
- Risk per trade: set in the backtester or trader (fraction of equity).

---

## How to run (locally)

- Backtest quickly: `python backtest_cli.py` — uses cached data when available.
- Run live (paper): configure API keys and run `python delta_trader.py`.
- Run unit tests: `pytest -q` (ensure test environment and API keys not set for live tests).

---

## Where to look next (code pointers)

- Signal logic: [trend_rider_engine.py](trend_rider_engine.py#L1)
- Backtest utilities: [crypto_trend_backtest.py](crypto_trend_backtest.py#L1)
- Live order placement: [delta_trader.py](delta_trader.py#L1)
- CLI entrypoint: [backtest_cli.py](backtest_cli.py#L1)

---

If you'd like, I can:

- extract the exact parameter values from the code and show the numeric defaults, or
- create a one-page `README.md` with run examples and typical config, or
- generate a small diagram (`.svg`) showing the runtime flow.

Tell me which of the three you'd like next.

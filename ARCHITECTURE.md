# Architecture — Gold Hedge-Grid (XAUTUSD + PAXGUSD)

## Simple explanation (plain language)

This is a two-leg gold strategy for Delta Exchange. A **SuperTrend(10, 3)** indicator on
**XAUTUSD 4H** candles is the only thing that decides direction: when it flips bullish the
bot goes long gold, when it flips bearish it goes short. On top of that main position it
runs a **hedge grid** on the correlated **PAXGUSD**: every 1% the trade moves in its favour
it opens one counter-lot (up to 5), and each 1% pullback buys the top lot back for a small
profit. The main position rides the trend behind a trailing SuperTrend stop and takes profit
at ±10%; a flip against the position, or the take-profit, flattens everything.

In short: SuperTrend flip picks the side → ride it behind a trailing stop → scalp the
retracements with a counter-hedge grid on PAXG → flatten on the opposite flip or ±10%.

---

## Components

- **Strategy engine**: `gold_hedge_engine.py` — SuperTrend/ATR indicators, the
  `GoldHedgeStrategy` decision core (`step()`), the backtest driver (`run_backtest`), and
  performance `get_metrics`.
- **Backtester**: `gold_hedge_backtest.py` — fetches XAUT (Delta) + PAXG (Delta, Binance
  fallback), replays history through the engine, and writes `gold_hedge_backtest_results.md`.
- **Live trader**: `delta_trader.py` — `DeltaClient` (signed REST wrapper) plus
  `GoldHedgeTrader`, which polls prices, calls the same `GoldHedgeStrategy.step()`, and
  translates the returned actions into Delta orders.
- **Notifications / control**: `telegram_notifier.py` — startup/execution/exit messages and
  remote commands.
- **State & logs**: `trader_state.json` (persisted position + grid), `cache/orders.log`
  (real-order audit trail, rotates at 1 MB).

### Shared decision core

The single most important design point: **backtest and live share one code path.**
`GoldHedgeStrategy.step(xaut_price, pax_price, st_dir, flip_bull, flip_bear)` returns a list
of `Action`s (`open_main`, `close_main`, `open_hedge`, `close_hedge`). The backtest calls it
on each 4H close; the live trader calls it on each poll's mark price. Because the logic lives
in one place, the two can only ever differ in *how often* they sample price, never in *what*
they decide.

Diagram (logical):

```
Price (XAUT 4H + PAXG) --> GoldHedgeStrategy.step() --> [Actions] --> Backtest ledger OR Delta orders
```

---

## How the algorithm decides (step-by-step)

1. Compute SuperTrend(10, 3) on XAUTUSD 4H; derive `st_dir` and bull/bear flip flags.
2. **When flat:** a bull flip opens LONG `MAIN_LOTS`; a bear flip opens SHORT.
3. **While in a position:**
   - Take-profit: exit everything at ±`TP_PCT`% from entry.
   - Trailing stop: exit everything when SuperTrend flips against the position.
   - Grid add: each `STEP_PCT`% travelled in-trend opens one hedge lot on PAXG (opposite
     side), up to `HEDGE_MAX_LOTS`.
   - Grid close: a `STEP_PCT`% retrace back through the top lot's level closes that lot in
     profit; travelling out again re-adds it.
4. On a flip against the position the same `step()` call closes the old side and reverses —
   the engine is always-in-market.

---

## Key parameters (all via `.env`)

- SuperTrend: `ST_PERIOD` (10), `ST_MULT` (3.0).
- Instruments: `MAIN_SYMBOL` (XAUTUSD), `HEDGE_SYMBOL` (PAXGUSD), `TIMEFRAME` (4h).
- Sizing/grid: `MAIN_LOTS` (10), `HEDGE_LOTS_PER_STEP` (1), `HEDGE_MAX_LOTS` (5),
  `STEP_PCT` (1.0), `TP_PCT` (10.0), `LEVERAGE` (5).
- Operation: `DRY_RUN` (true), `POLL_INTERVAL_SEC` (60).

Sizing note: on Delta both symbols have `contract_value = 0.001`, so 1 lot = 1 contract and
the backtest's oz-sizing equals the live contract-sizing exactly.

---

## How to run

- Backtest: `python gold_hedge_backtest.py` → regenerates `gold_hedge_backtest_results.md`.
- Live (paper): configure `.env` and run `python delta_trader.py` (defaults to `DRY_RUN=true`).
- Tests: `pytest -q`.

---

## Code pointers

- Decision core: [gold_hedge_engine.py](gold_hedge_engine.py#L137)
- Backtest driver: [gold_hedge_engine.py](gold_hedge_engine.py#L241)
- Report generator: [gold_hedge_backtest.py](gold_hedge_backtest.py#L1)
- Live executor: [delta_trader.py](delta_trader.py#L250)

---

## Caveats

- **Short history.** XAUTUSD lists on Delta from ~April 2026, so the backtest window is only
  a few months — a mechanics check, not a validated statistical edge.
- Backtest decisions use 4H **close** prices (no intrabar fills); live samples the mark price
  each poll, so it is more reactive within a bar, but the decision logic is identical.
- Fees, funding, and slippage are **not** modelled in the backtest.
- Real-money trading is gated behind `DRY_RUN="false"`; paper-run first.

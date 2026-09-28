"""
XAUTUSD SuperTrend + PAXGUSD Hedge-Grid Backtest
=================================================
Thin driver over `gold_hedge_engine` — the single source of truth for the
strategy. This file only fetches data, feeds it to `run_backtest`, and writes
`gold_hedge_backtest_results.md`. All trade logic lives in the engine, so the
live trader (`delta_trader.py`) and this backtest can never diverge.

Strategy (see gold_hedge_engine for the full statement):
  SuperTrend(10,3) on XAUTUSD 4H is the only signal.
  Bull flip -> LONG 10 lots XAUT (trailing SuperTrend stop, +10% TP). Each +1%
  step shorts 1 lot PAXG (max 5); a 1% retrace closes the top lot in profit; a
  re-cross re-adds it. +10% or bear flip flattens everything. Bear flip mirrors.

Sizing: 1 lot = 0.001 oz = 1 Delta contract.  Starting capital = $100.
Decisions on 4H CLOSE prices (deterministic, no intrabar assumptions).

Usage:  python gold_hedge_backtest.py
Writes: gold_hedge_backtest_results.md
"""

import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from gold_hedge_engine import GoldHedgeParams, run_backtest, get_metrics

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------
DELTA_BASE_URL = "https://api.india.delta.exchange"
TIMEFRAME = "1h"
CAPITAL = 100.0
PARAMS = GoldHedgeParams()   # st(10,3), 10 main lots, 5 max hedge, 1% step, 10% TP, 0.001 oz

OUT_MD = Path(__file__).parent / "gold_hedge_backtest_results.md"


# ----------------------------------------------------------------------------
# DATA
# ----------------------------------------------------------------------------
def fetch_delta_ohlcv(symbol: str, resolution: str = "4h") -> pd.DataFrame:
    """Fetch full available history for a Delta Exchange symbol (paginated)."""
    end_ts = int(datetime.now(timezone.utc).timestamp())
    start_ts = int(datetime(2019, 1, 1, tzinfo=timezone.utc).timestamp())
    all_candles, cursor = [], start_ts
    while cursor < end_ts:
        params = {"symbol": symbol, "resolution": resolution, "start": cursor, "end": end_ts}
        resp = requests.get(f"{DELTA_BASE_URL}/v2/history/candles", params=params, timeout=20)
        resp.raise_for_status()
        batch = resp.json().get("result", [])
        if not batch:
            break
        all_candles.extend(batch)
        last_time = max(c["time"] for c in batch)
        if last_time <= cursor:
            break
        cursor = last_time + 1
        time.sleep(0.2)
    if not all_candles:
        raise RuntimeError(f"No candles returned for {symbol}")
    df = pd.DataFrame(all_candles)
    df["ts"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
    df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")
    return df[["open", "high", "low", "close", "volume"]]


def fetch_binance_ohlcv(symbol_ccxt: str, timeframe: str = "4h") -> pd.DataFrame:
    """Optional Binance fallback for PAXG (XAUT is not listed on Binance)."""
    try:
        import ccxt
    except ImportError as e:
        raise RuntimeError("ccxt not installed; cannot use Binance fallback") from e
    ex = ccxt.binance({"enableRateLimit": True})
    since = ex.parse8601("2019-01-01T00:00:00Z")
    rows, limit = [], 1000
    while True:
        batch = ex.fetch_ohlcv(symbol_ccxt, timeframe, since=since, limit=limit)
        if not batch:
            break
        rows.extend(batch)
        since = batch[-1][0] + 1
        if len(batch) < limit:
            break
        time.sleep(ex.rateLimit / 1000)
    if not rows:
        raise RuntimeError(f"No Binance candles for {symbol_ccxt}")
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df.set_index("ts")[["open", "high", "low", "close", "volume"]]


def load_data():
    """Fetch XAUT (Delta only) + PAXG (Delta, Binance fallback). Validate overlap."""
    xaut = fetch_delta_ohlcv(PARAMS.main_symbol, TIMEFRAME)
    try:
        paxg = fetch_delta_ohlcv(PARAMS.hedge_symbol, TIMEFRAME)
        src = "Delta Exchange"
    except Exception as e:
        print(f"  PAXG on Delta failed ({e}); trying Binance PAXG/USDT ...")
        paxg = fetch_binance_ohlcv("PAXG/USDT", TIMEFRAME)
        src = "Delta (XAUT) + Binance (PAXG)"

    overlap_start = max(xaut.index[0], paxg.index[0])
    overlap_end = min(xaut.index[-1], paxg.index[-1])
    overlap = xaut[(xaut.index >= overlap_start) & (xaut.index <= overlap_end)]
    if len(overlap) < PARAMS.st_period + 5:
        raise RuntimeError(
            f"Too little overlapping data: {len(overlap)} bars "
            f"({overlap_start:%Y-%m-%d} -> {overlap_end:%Y-%m-%d})"
        )
    return xaut, paxg["close"], src


# ----------------------------------------------------------------------------
# REPORT
# ----------------------------------------------------------------------------
def _fmt_t(t):
    return t.strftime("%Y-%m-%d %H:%M") if t is not None else "-"


def _sparkline(eq: pd.Series, buckets: int = 40) -> str:
    """Compact unicode equity sparkline."""
    blocks = "▁▂▃▄▅▆▇█"
    if len(eq) < 2:
        return ""
    step = max(1, len(eq) // buckets)
    sampled = eq.iloc[::step]
    lo, hi = sampled.min(), sampled.max()
    rng = (hi - lo) or 1.0
    return "".join(blocks[min(len(blocks) - 1, int((v - lo) / rng * (len(blocks) - 1)))] for v in sampled)


def write_report(signals, main_trades, hedge_trades, eq_df, m, src):
    p = PARAMS
    start, end = signals.index[0], signals.index[-1]
    pf = "inf" if m["profit_factor"] == float("inf") else f"{m['profit_factor']:.2f}"
    L = []
    L.append("# XAUTUSD SuperTrend + PAXGUSD Hedge-Grid — Backtest Results\n")
    L.append(f"_Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}_\n")

    L.append("## Strategy\n")
    L.append(f"SuperTrend({p.st_period}, {p.st_mult:g}) on **{p.main_symbol} {TIMEFRAME.upper()}** is the only signal generator.\n")
    L.append(f"- **Bullish flip** → LONG {p.main_lots} lots {p.main_symbol} (trailing SuperTrend stop). "
             f"Each +{p.step_pct:g}% step shorts {p.hedge_lots_per_step} lot {p.hedge_symbol} "
             f"(grid +{p.step_pct:g}%…+{p.step_pct*p.max_hedge_lots:g}%, max {p.max_hedge_lots}). "
             f"A {p.step_pct:g}% retrace closes the top {p.hedge_symbol} lot in profit; a re-cross re-adds it. "
             f"+{p.tp_pct:g}% on {p.main_symbol} closes everything.\n")
    L.append(f"- **Bearish flip** → mirror: SHORT {p.main_symbol}, LONG {p.hedge_symbol} on each −{p.step_pct:g}% step.\n")
    L.append("- Exits also trigger on SuperTrend flip against the position, which closes all hedges.\n")

    L.append("## Setup\n")
    L.append("| Parameter | Value |")
    L.append("|---|---|")
    L.append(f"| Signal / data source | {src}, {TIMEFRAME.upper()} candles |")
    L.append(f"| Main / hedge symbols | {p.main_symbol} / {p.hedge_symbol} |")
    L.append(f"| SuperTrend | period {p.st_period}, multiplier {p.st_mult:g} |")
    L.append(f"| Starting capital | ${CAPITAL:,.2f} |")
    L.append(f"| Lot size | {p.contract_oz} oz ({p.main_symbol}: {p.main_lots} lots = {p.main_qty:g} oz; {p.hedge_symbol}: {p.hedge_qty:g} oz/lot) |")
    L.append(f"| Grid step / max lots / TP | {p.step_pct:g}% / {p.max_hedge_lots} / {p.tp_pct:g}% |")
    L.append(f"| Backtest window | {start:%Y-%m-%d} → {end:%Y-%m-%d} ({len(signals)} bars) |")
    L.append(f"| Decision basis | {TIMEFRAME.upper()} close prices |\n")

    L.append("## Headline Results\n")
    L.append("| Metric | Value |")
    L.append("|---|---|")
    L.append(f"| **Final equity** | ${m['final_equity']:,.2f} |")
    L.append(f"| **Total return** | {m['return_pct']:+.2f}% |")
    L.append(f"| Net P&L | ${m['net']:+,.4f} |")
    L.append(f"| — {p.main_symbol} (main) P&L | ${m['main_pnl']:+,.4f} |")
    L.append(f"| — {p.hedge_symbol} (hedge) P&L | ${m['hedge_pnl']:+,.4f} |")
    L.append(f"| Total trades | {m['n_trades']} ({m['n_main']} main / {m['n_hedge']} hedge) |")
    L.append(f"| Win rate | {m['win_rate']:.1f}% |")
    L.append(f"| Profit factor | {pf} |")
    L.append(f"| Sharpe / Sortino (ann.) | {m['sharpe']:.2f} / {m['sortino']:.2f} |")
    L.append(f"| Max drawdown | {m['max_drawdown']:.2f}% |")
    L.append(f"| Largest win / loss | ${m['largest_win']:+,.4f} / ${m['largest_loss']:+,.4f} |\n")

    L.append("## Equity Curve\n")
    L.append(f"`{_sparkline(eq_df['equity'])}`  ${CAPITAL:,.2f} → ${m['final_equity']:,.2f}\n")

    if m["monthly"]:
        L.append("## Monthly Returns\n")
        L.append("| Month | Return |")
        L.append("|---|--:|")
        for month, ret in m["monthly"]:
            L.append(f"| {month} | {ret:+.2f}% |")
        L.append("")

    L.append("## Main (XAUTUSD) Trades\n")
    if main_trades:
        L.append("| # | Dir | Entry | Entry $ | Exit | Exit $ | P&L $ | Reason |")
        L.append("|--:|:--|:--|--:|:--|--:|--:|:--|")
        for i, t in enumerate(main_trades, 1):
            L.append(f"| {i} | {t['dir']} | {_fmt_t(t['entry_time'])} | {t['entry_price']:,.2f} | "
                     f"{_fmt_t(t['exit_time'])} | {t['exit_price']:,.2f} | {t['pnl']:+.4f} | {t['reason']} |")
    else:
        L.append("_No main trades._")
    L.append("")

    L.append("## Hedge (PAXGUSD) Trades\n")
    if hedge_trades:
        L.append("| # | Side | Step | Entry | Entry $ | Exit | Exit $ | P&L $ | Reason |")
        L.append("|--:|:--|--:|:--|--:|:--|--:|--:|:--|")
        for i, h in enumerate(hedge_trades, 1):
            L.append(f"| {i} | {h['side']} | {h['step']} | {_fmt_t(h['entry_time'])} | {h['pax_entry']:,.2f} | "
                     f"{_fmt_t(h['exit_time'])} | {h['pax_exit']:,.2f} | {h['pnl']:+.4f} | {h['reason']} |")
    else:
        L.append("_No hedge trades._")
    L.append("")

    L.append("## Notes & Caveats\n")
    L.append(f"- **Short history.** {p.main_symbol} on Delta only lists from ~2026-04, so the "
             "overlapping window with PAXG is a few months — too short for statistically robust "
             "conclusions. Treat this as a mechanics check, not an edge validation.\n")
    L.append(f"- All decisions use {TIMEFRAME.upper()} **close** prices (no intrabar fills), so the "
             f"{p.tp_pct:g}% TP and {p.step_pct:g}% grid levels are recognised at the first close beyond the level.\n")
    L.append(f"- P&L is tiny in absolute terms because {p.main_lots} lots = {p.main_qty:g} oz "
             f"(~$40 notional) against ${CAPITAL:.0f} capital — by design, this keeps the account "
             "survivable. Scale `main_lots`/`contract_oz` in `GoldHedgeParams` to change notional.\n")
    L.append("- Fees, funding, and slippage are **not** modelled.\n")

    OUT_MD.write_text("\n".join(L), encoding="utf-8")


def main():
    print(f"Fetching {PARAMS.main_symbol} + {PARAMS.hedge_symbol} {TIMEFRAME} ...")
    xaut, pax_close, src = load_data()
    signals, main_trades, hedge_trades, eq_df, realized = run_backtest(xaut, pax_close, PARAMS, CAPITAL)
    m = get_metrics(main_trades, hedge_trades, eq_df, CAPITAL)
    write_report(signals, main_trades, hedge_trades, eq_df, m, src)

    print(f"\nData source : {src}")
    print(f"Window      : {signals.index[0]:%Y-%m-%d} -> {signals.index[-1]:%Y-%m-%d} ({len(signals)} bars)")
    print(f"Final equity: ${m['final_equity']:.2f}  ({m['return_pct']:+.2f}%)")
    print(f"Net P&L     : ${m['net']:+.4f}  (main ${m['main_pnl']:+.4f} / hedge ${m['hedge_pnl']:+.4f})")
    print(f"Trades      : {m['n_trades']} ({m['n_main']} main / {m['n_hedge']} hedge)")
    print(f"Win rate    : {m['win_rate']:.1f}%   PF: {m['profit_factor']}")
    print(f"Sharpe/Sort : {m['sharpe']:.2f} / {m['sortino']:.2f}   Max DD: {m['max_drawdown']:.2f}%")
    print(f"\nReport written to: {OUT_MD}")


if __name__ == "__main__":
    main()

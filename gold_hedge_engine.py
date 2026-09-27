"""
Gold Hedge Engine — XAUTUSD SuperTrend + PAXGUSD Hedge Grid
============================================================
The project's single strategy engine. SuperTrend(10,3) on XAUTUSD drives one
main directional position; a grid of counter-hedges on the correlated PAXGUSD
is layered on top to scalp the intra-trend retracements.

PHILOSOPHY
- SuperTrend flip = the only entry/exit signal on the main leg (XAUTUSD).
- Main stop = the trailing SuperTrend line itself (exit on the opposite flip).
- +/-10% on the main leg = hard take-profit that flattens everything.
- Each 1% the main leg travels in-trend opens 1 counter-lot on PAXGUSD
  (max 5); a 1% retrace buys the top lot back for a small profit; a re-cross
  re-adds it. Both instruments are gold-backed and ~1:1 correlated.

DESIGN
- `GoldHedgeStrategy.step()` is the single decision core. The backtest driver
  (`run_backtest`) and the live trader both call it, so their logic can never
  diverge — they differ only in how often price is sampled (backtest = 4H
  close, live = mark price each poll).
- On Delta both XAUTUSD and PAXGUSD have contract_value = 0.001, so 1 lot =
  1 contract; backtest oz-sizing and live contract-sizing are identical.
"""

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

# ============================================================================
# INDICATORS
# ============================================================================

def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = true_range(df)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def supertrend_full(df: pd.DataFrame, period: int = 10, mult: float = 3.0):
    """Return (direction, value) SuperTrend series. direction: +1 bull, -1 bear."""
    atr_ = atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2
    upper = hl2 + mult * atr_
    lower = hl2 - mult * atr_

    final_upper = upper.copy()
    final_lower = lower.copy()
    direction = pd.Series(1, index=df.index)
    value = pd.Series(np.nan, index=df.index)

    for i in range(1, len(df)):
        final_upper.iat[i] = (
            upper.iat[i] if (upper.iat[i] < final_upper.iat[i - 1] or df["close"].iat[i - 1] > final_upper.iat[i - 1])
            else final_upper.iat[i - 1]
        )
        final_lower.iat[i] = (
            lower.iat[i] if (lower.iat[i] > final_lower.iat[i - 1] or df["close"].iat[i - 1] < final_lower.iat[i - 1])
            else final_lower.iat[i - 1]
        )
        if df["close"].iat[i] > final_upper.iat[i - 1]:
            direction.iat[i] = 1
        elif df["close"].iat[i] < final_lower.iat[i - 1]:
            direction.iat[i] = -1
        else:
            direction.iat[i] = direction.iat[i - 1]
        value.iat[i] = final_lower.iat[i] if direction.iat[i] == 1 else final_upper.iat[i]

    return direction, value


# ============================================================================
# PARAMETERS
# ============================================================================

@dataclass
class GoldHedgeParams:
    st_period: int = 10
    st_mult: float = 3.0
    main_lots: int = 10             # XAUT position size, in lots (= contracts)
    hedge_lots_per_step: int = 1    # PAXG lots added per grid step
    max_hedge_lots: int = 5         # cap on simultaneously open PAXG lots
    step_pct: float = 1.0           # grid step, percent of entry
    tp_pct: float = 10.0            # take-profit on the main leg, percent
    contract_oz: float = 0.001      # 1 lot = 0.001 oz (Delta contract_value)
    main_symbol: str = "XAUTUSD"
    hedge_symbol: str = "PAXGUSD"

    @property
    def main_qty(self) -> float:
        return self.main_lots * self.contract_oz

    @property
    def hedge_qty(self) -> float:
        return self.hedge_lots_per_step * self.contract_oz


# ============================================================================
# ACTIONS emitted by the decision core
# ============================================================================

@dataclass
class Action:
    kind: str                       # open_main | close_main | open_hedge | close_hedge
    direction: Optional[str] = None # main leg direction (long/short)
    side: Optional[str] = None      # hedge leg side (short hedges a long, long hedges a short)
    price: Optional[float] = None   # XAUT execution price (main actions)
    pax_price: Optional[float] = None  # PAXG execution price (hedge actions)
    step: Optional[int] = None      # grid step index (hedge actions)
    hedge_entry: Optional[float] = None  # PAXG entry price of the lot being closed
    reason: str = ""


def compute_signals(xaut_df: pd.DataFrame, p: GoldHedgeParams) -> pd.DataFrame:
    """Attach SuperTrend direction/value and flip flags to XAUT OHLCV."""
    d = xaut_df.copy()
    st_dir, st_val = supertrend_full(d, p.st_period, p.st_mult)
    d["st_dir"] = st_dir
    d["st_val"] = st_val
    d["flip_bull"] = (d["st_dir"] == 1) & (d["st_dir"].shift(1) == -1)
    d["flip_bear"] = (d["st_dir"] == -1) & (d["st_dir"].shift(1) == 1)
    return d


# ============================================================================
# DECISION CORE — shared by backtest and live
# ============================================================================

class GoldHedgeStrategy:
    """Stateful hedge-grid decision core.

    Feed it one price observation at a time via `step()`; it returns the list
    of Actions to execute (open/close main, open/close hedge). It holds no
    money — it only decides. The caller (backtest or live) owns execution and
    P&L. Backtest calls it on each 4H close; live calls it on each poll's mark
    price. Same code path, so the two can never disagree.
    """

    def __init__(self, p: GoldHedgeParams):
        self.p = p
        self.reset()

    def reset(self):
        self.pos: Optional[str] = None      # None | "long" | "short"
        self.entry_price: Optional[float] = None
        self.hedges: list = []              # stack of {"step": int, "pax_entry": float}
        self.top: int = 0                   # highest open grid step

    # -- price helpers --------------------------------------------------------
    def _tp_level(self) -> float:
        tp = self.p.tp_pct / 100.0
        return self.entry_price * (1 + tp) if self.pos == "long" else self.entry_price * (1 - tp)

    def _grid_open_level(self, k: int) -> float:
        s = self.p.step_pct / 100.0
        return self.entry_price * (1 + s * k) if self.pos == "long" else self.entry_price * (1 - s * k)

    # -- the single decision function -----------------------------------------
    def step(self, xaut_price: float, pax_price: float, st_dir: int,
             flip_bull: bool, flip_bear: bool) -> list:
        p = self.p
        actions: list = []

        # ---- Manage an open position ----
        if self.pos is not None:
            direction = self.pos
            main_exit = None
            if direction == "long":
                if xaut_price >= self._tp_level():
                    main_exit = "take_profit"
                elif st_dir == -1:
                    main_exit = "supertrend_stop"
            else:
                if xaut_price <= self._tp_level():
                    main_exit = "take_profit"
                elif st_dir == 1:
                    main_exit = "supertrend_stop"

            if main_exit is not None:
                # Flatten hedges (top-down) then the main leg.
                side = "short" if direction == "long" else "long"
                while self.hedges:
                    h = self.hedges.pop()
                    actions.append(Action("close_hedge", side=side, step=h["step"],
                                          pax_price=pax_price, hedge_entry=h["pax_entry"],
                                          reason=main_exit))
                actions.append(Action("close_main", direction=direction,
                                      price=xaut_price, reason=main_exit))
                self.reset()
                # fall through: a SuperTrend flip may re-enter the opposite way
                # on this same observation (the engine is always-in-market).
            else:
                side = "short" if direction == "long" else "long"
                # Add lots as the trend extends.
                while self.top < p.max_hedge_lots and _extended(direction, xaut_price, self._grid_open_level(self.top + 1)):
                    self.top += 1
                    self.hedges.append({"step": self.top, "pax_entry": pax_price})
                    actions.append(Action("open_hedge", side=side, step=self.top, pax_price=pax_price))
                # Close the top lot on a 1% retrace back through its level.
                while self.hedges and _retraced(direction, xaut_price, self._grid_open_level(self.hedges[-1]["step"] - 1)):
                    h = self.hedges.pop()
                    actions.append(Action("close_hedge", side=side, step=h["step"],
                                          pax_price=pax_price, hedge_entry=h["pax_entry"],
                                          reason="retrace_1pct"))
                    self.top = self.hedges[-1]["step"] if self.hedges else 0

        # ---- Enter on a SuperTrend flip when flat ----
        if self.pos is None:
            if flip_bull:
                self.pos, self.entry_price, self.top, self.hedges = "long", xaut_price, 0, []
                actions.append(Action("open_main", direction="long", price=xaut_price, reason="flip_bull"))
            elif flip_bear:
                self.pos, self.entry_price, self.top, self.hedges = "short", xaut_price, 0, []
                actions.append(Action("open_main", direction="short", price=xaut_price, reason="flip_bear"))

        return actions


def _extended(direction: str, price: float, level: float) -> bool:
    """True when price has travelled far enough in-trend to add the next lot."""
    return price >= level if direction == "long" else price <= level


def _retraced(direction: str, price: float, level: float) -> bool:
    """True when price has retraced back through the top lot's close level."""
    return price <= level if direction == "long" else price >= level


# ============================================================================
# BACKTEST DRIVER — replays history through the decision core
# ============================================================================

def run_backtest(xaut_df: pd.DataFrame, pax_series: pd.Series,
                 p: GoldHedgeParams, capital: float = 100.0):
    """Drive the state machine over aligned XAUT bars + PAXG closes.

    xaut_df   : OHLCV indexed by 4H timestamp (SuperTrend computed here).
    pax_series: PAXG close indexed on the same grid (already ffilled/aligned).
    Returns (signals_df, main_trades, hedge_trades, equity_df, realized).
    """
    d = compute_signals(xaut_df, p)
    d = d.copy()
    d["pax"] = pax_series.reindex(d.index).ffill()
    d = d.dropna(subset=["st_dir", "st_val", "pax"])

    strat = GoldHedgeStrategy(p)
    realized = 0.0
    equity_curve = []          # (time, mtm_equity)
    main_trades, hedge_trades = [], []

    cur_main = None            # {"dir","entry_time","entry_price"}
    cur_hedges = {}            # step -> {"entry_time","pax_entry","side"}

    def main_pnl(direction, entry, exit_):
        return p.main_qty * (exit_ - entry) if direction == "long" else p.main_qty * (entry - exit_)

    def hedge_pnl(side, entry, exit_):
        # short hedge profits when PAXG falls; long hedge profits when it rises
        return p.hedge_qty * (entry - exit_) if side == "short" else p.hedge_qty * (exit_ - entry)

    for t, row in d.iterrows():
        price, pax = row["close"], row["pax"]
        for a in strat.step(price, pax, int(row["st_dir"]), bool(row["flip_bull"]), bool(row["flip_bear"])):
            if a.kind == "open_main":
                cur_main = {"dir": a.direction, "entry_time": t, "entry_price": a.price}
            elif a.kind == "close_main":
                pnl = main_pnl(cur_main["dir"], cur_main["entry_price"], a.price)
                realized += pnl
                main_trades.append({**cur_main, "exit_time": t, "exit_price": a.price,
                                    "pnl": pnl, "reason": a.reason})
                cur_main = None
            elif a.kind == "open_hedge":
                cur_hedges[a.step] = {"entry_time": t, "pax_entry": a.pax_price, "side": a.side}
            elif a.kind == "close_hedge":
                h = cur_hedges.pop(a.step, {"entry_time": t, "pax_entry": a.hedge_entry, "side": a.side})
                pnl = hedge_pnl(a.side, h["pax_entry"], a.pax_price)
                realized += pnl
                hedge_trades.append({"side": a.side, "step": a.step, "entry_time": h["entry_time"],
                                     "pax_entry": h["pax_entry"], "exit_time": t, "pax_exit": a.pax_price,
                                     "pnl": pnl, "reason": a.reason})

        # ---- mark-to-market ----
        eq = capital + realized
        if cur_main is not None:
            eq += main_pnl(cur_main["dir"], cur_main["entry_price"], price)
            for h in cur_hedges.values():
                eq += hedge_pnl(h["side"], h["pax_entry"], pax)
        equity_curve.append((t, eq))

    # ---- close anything still open at end of data ----
    if cur_main is not None:
        last_t, price, pax = d.index[-1], d["close"].iloc[-1], d["pax"].iloc[-1]
        for step, h in sorted(cur_hedges.items(), reverse=True):
            pnl = hedge_pnl(h["side"], h["pax_entry"], pax)
            realized += pnl
            hedge_trades.append({"side": h["side"], "step": step, "entry_time": h["entry_time"],
                                 "pax_entry": h["pax_entry"], "exit_time": last_t, "pax_exit": pax,
                                 "pnl": pnl, "reason": "end_of_data"})
        cur_hedges.clear()
        pnl = main_pnl(cur_main["dir"], cur_main["entry_price"], price)
        realized += pnl
        main_trades.append({**cur_main, "exit_time": last_t, "exit_price": price,
                            "pnl": pnl, "reason": "end_of_data"})

    eq_df = pd.DataFrame(equity_curve, columns=["time", "equity"]).set_index("time")
    return d, main_trades, hedge_trades, eq_df, realized


# ============================================================================
# METRICS
# ============================================================================

def get_metrics(main_trades, hedge_trades, eq_df, capital: float = 100.0,
                periods_per_year: int = 6 * 365):
    """Performance summary. `periods_per_year` = 4H bars/yr for Sharpe/Sortino."""
    all_pnls = [t["pnl"] for t in main_trades] + [h["pnl"] for h in hedge_trades]
    main_pnl = sum(t["pnl"] for t in main_trades)
    hedge_pnl_total = sum(h["pnl"] for h in hedge_trades)
    net = main_pnl + hedge_pnl_total

    wins = [x for x in all_pnls if x > 0]
    losses = [x for x in all_pnls if x <= 0]
    n = len(all_pnls)
    win_rate = (len(wins) / n * 100) if n else 0.0
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float("inf")

    eq = eq_df["equity"]
    running_max = eq.cummax()
    dd = (eq - running_max) / running_max
    max_dd = float(dd.min() * 100) if len(eq) else 0.0
    final_eq = float(eq.iloc[-1]) if len(eq) else capital

    # bar-to-bar returns for risk-adjusted ratios
    rets = eq.pct_change().dropna()
    sharpe = sortino = 0.0
    if len(rets) > 1 and rets.std() > 0:
        sharpe = float(rets.mean() / rets.std() * np.sqrt(periods_per_year))
    downside = rets[rets < 0]
    if len(downside) > 1 and downside.std() > 0:
        sortino = float(rets.mean() / downside.std() * np.sqrt(periods_per_year))

    # monthly returns (month-end equity, pct change; first month vs capital)
    monthly = []
    if len(eq):
        me = eq.resample("ME").last().dropna()
        prev = capital
        for ts, val in me.items():
            monthly.append((ts.strftime("%Y-%m"), (val - prev) / prev * 100))
            prev = val

    return {
        "net": net, "main_pnl": main_pnl, "hedge_pnl": hedge_pnl_total,
        "final_equity": final_eq, "return_pct": (final_eq - capital) / capital * 100,
        "n_trades": n, "n_main": len(main_trades), "n_hedge": len(hedge_trades),
        "win_rate": win_rate, "profit_factor": pf, "max_drawdown": max_dd,
        "sharpe": sharpe, "sortino": sortino,
        "largest_win": max(all_pnls) if all_pnls else 0.0,
        "largest_loss": min(all_pnls) if all_pnls else 0.0,
        "monthly": monthly,
    }

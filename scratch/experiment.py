"""Multi-year experiment harness for Trend Rider tuning.
Fetches once, caches in memory, runs param variants, prints aggregate metrics.
Run:  python scratch/experiment.py
"""
import sys, os, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from trend_rider_engine import TrendRiderParams, run_trend_rider_backtest, get_metrics
from backtest_cli import fetch_year_data, fetch_ltf_year_data, SYMBOL

YEARS = [2019, 2020, 2021, 2022, 2023, 2024]

# Fetch & cache data once
_DATA = {}
def load(yr):
    if yr not in _DATA:
        df4h = fetch_year_data(yr)
        dfltf = fetch_ltf_year_data(yr, "1h")
        _DATA[yr] = (df4h, dfltf)
    return _DATA[yr]

def run_variant(label, **overrides):
    """Run all years with param overrides; return aggregate + per-year rows."""
    rows = []
    all_r = []
    tot_ret_mult = 1.0
    for yr in YEARS:
        df4h, dfltf = load(yr)
        kwargs = {"ltf_enabled": dfltf is not None, "ltf_confirm_mode": "majority"}
        kwargs.update(overrides)
        p = TrendRiderParams(**kwargs)
        trades, eq = run_trend_rider_backtest(df4h, p, 10000.0, dfltf)
        m = get_metrics(trades, eq, 10000.0)
        rows.append((yr, m))
        all_r += [t.r_multiple for t in trades if t.r_multiple is not None]
        tot_ret_mult *= (1 + m["total_return_pct"] / 100.0)

    n = len(all_r)
    wins = [r for r in all_r if r > 0]
    win_rate = len(wins) / n * 100 if n else 0
    expectancy = float(np.mean(all_r)) if all_r else 0
    compounded = (tot_ret_mult - 1) * 100
    avg_dd = np.mean([m["max_drawdown"] for _, m in rows])

    print(f"\n=== {label} ===")
    for yr, m in rows:
        print(f"  {yr} ret {m['total_return_pct']:+7.1f}% | WR {m['win_rate']:4.1f}% | PF {m['profit_factor']:5.2f} | DD {m['max_drawdown']:+6.1f}% | n={m['total_trades']}")
    print(f"  AGGREGATE: WR {win_rate:.1f}% | expectancy {expectancy:+.3f}R | compounded {compounded:+.1f}% | avgDD {avg_dd:+.1f}% | trades {n}")
    return {"label": label, "win_rate": win_rate, "expectancy": expectancy,
            "compounded": compounded, "avg_dd": avg_dd, "trades": n}


if __name__ == "__main__":
    results = []
    results.append(run_variant("BASELINE (current)"))
    results.append(run_variant("LTF strict 4/4", ltf_confirm_mode="strict"))
    results.append(run_variant("No fresh_trend entry", disable_fresh_trend=True))
    results.append(run_variant("No breakout entry", disable_breakout=True))
    results.append(run_variant("RSI filter tighter", rsi_ob=70.0, rsi_os=30.0))
    results.append(run_variant("Longs only", longs_only=True))
    results.append(run_variant("RSI70/30 + no breakout", rsi_ob=70.0, rsi_os=30.0, disable_breakout=True))
    results.append(run_variant("RSI65/35", rsi_ob=65.0, rsi_os=35.0))
    results.append(run_variant("RSI70/30 + no breakout + no fresh", rsi_ob=70.0, rsi_os=30.0, disable_breakout=True, disable_fresh_trend=True))
    results.append(run_variant("pullback-only + RSI70/30", disable_breakout=True, disable_fresh_trend=True, rsi_ob=70.0, rsi_os=30.0))
    results.append(run_variant("RSI70/30 longs-only", rsi_ob=70.0, rsi_os=30.0, longs_only=True))
    print("\n" + "="*70)
    print(f"{'VARIANT':<32} {'WR%':>6} {'Exp(R)':>8} {'Comp%':>8} {'DD%':>7} {'N':>5}")
    for r in results:
        print(f"{r['label']:<32} {r['win_rate']:>6.1f} {r['expectancy']:>+8.3f} {r['compounded']:>+8.1f} {r['avg_dd']:>+7.1f} {r['trades']:>5}")

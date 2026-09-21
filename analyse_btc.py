"""
analyse_btc.py
==============
Analyse historical BTC daily "sessions" that run from 6:30 PM to the next day 5:30 PM.

For each session we:
  1. Mark the price at 6:30 PM (session open).
  2. Look at the whole session (6:30 PM -> next 5:30 PM, 23 hours).
  3. Check how far price travelled ABOVE and BELOW that mark price.
  4. Count how many sessions broke the ABOVE band, the BELOW band, and how many
     stayed inside both bands (i.e. "ranging" the whole session).
  5. Report movement stats in points and percentage: average / worst / least.

The ABOVE band and BELOW band are asked for separately at runtime.

Times default to IST (Asia/Kolkata). 6:30 PM IST == 13:00 UTC and 5:30 PM IST
== 12:00 UTC, so the session lines up cleanly with hourly candles.

Usage:
    python analyse_btc.py                 # interactive: asks for year + bands
    python analyse_btc.py 2026            # year given, still asks for bands
    python analyse_btc.py 2023 --up 600 --down 800 --symbol BTC/USDT
    python analyse_btc.py --all --up 600 --down 600     # sweep 2021..current
"""

import argparse
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from crypto_trend_backtest import fetch_ohlcv

# ---------------------------------------------------------------------------
# Session definition (IST). 18:30 IST == 13:00 UTC, 17:30 IST(+1d) == 12:00 UTC
# ---------------------------------------------------------------------------
SESSION_START_HOUR_UTC = 13   # 18:30 IST
SESSION_LEN_HOURS = 23        # 18:30 today -> 17:30 tomorrow


# ---------------------------------------------------------------------------
# Colors (ANSI). Auto-enabled on Windows terminals.
# ---------------------------------------------------------------------------
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GREY = "\033[90m"


def _enable_ansi():
    """Turn on ANSI escape processing on Windows; no-op elsewhere."""
    # make sure we can print unicode bars regardless of the console codepage
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            # if we can't enable colors, strip them so output stays readable
            for attr in dir(C):
                if not attr.startswith("_") and attr.isupper():
                    setattr(C, attr, "")


def paint(text, color):
    return f"{color}{text}{C.RESET}"


def build_sessions(df1h: pd.DataFrame, up_band: float, down_band: float) -> pd.DataFrame:
    """Group hourly candles into 6:30PM->5:30PM sessions and compute per-session stats."""
    if df1h.empty:
        return pd.DataFrame()

    df = df1h.copy()
    # A session "belongs" to the day it started on. Anything at/after 13:00 UTC
    # starts today's session; anything before 13:00 UTC belongs to yesterday's.
    hours = df.index.hour
    session_date = df.index.normalize()
    # shift candles before 13:00 UTC back one day so they join the prior session
    session_date = session_date.where(hours >= SESSION_START_HOUR_UTC,
                                      session_date - pd.Timedelta(days=1))
    df = df.assign(session=session_date)

    rows = []
    for sess_day, g in df.groupby("session"):
        g = g.sort_index()
        # first candle of the session must be the 13:00 UTC (6:30 PM IST) candle
        first = g.iloc[0]
        if g.index[0].hour != SESSION_START_HOUR_UTC:
            continue  # incomplete / misaligned session, skip
        # only keep candles within the 23h window
        end_ts = g.index[0] + pd.Timedelta(hours=SESSION_LEN_HOURS)
        g = g[g.index < end_ts]
        if len(g) < 12:
            continue  # too little data to be meaningful, skip

        mark = float(first["open"])
        hi = float(g["high"].max())
        lo = float(g["low"].min())
        close = float(g.iloc[-1]["close"])

        up_move = hi - mark          # max points above mark
        dn_move = mark - lo          # max points below mark
        range_pts = hi - lo          # full range of the session
        net_move = close - mark      # directional close-vs-mark

        rows.append({
            "session_date": sess_day.date(),
            "mark": mark,
            "high": hi,
            "low": lo,
            "close": close,
            "up_pts": up_move,
            "dn_pts": dn_move,
            "range_pts": range_pts,
            "net_pts": net_move,
            "up_pct": up_move / mark * 100,
            "dn_pct": dn_move / mark * 100,
            "range_pct": range_pts / mark * 100,
            "net_pct": net_move / mark * 100,
            "broke_up": up_move >= up_band,
            "broke_dn": dn_move >= down_band,
        })

    return pd.DataFrame(rows)


def _bar(pct, width=24):
    """A little colored percentage bar."""
    filled = int(round(pct / 100 * width))
    filled = max(0, min(width, filled))
    return "█" * filled + paint("░" * (width - filled), C.GREY)


def summarise(sessions: pd.DataFrame, up_band: float, down_band: float, year: int) -> None:
    if sessions.empty:
        print(paint(f"\n=== {year} ===  no data", C.YELLOW))
        return

    n = len(sessions)
    broke_up = int(sessions["broke_up"].sum())
    broke_dn = int(sessions["broke_dn"].sum())
    broke_both = int((sessions["broke_up"] & sessions["broke_dn"]).sum())
    stayed_in = int((~sessions["broke_up"] & ~sessions["broke_dn"]).sum())

    bar_c = paint("=" * 64, C.CYAN)
    print(f"\n{bar_c}")
    print(paint(f"  BTC SESSION ANALYSIS  {year}   (6:30 PM -> next 5:30 PM IST)", C.BOLD + C.WHITE))
    print(paint(f"  bands: ABOVE +{up_band:.0f} pts   |   BELOW -{down_band:.0f} pts", C.DIM + C.WHITE))
    print(bar_c)

    print(f"  {'Sessions analysed':<28}: {paint(f'{n:4d}', C.BOLD + C.WHITE)}")

    def count_line(label, cnt, color):
        pct = cnt / n * 100
        print(f"  {label:<28}: {paint(f'{cnt:4d}', color)}  "
              f"({paint(f'{pct:5.1f}%', color)})  {_bar(pct)}")

    count_line(f"Broke +{up_band:.0f} ABOVE mark", broke_up, C.GREEN)
    count_line(f"Broke -{down_band:.0f} BELOW mark", broke_dn, C.RED)
    count_line("Broke BOTH sides", broke_both, C.MAGENTA)
    count_line("Stayed INSIDE (ranged)", stayed_in, C.YELLOW)

    # --- movement stats (based on full session range) ---
    rng_pct = sessions["range_pct"]
    rng_pts = sessions["range_pts"]

    def stat_line(label, pts, pct, color):
        print(f"    {paint(f'{label:<18}', color)}: "
              f"{paint(f'{pts:8.0f} pts', C.WHITE)}   {paint(f'{pct:6.2f}%', color)}")

    print(paint("\n  --- Session movement (full high-low range) ---", C.BOLD + C.CYAN))
    stat_line("Average move", rng_pts.mean(), rng_pct.mean(), C.WHITE)
    stat_line("Worst / max move", rng_pts.max(), rng_pct.max(), C.RED)
    stat_line("Least / min move", rng_pts.min(), rng_pct.min(), C.GREEN)
    stat_line("Median move", rng_pts.median(), rng_pct.median(), C.WHITE)

    print(paint("\n  --- Directional (max points above / below mark) ---", C.BOLD + C.CYAN))
    stat_line("Avg up-move", sessions["up_pts"].mean(), sessions["up_pct"].mean(), C.GREEN)
    stat_line("Avg down-move", sessions["dn_pts"].mean(), sessions["dn_pct"].mean(), C.RED)
    stat_line("Max up-move", sessions["up_pts"].max(), sessions["up_pct"].max(), C.GREEN)
    stat_line("Max down-move", sessions["dn_pts"].max(), sessions["dn_pct"].max(), C.RED)

    # biggest single session
    worst_idx = rng_pct.idxmax()
    w = sessions.loc[worst_idx]
    print(paint(f"\n  Biggest range day: ", C.BOLD + C.YELLOW)
          + paint(f"{w['session_date']}  {w['range_pts']:.0f} pts "
                  f"({w['range_pct']:.2f}%)  mark={w['mark']:.0f}", C.WHITE))


def analyse_year(exchange: str, symbol: str, year: int, up_band: float, down_band: float) -> None:
    now = datetime.now(timezone.utc)
    start = f"{year}-01-01"
    # extend a little past year end so late-Dec sessions that spill into Jan close cleanly
    end_dt = now if year >= now.year else datetime(year + 1, 1, 2, tzinfo=timezone.utc)
    since_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    until_ms = int(end_dt.timestamp() * 1000)

    print(paint(f"Fetching 1H {symbol} from {exchange} for {year} ...", C.DIM + C.CYAN))
    df1h = fetch_ohlcv(exchange, symbol, "1h", since_ms, until_ms)
    if df1h.empty:
        print(paint(f"  no candles returned for {year}", C.YELLOW))
        return

    # keep only sessions that started within the requested year
    sessions = build_sessions(df1h, up_band, down_band)
    if not sessions.empty:
        sessions = sessions[sessions["session_date"].apply(lambda d: d.year) == year].reset_index(drop=True)
    summarise(sessions, up_band, down_band, year)


def _ask_float(prompt, default):
    raw = input(paint(f"{prompt} [{default:.0f}]: ", C.CYAN)).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        print(paint(f"  '{raw}' isn't a number, using {default:.0f}", C.YELLOW))
        return default


def _ask_year(default):
    raw = input(paint(f"Year to analyse (blank = 2021..{default}): ", C.CYAN)).strip()
    if not raw:
        return None  # sweep
    try:
        return int(raw)
    except ValueError:
        print(paint(f"  '{raw}' isn't a year, running the full sweep", C.YELLOW))
        return None


def main():
    _enable_ansi()

    p = argparse.ArgumentParser(description="Analyse BTC 6:30PM->5:30PM sessions by year.")
    p.add_argument("year", nargs="?", type=int, default=None,
                   help="Year to analyse (e.g. 2026). Omit to be asked / sweep.")
    p.add_argument("--up", type=float, default=None,
                   help="ABOVE band in points (breakout above the mark).")
    p.add_argument("--down", type=float, default=None,
                   help="BELOW band in points (breakdown below the mark).")
    p.add_argument("--all", action="store_true",
                   help="Sweep every year 2021..current (skips the year prompt).")
    p.add_argument("--exchange", default="binance", help="ccxt exchange id (default binance).")
    p.add_argument("--symbol", default="BTC/USDT", help="Trading symbol (default BTC/USDT).")
    args = p.parse_args()

    current_year = datetime.now(timezone.utc).year

    # ---- resolve year ----
    if args.all:
        year = None
    elif args.year is not None:
        year = args.year
    else:
        year = _ask_year(current_year)

    # ---- resolve bands (ask separately if not provided) ----
    up_band = args.up if args.up is not None else _ask_float("ABOVE range (points above mark)", 600.0)
    down_band = args.down if args.down is not None else _ask_float("BELOW range (points below mark)", 600.0)

    years = [year] if year is not None else list(range(2021, current_year + 1))

    for y in years:
        analyse_year(args.exchange, args.symbol, y, up_band, down_band)


if __name__ == "__main__":
    main()

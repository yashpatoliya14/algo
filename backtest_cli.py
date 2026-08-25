"""
BTCUSD 4H Trend Rider — Terminal Dashboard
============================================
Interactive CLI that backtests the Trend Rider strategy on BTCUSD 4H.
Select any year, see overall winrate, annual return, metrics & trade logs instantly.
Includes 0.5% profit trigger with 0.3% trailing stop loss.

Usage:  python backtest_cli.py
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_trend_backtest import fetch_ohlcv, list_exchange_products
from trend_rider_engine import (
    TrendRiderParams,
    run_trend_rider_backtest,
    get_metrics,
)
from symbol_utils import to_delta, to_ccxt, to_binance

# ============================================================================
# TERMINAL COLORS
# ============================================================================

class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    ITALIC = "\033[3m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    MAGENTA= "\033[95m"
    CYAN   = "\033[96m"
    WHITE  = "\033[97m"
    GRAY   = "\033[90m"

if sys.platform == "win32":
    os.system("")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

# ============================================================================
# CONFIG
# ============================================================================

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

CAPITAL = 10_000.0
SYMBOL = "BTC/USDT"
EXCHANGE = "binance"
DELTA_BASE_URL = os.getenv("DELTA_BASE_URL", "https://api.india.delta.exchange")

# Load cache limits from env
try:
    CACHE_MAX_SIZE_MB = int(os.getenv("CACHE_MAX_SIZE_MB", "200"))
    CACHE_MAX_AGE_DAYS = int(os.getenv("CACHE_MAX_AGE_DAYS", "90"))
except Exception:
    CACHE_MAX_SIZE_MB = 200
    CACHE_MAX_AGE_DAYS = 90

STRATEGY_DESC = (
    "Trend Rider v2 -- Supertrend(10,3) + EMA21/55 trend detection\n"
    "  Entries: Pullback-to-EMA21 | Donchian-30 Breakout | Supertrend Flip\n"
    "  Trailing Stop: 0.5% Profit Activation -> 0.3% Trailing Stop\n"
    "  No partial exits -- full ride on every trend"
)

# ============================================================================
# DISPLAY HELPERS
# ============================================================================

def color_val(val, good=0, great=None, suffix="", reverse=False):
    if reverse:
        if val >= good:
            return f"{C.GREEN}{val}{suffix}{C.RESET}"
        elif great is not None and val <= great:
            return f"{C.RED}{val}{suffix}{C.RESET}"
        return f"{C.YELLOW}{val}{suffix}{C.RESET}"
    if great is not None and val >= great:
        return f"{C.GREEN}{C.BOLD}{val}{suffix}{C.RESET}"
    if val >= good:
        return f"{C.GREEN}{val}{suffix}{C.RESET}"
    if val > 0:
        return f"{C.YELLOW}{val}{suffix}{C.RESET}"
    return f"{C.RED}{val}{suffix}{C.RESET}"


def sparkline(values, width=56):
    if not values or len(values) < 2:
        return ""
    blocks = " .,:-=+*#@"
    mn, mx = min(values), max(values)
    rng = mx - mn if mx != mn else 1
    step = max(1, len(values) // width)
    sampled = [values[i] for i in range(0, len(values), step)][:width]
    return "".join(blocks[int((v - mn) / rng * (len(blocks) - 1))] for v in sampled)


def print_header():
    print()
    print(f"  {C.CYAN}{C.BOLD}+{'=' * 58}+{C.RESET}")
    print(f"  {C.CYAN}{C.BOLD}|{C.RESET}      {C.MAGENTA}{C.BOLD}BTCUSD 4H TREND RIDER{C.RESET}  {C.GRAY}-- Crypto Trend Strategy{C.RESET}    {C.CYAN}{C.BOLD}|{C.RESET}")
    print(f"  {C.CYAN}{C.BOLD}|{C.RESET}      {C.GRAY}Pullback + Breakout + ST Flip + 0.5%->0.3% Trail{C.RESET}      {C.CYAN}{C.BOLD}|{C.RESET}")
    print(f"  {C.CYAN}{C.BOLD}+{'=' * 58}+{C.RESET}")
    print()


def divider(char="-", width=62):
    print(f"  {C.GRAY}{char * width}{C.RESET}")


def section(title, icon=""):
    print()
    print(f"  {C.CYAN}{C.BOLD}[{icon}] {title}{C.RESET}")
    divider()


# ============================================================================
# DATA FETCHING & CACHING
# ============================================================================

def _fetch_year_delta(year: int, symbol: str) -> pd.DataFrame | None:
    """Try fetching candle data from Delta Exchange (priority 1, no auth needed)."""
    try:
        # Map CCXT symbol to Delta format: BTC/USDT -> BTCUSD
        delta_sym = to_delta(symbol)
    except Exception:
        return None

    try:
        import requests

        base_url = DELTA_BASE_URL.rstrip("/")
        start_dt = datetime(year, 1, 1, tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        end_dt = now if year >= now.year else datetime(year + 1, 1, 1, tzinfo=timezone.utc)

        start_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp())

        all_candles = []
        cursor = start_ts
        resolution = "4h"

        # Delta returns max ~500 candles per request, so paginate
        while cursor < end_ts:
            params = {"symbol": delta_sym, "resolution": resolution, "start": cursor, "end": end_ts}
            resp = requests.get(f"{base_url}/v2/history/candles", params=params, timeout=15)
            resp.raise_for_status()
            batch = resp.json().get("result", [])
            if not batch:
                break
            all_candles.extend(batch)
            # Delta candles have "time" field in unix seconds
            last_time = max(c["time"] for c in batch)
            if last_time <= cursor:
                break
            cursor = last_time + 1
            time.sleep(0.3)  # rate limit courtesy

        if not all_candles:
            return None

        df = pd.DataFrame(all_candles)
        df["ts"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
        df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")

        if len(df) < 50:
            return None
        return df
    except Exception as e:
        print(f"  {C.YELLOW}[Delta fetch failed: {e}]{C.RESET}")
        return None


def fetch_year_data(year: int):
    """Fetch candle data: Delta Exchange (priority 1) → Binance (fallback)."""
    start = f"{year}-01-01"
    now = datetime.now(timezone.utc)
    end_dt = now if year >= now.year else datetime(year + 1, 1, 1, tzinfo=timezone.utc)

    # Priority 1: Try Delta Exchange
    print(f"  {C.GRAY}Trying Delta Exchange for {SYMBOL} 4H data ({year})...{C.RESET}", end="", flush=True)
    df4h = _fetch_year_delta(year, SYMBOL)
    if df4h is not None:
        print(f" {C.GREEN}{len(df4h)} bars (Delta){C.RESET}")
        return df4h

    # Fallback: Binance
    print(f" {C.YELLOW}no data{C.RESET}")
    print(f"  {C.GRAY}Falling back to Binance for {SYMBOL} 4H data ({year})...{C.RESET}", end="", flush=True)

    since_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    until_ms = int(end_dt.timestamp() * 1000)
    df4h = fetch_ohlcv(EXCHANGE, SYMBOL, "4h", since_ms, until_ms)
    print(f" {C.GREEN}{len(df4h)} bars (Binance){C.RESET}")

    return df4h


def cache_path(year: int, symbol: str = None) -> Path:
    symbol = (symbol or SYMBOL).replace("/", "_")
    return CACHE_DIR / f"rider_{symbol}_{year}.json"

def prune_cache():
    """Evict cache files older than max age or when total size exceeds limit."""
    files = list(CACHE_DIR.glob("rider_*.json"))
    now = datetime.now(timezone.utc)

    # Evict by age first
    for f in files:
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            age_days = (now - mtime).days
            if age_days > CACHE_MAX_AGE_DAYS:
                f.unlink()
        except Exception:
            pass

    # Evict by total size (oldest first)
    files = sorted(list(CACHE_DIR.glob("rider_*.json")), key=lambda p: p.stat().st_mtime)
    total_mb = sum(p.stat().st_size for p in files) / (1024 * 1024)
    while total_mb > CACHE_MAX_SIZE_MB and files:
        rm = files.pop(0)
        try:
            total_mb -= rm.stat().st_size / (1024 * 1024)
            rm.unlink()
        except Exception:
            pass

def year_complete(year: int) -> bool:
    return year < datetime.now(timezone.utc).year

def load_cache(year: int, symbol: str = None):
    p = cache_path(year, symbol)
    if not p.exists() or not year_complete(year):
        return None
    with open(p, "r") as f:
        return json.load(f)

def save_cache(year: int, data: dict, symbol: str = None):
    data["cached_at"] = datetime.now(timezone.utc).isoformat()
    with open(cache_path(year, symbol), "w") as f:
        json.dump(data, f)


def run_year(year: int):
    """Fetch data, run Trend Rider backtest with 0.5%->0.3% trailing stop, return result dict."""
    df4h = fetch_year_data(year)

    if len(df4h) < 100:
        raise ValueError(f"Insufficient data for {year}: only {len(df4h)} 4H bars")

    print(f"  {C.GRAY}Running Trend Rider backtest...{C.RESET}", flush=True)

    params = TrendRiderParams(
        trail_pct_activation=0.5, # Move 0.5% in profit -> activate trailing stop
        trail_pct_distance=0.3,   # Trail 0.3% behind peak price
    )
    trades, eq_df = run_trend_rider_backtest(df4h, params, capital=CAPITAL)
    metrics = get_metrics(trades, eq_df, CAPITAL)

    eq_values = [float(row["equity"]) for _, row in eq_df.iterrows()]

    trade_log = []
    for t in trades:
        trade_log.append({
            "dir": t.direction,
            "type": t.signal_type,
            "entry": t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else "-",
            "entry_px": round(t.entry_price, 2),
            "exit": t.exit_time.strftime("%Y-%m-%d %H:%M") if t.exit_time else "-",
            "exit_px": round(t.exit_price, 2) if t.exit_price else 0,
            "r": round(t.r_multiple, 2) if t.r_multiple is not None else 0,
            "pnl": round(t.pnl, 2),
            "reason": t.exit_reason,
        })

    return {
        "metrics": metrics,
        "equity_values": eq_values,
        "trades": trade_log,
        "data_bars": len(df4h),
    }


# ============================================================================
# DISPLAY RESULTS
# ============================================================================

def print_summary_card(m, year, from_cache, elapsed, data_bars):
    tag = f"{C.BLUE}[CACHED]{C.RESET}" if from_cache else f"{C.GREEN}[FRESH]{C.RESET}"
    
    print(f"\n  {C.CYAN}{C.BOLD}+{'='*64}+{C.RESET}")
    print(f"  {C.CYAN}{C.BOLD}|{C.RESET}  {C.WHITE}{C.BOLD}ANNUAL BACKTEST OVERVIEW -- YEAR {year}{C.RESET}  {tag} ({elapsed:.1f}s)  {C.CYAN}{C.BOLD}|{C.RESET}")
    print(f"  {C.CYAN}{C.BOLD}+{'='*64}+{C.RESET}")
    
    ret_color = C.GREEN if m['total_return_pct'] >= 15 else (C.YELLOW if m['total_return_pct'] >= 0 else C.RED)
    wr_color = C.GREEN if m['win_rate'] >= 50 else C.YELLOW
    
    print(f"  {C.BOLD}TOTAL RETURN FOR {year}:{C.RESET}     {ret_color}{C.BOLD}{m['total_return_pct']:>+6.1f}%{C.RESET}  ({m['net_profit']:+,.2f} USD)")
    print(f"  {C.BOLD}OVERALL WIN RATE:{C.RESET}          {wr_color}{C.BOLD}{m['win_rate']:>6.1f}%{C.RESET}  ({m['total_trades']} total trades)")
    print(f"  {C.BOLD}PROFIT FACTOR:{C.RESET}             {C.WHITE}{m['profit_factor']:>6.2f}{C.RESET}")
    print(f"  {C.BOLD}MAX DRAWDOWN:{C.RESET}              {C.RED}{m['max_drawdown']:>6.1f}%{C.RESET}")
    print(f"  {C.BOLD}FINAL EQUITY:{C.RESET}              {C.WHITE}${m['final_equity']:,.2f}{C.RESET}  (from ${CAPITAL:,.2f})")
    print(f"  {C.CYAN}{C.BOLD}+{'='*64}+{C.RESET}\n")


def display(result, year, from_cache, elapsed):
    m = result["metrics"]

    os.system("cls" if sys.platform == "win32" else "clear")
    print_header()

    # Always show top summary card
    print_summary_card(m, year, from_cache, elapsed, result.get('data_bars', 0))

    # -- DETAILED PERFORMANCE TABLE --
    section("DETAILED METRICS", "#")
    rows = [
        ("Total Return",    color_val(m["total_return_pct"], 0, 15, "%"),     "Net Profit",       f"${m['net_profit']:+,.2f}" if m['net_profit'] >= 0 else f"{C.RED}${m['net_profit']:+,.2f}{C.RESET}"),
        ("Win Rate",        color_val(m["win_rate"], 35, 50, "%"),            "Total Trades",     f"{C.WHITE}{m['total_trades']}{C.RESET}"),
        ("CAGR",            color_val(m["cagr"], 0, 15, "%"),                 "Trades/Month",     f"{C.WHITE}{m['trades_per_month']}{C.RESET}"),
        ("Profit Factor",   color_val(m["profit_factor"], 1.0, 1.5),         "Avg R-Multiple",   color_val(m["avg_r"], 0, 0.5, "R")),
        ("Sharpe Ratio",    color_val(m["sharpe"], 0, 1.0),                  "Sortino Ratio",    color_val(m["sortino"], 0, 1.0)),
        ("Max Drawdown",    color_val(m["max_drawdown"], -15, reverse=True, great=-30, suffix="%"),
                                                                              "Consec Losses",    f"{C.WHITE}{m['max_consec_losses']}{C.RESET}"),
        ("Final Equity",    f"{C.WHITE}${m['final_equity']:,.2f}{C.RESET}",  "Capital",           f"{C.GRAY}${CAPITAL:,.2f}{C.RESET}"),
    ]
    for ll, lv, rl, rv in rows:
        print(f"  {C.GRAY}{ll:<18}{C.RESET} {lv:<30}  {C.GRAY}{rl:<18}{C.RESET} {rv}")

    # -- TRADE BREAKDOWN --
    if m["total_trades"] > 0:
        section("TRADE BREAKDOWN", "~")
        print(f"  {C.GRAY}Long/Short:{C.RESET}       {C.GREEN}{m['long_trades']} longs{C.RESET} / {C.RED}{m['short_trades']} shorts{C.RESET}")
        print(f"  {C.GRAY}Entry Types:{C.RESET}      {C.CYAN}{m['pullback_entries']} pullback{C.RESET} | {C.MAGENTA}{m['breakout_entries']} breakout{C.RESET} | {C.YELLOW}{m['fresh_trend_entries']} fresh trend{C.RESET}")
        print(f"  {C.GRAY}Avg Winner R:{C.RESET}     {C.GREEN}{m['avg_winner_r']}R{C.RESET}")
        print(f"  {C.GRAY}Avg Loser R:{C.RESET}      {C.RED}{m['avg_loser_r']}R{C.RESET}")
        print(f"  {C.GRAY}Largest Win:{C.RESET}      {C.GREEN}${m['largest_winner']:+,.2f}{C.RESET}")
        print(f"  {C.GRAY}Largest Loss:{C.RESET}     {C.RED}${m['largest_loser']:+,.2f}{C.RESET}")

    # -- EQUITY CURVE --
    eq = result.get("equity_values", [])
    if eq:
        section("EQUITY CURVE", "$")
        color = C.GREEN if eq[-1] >= eq[0] else C.RED
        spark = sparkline(eq)
        print(f"  {C.GRAY}${eq[0]:,.0f}{C.RESET} {color}{spark}{C.RESET} {C.GRAY}${eq[-1]:,.0f}{C.RESET}")

    # -- TRADE LOG --
    trades = result.get("trades", [])
    if trades:
        section(f"TRADE LOG ({len(trades)} trades)", ">>")
        print(f"  {C.GRAY}{'#':>3} {'Dir':>5} {'Type':<10} {'Entry Date':<17} {'Entry$':>10} {'Exit Date':<17} {'Exit$':>10} {'R':>7} {'PnL':>10} {'Exit':<12}{C.RESET}")
        divider("-", 108)

        for i, t in enumerate(trades, 1):
            dc = C.GREEN if t["dir"] == "long" else C.RED
            ds = "LONG" if t["dir"] == "long" else "SHORT"
            pc = C.RED if t["pnl"] < 0 else C.GREEN
            rc = C.RED if t["r"] < 0 else C.GREEN
            tc = {
                "pullback": C.CYAN,
                "breakout": C.MAGENTA,
                "fresh_trend": C.YELLOW,
            }.get(t["type"], C.GRAY)

            print(f"  {C.GRAY}{i:>3}{C.RESET} {dc}{ds:>5}{C.RESET} {tc}{t['type']:<10}{C.RESET} {t['entry']:<17} {C.WHITE}${t['entry_px']:>9,.2f}{C.RESET} {t['exit']:<17} {C.WHITE}${t['exit_px']:>9,.2f}{C.RESET} {rc}{t['r']:>+6.2f}R{C.RESET} {pc}{t['pnl']:>+10,.2f}{C.RESET} {C.GRAY}{t['reason']:<12}{C.RESET}")

    # ALSO PRINT FINAL OVERVIEW AT THE VERY BOTTOM SO IT NEVER GETS LOST AFTER SCROLLING
    print_summary_card(m, year, from_cache, elapsed, result.get('data_bars', 0))


# ============================================================================
# MAIN
# ============================================================================

def main():
    global SYMBOL
    print_header()

    # Prune cache on startup
    prune_cache()

    # Optionally allow selecting a symbol from Delta Exchange products
    print(f"  {C.GRAY}Fetching available products from exchange...{C.RESET}")
    try:
        products = list_exchange_products(EXCHANGE)
        symbols = sorted([p for p in products if "/" in p])
    except Exception:
        symbols = []

    if symbols:
        print(f"  {C.BOLD}Available symbols sample:{C.RESET} {', '.join(symbols[:12])} ...")
        print(f"  Enter symbol in format 'BTC/USDT' or press Enter to use default ({SYMBOL})")
        sinput = input(f"  {C.CYAN}>{C.RESET} Symbol: ").strip()
        if sinput:
            try:
                SYMBOL_OVERRIDE = to_binance(sinput)
            except Exception:
                print(f"  {C.RED}Invalid symbol format: {sinput}. Using default {SYMBOL}{C.RESET}")
                SYMBOL_OVERRIDE = SYMBOL
        else:
            SYMBOL_OVERRIDE = SYMBOL
    else:
        SYMBOL_OVERRIDE = SYMBOL

    current_year = datetime.now().year
    years = list(range(2018, current_year + 1))

    while True:
        print(f"  {C.BOLD}{C.WHITE}Available Years:{C.RESET}")
        print()
        line = "  "
        for y in years:
            cached = cache_path(y, SYMBOL_OVERRIDE).exists() and year_complete(y)
            mark = f"{C.BLUE}*{C.RESET}" if cached else " "
            line += f"  {mark}{C.WHITE}{y}{C.RESET}"
        print(line)
        print()
        print(f"  {C.GRAY}{C.BLUE}*{C.RESET}{C.GRAY} = cached    Enter year or 'q' to quit{C.RESET}")
        print()

        try:
            choice = input(f"  {C.CYAN}>{C.RESET} Year: ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n  {C.GRAY}Goodbye!{C.RESET}\n")
            break

        if choice.lower() in ("q", "quit", "exit"):
            print(f"\n  {C.GRAY}Goodbye!{C.RESET}\n")
            break

        try:
            year = int(choice)
        except ValueError:
            print(f"  {C.RED}Invalid. Enter a year or 'q'.{C.RESET}\n")
            continue

        if year not in years:
            print(f"  {C.RED}Year {year} not available ({years[0]}-{years[-1]}).{C.RESET}\n")
            continue

        t0 = time.time()

        cached_data = load_cache(year, SYMBOL_OVERRIDE)
        if cached_data is not None:
            display(cached_data, year, True, time.time() - t0)
        else:
            print()
            try:
                # run with symbol override by temporarily setting SYMBOL
                old_sym = SYMBOL
                SYMBOL = SYMBOL_OVERRIDE
                result = run_year(year)
                SYMBOL = old_sym
                elapsed = time.time() - t0
                save_cache(year, result, SYMBOL_OVERRIDE)
                display(result, year, False, elapsed)
            except Exception as e:
                print(f"  {C.RED}Error: {e}{C.RESET}\n")
                continue

        divider("=", 62)
        print(f"  {C.GRAY}Enter to continue, 'q' to quit{C.RESET}")
        try:
            again = input(f"  {C.CYAN}>{C.RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n  {C.GRAY}Goodbye!{C.RESET}\n")
            break
        if again.lower() in ("q", "quit", "exit"):
            print(f"\n  {C.GRAY}Goodbye!{C.RESET}\n")
            break

        print_header()


if __name__ == "__main__":
    main()

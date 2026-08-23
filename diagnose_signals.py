"""
Signal Diagnostic Tool -- Why is my algo not generating signals?
================================================================
Fetches live 4H candle data for all SYMBOLS in .env, computes indicators,
and prints a detailed breakdown of every entry condition for the last
several candles to show exactly what's blocking signal generation.
"""

import os
import sys
import time
from datetime import datetime, timezone

# Force UTF-8 output on Windows
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv()

import numpy as np
import pandas as pd

from trend_rider_engine import TrendRiderParams, compute_indicators
from symbol_utils import to_ccxt, to_delta, to_binance
import requests


def fetch_candles_delta(symbol_delta: str, timeframe: str = "4h", limit: int = 150) -> pd.DataFrame | None:
    """Fetch candles from Delta Exchange REST API (matches delta_trader.py priority 1)."""
    try:
        base_url = os.getenv("DELTA_BASE_URL", "https://api.india.delta.exchange").strip()
        if (base_url.startswith('"') and base_url.endswith('"')) or (base_url.startswith("'") and base_url.endswith("'")):
            base_url = base_url[1:-1].strip()
        base_url = base_url.rstrip("/")

        now_ts = int(time.time())
        
        # Convert timeframe to multiplier
        tf = timeframe.strip().lower()
        multiplier = 4
        if tf.endswith("h"):
            multiplier = int(tf[:-1])
        elif tf.endswith("m"):
            multiplier = int(tf[:-1]) / 60
        elif tf.endswith("d"):
            multiplier = int(tf[:-1]) * 24

        start_ts = now_ts - int(limit * multiplier * 3600)

        params = {
            "symbol": symbol_delta,
            "resolution": timeframe,
            "start": start_ts,
            "end": now_ts
        }
        resp = requests.get(f"{base_url}/v2/history/candles", params=params, timeout=15)
        resp.raise_for_status()
        raw_candles = resp.json().get("result", [])
        if not raw_candles:
            return None

        df = pd.DataFrame(raw_candles)
        df["ts"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.rename(columns={"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"})
        df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
        df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")

        if len(df) < 5:
            return None
        return df
    except Exception as e:
        print(f"  [WARN] Delta candle fetch failed: {e}")
        return None


def fetch_candles_binance(symbol_ccxt: str, timeframe: str = "4h", limit: int = 150) -> pd.DataFrame:
    """Fetch candles from Binance via ccxt."""
    import ccxt
    binance_symbol = symbol_ccxt
    if binance_symbol.endswith("/USD"):
        binance_symbol = binance_symbol + "T"

    exchange = ccxt.binance({"enableRateLimit": True})
    now_ts = int(time.time())
    start_ts = now_ts - (limit * 4 * 3600)
    since_ms = start_ts * 1000

    all_rows = []
    cursor = since_ms
    until_ms = now_ts * 1000

    while cursor < until_ms:
        batch = exchange.fetch_ohlcv(binance_symbol, timeframe=timeframe, since=cursor, limit=1000)
        if not batch:
            break
        all_rows.extend(batch)
        cursor = batch[-1][0] + 1
        if len(batch) < 2:
            break
        time.sleep(exchange.rateLimit / 1000)

    df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.drop_duplicates("ts").set_index("ts")
    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
    return df


def diagnose_symbol(symbol_canonical: str, params: TrendRiderParams, lookback_bars: int = 10):
    """Diagnose signal conditions for a single symbol over the last N completed candles."""
    print(f"\n{'='*75}")
    print(f"  DIAGNOSING: {symbol_canonical}")
    print(f"{'='*75}")

    df = None
    try:
        # Try fetching from Delta Exchange first (matches live bot)
        symbol_delta = to_delta(symbol_canonical)
        df = fetch_candles_delta(symbol_delta, "4h", limit=150)
        if df is not None:
            print(f"  [DATA] Candles from Delta Exchange ({len(df)} bars)")
        else:
            print(f"  [DATA] Delta returned no data for {symbol_delta}, trying Binance fallback...")
            df = fetch_candles_binance(symbol_canonical, "4h", limit=150)
            if df is not None:
                print(f"  [DATA] Candles from Binance fallback ({len(df)} bars)")
    except Exception as e:
        print(f"  [ERROR] Could not fetch data: {e}")
        return

    if df is None:
        print("  [ERROR] Failed to fetch candle data from both Delta and Binance.")
        return

    d = compute_indicators(df, params)
    d = d.dropna(subset=["ema_fast", "ema_slow", "atr", "st_dir", "donchian_high"])

    if len(d) < 5:
        print("  [ERROR] Not enough data after indicator computation.")
        return

    # Show current market state
    latest = d.iloc[-2]  # last completed candle (same as live algo uses)
    prev = d.iloc[-3]
    live = d.iloc[-1]  # current forming candle

    print(f"\n  [MARKET STATE] Last completed 4H candle:")
    print(f"     Time:           {latest.name}")
    print(f"     Close:          ${latest['close']:,.2f}")
    print(f"     EMA21 (Fast):   ${latest['ema_fast']:,.2f}")
    print(f"     EMA55 (Slow):   ${latest['ema_slow']:,.2f}")
    print(f"     SuperTrend:     {'BULL' if latest['st_dir'] == 1 else 'BEAR'} (dir={int(latest['st_dir'])})")
    print(f"     RSI:            {latest['rsi']:.1f}")
    print(f"     ATR:            ${latest['atr']:,.2f}")
    print(f"     Donchian High:  ${latest['donchian_high']:,.2f}")
    print(f"     Donchian Low:   ${latest['donchian_low']:,.2f}")

    # Trend alignment
    ema_bull = latest["ema_fast"] > latest["ema_slow"]
    st_bull = latest["st_dir"] == 1
    ema_bear = latest["ema_fast"] < latest["ema_slow"]
    st_bear = latest["st_dir"] == -1

    trend_bull = ema_bull and st_bull
    trend_bear = ema_bear and st_bear

    print(f"\n  [TREND ALIGNMENT CHECK]")
    print(f"     EMA21 > EMA55:        {'YES' if ema_bull else 'NO'} (fast={latest['ema_fast']:.2f}, slow={latest['ema_slow']:.2f})")
    print(f"     SuperTrend Bullish:    {'YES' if st_bull else 'NO'}")
    print(f"     => trend_bull:         {'YES' if trend_bull else 'NO'}")
    print(f"     EMA21 < EMA55:        {'YES' if ema_bear else 'NO'}")
    print(f"     SuperTrend Bearish:    {'YES' if st_bear else 'NO'}")
    print(f"     => trend_bear:         {'YES' if trend_bear else 'NO'}")

    if not trend_bull and not trend_bear:
        print(f"\n  *** DIAGNOSIS: CONFLICTING TREND -- EMAs and SuperTrend disagree. ***")
        print(f"     This is the MOST COMMON reason for no signals.")
        print(f"     The algo requires BOTH EMA crossover AND SuperTrend to align.")
        if ema_bull and st_bear:
            print(f"     => EMA says BULL but SuperTrend says BEAR (mixed/choppy market)")
        elif ema_bear and st_bull:
            print(f"     => EMA says BEAR but SuperTrend says BULL (mixed/choppy market)")

    # EMA slope check
    ema_fast_slope_bull = bool(latest["ema_fast_slope"])
    ema_fast_slope_bear = bool(latest["ema_fast_slope_short"])

    print(f"\n  [EMA SLOPE CHECK]")
    print(f"     EMA21 rising (slope > 3 bars ago): {'YES' if ema_fast_slope_bull else 'NO'}")
    print(f"     EMA21 falling (slope < 3 bars ago): {'YES' if ema_fast_slope_bear else 'NO'}")

    if trend_bull and not ema_fast_slope_bull:
        print(f"     *** Trend is bullish but EMA slope is FLAT/DOWN -- no long signals possible.")
    if trend_bear and not ema_fast_slope_bear:
        print(f"     *** Trend is bearish but EMA slope is FLAT/UP -- no short signals possible.")

    # Individual entry condition analysis
    ema_val = latest["ema_fast"]

    print(f"\n  [ENTRY CONDITION ANALYSIS] (Last Completed Candle)")

    if trend_bull and ema_fast_slope_bull:
        print(f"     [LONG Mode Active -- Checking 3 entry types]")

        # Pullback
        pb_touch = prev["low"] <= ema_val * 1.003
        pb_close_above = latest["close"] > ema_val
        pb_bullish = latest["close"] > latest["open"]
        is_pullback = pb_touch and pb_close_above and pb_bullish
        print(f"\n     PULLBACK Entry:")
        print(f"        Prev low touched EMA21*1.003 ({ema_val*1.003:.2f}): {'YES' if pb_touch else 'NO'} (prev low={prev['low']:.2f})")
        print(f"        Close > EMA21:                                    {'YES' if pb_close_above else 'NO'} (close={latest['close']:.2f}, ema={ema_val:.2f})")
        print(f"        Bullish candle (close > open):                    {'YES' if pb_bullish else 'NO'} (close={latest['close']:.2f}, open={latest['open']:.2f})")
        print(f"        => PULLBACK SIGNAL: {'YES' if is_pullback else 'NO'}")

        # Breakout
        bo_above = latest["close"] > latest["donchian_high"]
        bo_rsi = latest["rsi"] < params.rsi_ob
        is_breakout = bo_above and bo_rsi
        print(f"\n     BREAKOUT Entry:")
        print(f"        Close > Donchian High: {'YES' if bo_above else 'NO'} (close={latest['close']:.2f}, dh={latest['donchian_high']:.2f})")
        print(f"        RSI < {params.rsi_ob}:              {'YES' if bo_rsi else 'NO'} (rsi={latest['rsi']:.1f})")
        print(f"        => BREAKOUT SIGNAL: {'YES' if is_breakout else 'NO'}")

        # Fresh Trend
        st_flip = bool(latest["st_recent_bull"])
        ft_above = latest["close"] > ema_val
        is_fresh = st_flip and ft_above
        print(f"\n     FRESH TREND Entry:")
        print(f"        SuperTrend recently flipped bull: {'YES' if st_flip else 'NO'}")
        print(f"        Close > EMA21:                    {'YES' if ft_above else 'NO'}")
        print(f"        => FRESH TREND SIGNAL: {'YES' if is_fresh else 'NO'}")

    elif trend_bear and ema_fast_slope_bear:
        print(f"     [SHORT Mode Active -- Checking 3 entry types]")

        # Pullback
        pb_touch = prev["high"] >= ema_val * 0.997
        pb_close_below = latest["close"] < ema_val
        pb_bearish = latest["close"] < latest["open"]
        is_pullback = pb_touch and pb_close_below and pb_bearish
        print(f"\n     PULLBACK Entry:")
        print(f"        Prev high touched EMA21*0.997 ({ema_val*0.997:.2f}): {'YES' if pb_touch else 'NO'} (prev high={prev['high']:.2f})")
        print(f"        Close < EMA21:                                      {'YES' if pb_close_below else 'NO'} (close={latest['close']:.2f}, ema={ema_val:.2f})")
        print(f"        Bearish candle (close < open):                      {'YES' if pb_bearish else 'NO'} (close={latest['close']:.2f}, open={latest['open']:.2f})")
        print(f"        => PULLBACK SIGNAL: {'YES' if is_pullback else 'NO'}")

        # Breakout
        bo_below = latest["close"] < latest["donchian_low"]
        bo_rsi = latest["rsi"] > params.rsi_os
        is_breakout = bo_below and bo_rsi
        print(f"\n     BREAKOUT Entry:")
        print(f"        Close < Donchian Low: {'YES' if bo_below else 'NO'} (close={latest['close']:.2f}, dl={latest['donchian_low']:.2f})")
        print(f"        RSI > {params.rsi_os}:             {'YES' if bo_rsi else 'NO'} (rsi={latest['rsi']:.1f})")
        print(f"        => BREAKOUT SIGNAL: {'YES' if is_breakout else 'NO'}")

        # Fresh Trend
        st_flip = bool(latest["st_recent_bear"])
        ft_below = latest["close"] < ema_val
        is_fresh = st_flip and ft_below
        print(f"\n     FRESH TREND Entry:")
        print(f"        SuperTrend recently flipped bear: {'YES' if st_flip else 'NO'}")
        print(f"        Close < EMA21:                    {'YES' if ft_below else 'NO'}")
        print(f"        => FRESH TREND SIGNAL: {'YES' if is_fresh else 'NO'}")
    else:
        print(f"     [X] Neither LONG nor SHORT mode is active -- trend not aligned or slope flat.")
        print(f"        => NO entry conditions are even evaluated when trend/slope doesn't align.")

    # Historical signal scan -- look back to see when last signal occurred
    print(f"\n  [SIGNAL HISTORY] (last {lookback_bars} candles = {lookback_bars * 4}h)")
    signals_found = 0
    for i in range(len(d) - 2, max(len(d) - 2 - lookback_bars, 2), -1):
        row = d.iloc[i]
        prev_row = d.iloc[i - 1]
        ema_v = row["ema_fast"]

        sig = None
        sig_type = ""

        if row["trend_bull"] and row["ema_fast_slope"]:
            if (prev_row["low"] <= ema_v * 1.003) and (row["close"] > ema_v) and (row["close"] > row["open"]):
                sig, sig_type = "LONG", "pullback"
            elif (row["close"] > row["donchian_high"]) and (row["rsi"] < params.rsi_ob):
                sig, sig_type = "LONG", "breakout"
            elif row["st_recent_bull"] and (row["close"] > ema_v):
                sig, sig_type = "LONG", "fresh_trend"
        elif row["trend_bear"] and row["ema_fast_slope_short"]:
            if (prev_row["high"] >= ema_v * 0.997) and (row["close"] < ema_v) and (row["close"] < row["open"]):
                sig, sig_type = "SHORT", "pullback"
            elif (row["close"] < row["donchian_low"]) and (row["rsi"] > params.rsi_os):
                sig, sig_type = "SHORT", "breakout"
            elif row["st_recent_bear"] and (row["close"] < ema_v):
                sig, sig_type = "SHORT", "fresh_trend"

        if sig:
            signals_found += 1
            print(f"     >> {row.name} -> {sig} {sig_type}")

    if signals_found == 0:
        print(f"     No signals found in the last {lookback_bars} candles.")

    # Extended scan -- find the LAST signal whenever it was
    print(f"\n  [LAST SIGNAL EVER] (scanning all available data)")
    for i in range(len(d) - 2, 2, -1):
        row = d.iloc[i]
        prev_row = d.iloc[i - 1]
        ema_v = row["ema_fast"]

        sig = None
        sig_type = ""

        if row["trend_bull"] and row["ema_fast_slope"]:
            if (prev_row["low"] <= ema_v * 1.003) and (row["close"] > ema_v) and (row["close"] > row["open"]):
                sig, sig_type = "LONG", "pullback"
            elif (row["close"] > row["donchian_high"]) and (row["rsi"] < params.rsi_ob):
                sig, sig_type = "LONG", "breakout"
            elif row["st_recent_bull"] and (row["close"] > ema_v):
                sig, sig_type = "LONG", "fresh_trend"
        elif row["trend_bear"] and row["ema_fast_slope_short"]:
            if (prev_row["high"] >= ema_v * 0.997) and (row["close"] < ema_v) and (row["close"] < row["open"]):
                sig, sig_type = "SHORT", "pullback"
            elif (row["close"] < row["donchian_low"]) and (row["rsi"] > params.rsi_os):
                sig, sig_type = "SHORT", "breakout"
            elif row["st_recent_bear"] and (row["close"] < ema_v):
                sig, sig_type = "SHORT", "fresh_trend"

        if sig:
            bars_ago = len(d) - 2 - i
            hours_ago = bars_ago * 4
            days_ago = hours_ago / 24
            print(f"     Last signal: {sig} {sig_type} at {row.name}")
            print(f"     ({bars_ago} bars ago = {hours_ago}h = {days_ago:.1f} days)")
            break
    else:
        print(f"     No signals found in entire dataset!")


def main():
    symbols_env = os.getenv("SYMBOLS", "")
    if symbols_env:
        symbols = [s.strip() for s in symbols_env.split(",") if s.strip()]
    else:
        symbols = [os.getenv("SYMBOL", "BTCUSD")]

    # Canonicalize
    canonical_symbols = []
    for s in symbols:
        try:
            canonical_symbols.append(to_ccxt(s))
        except Exception:
            print(f"  [WARN] Skipping invalid symbol: {s}")

    def get_env_stripped(key: str, default: str = "") -> str:
        val = os.getenv(key, default).strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1].strip()
        return val

    params = TrendRiderParams(
        trail_pct_activation=float(get_env_stripped("TRAIL_PCT_ACTIVATION", "1.0")),
        trail_pct_distance=float(get_env_stripped("TRAIL_PCT_DISTANCE", "0.4")),
    )

    print("=" * 75)
    print(f"  ALGO SIGNAL DIAGNOSTIC -- {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Checking {len(canonical_symbols)} symbols: {', '.join(canonical_symbols)}")
    print(f"  Strategy: 4H Trend Rider")
    print("=" * 75)

    for sym in canonical_symbols:
        try:
            diagnose_symbol(sym, params, lookback_bars=42)  # 42 bars = 7 days of 4H candles
        except Exception as e:
            print(f"\n  [ERROR] {sym}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*75}")
    print(f"  DIAGNOSTIC COMPLETE")
    print(f"{'='*75}")


if __name__ == "__main__":
    main()

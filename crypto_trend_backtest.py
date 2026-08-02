"""
Institutional-Grade 4H Trend-Following Strategy — Backtesting Utilities
=========================================================================
Contains data fetching (ccxt), indicator calculations (EMA, ATR, RSI, ADX, Supertrend, Choppiness),
and core strategy metrics used across the project.
"""

import time
import numpy as np
import pandas as pd


# ============================================================================
# INDICATORS
# ============================================================================

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = true_range(df)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = true_range(df)
    atr_ = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0)


def supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0):
    atr_ = atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2
    upper = hl2 + mult * atr_
    lower = hl2 - mult * atr_

    final_upper = upper.copy()
    final_lower = lower.copy()
    direction = pd.Series(1, index=df.index)

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

    return direction


def choppiness_index(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = true_range(df)
    atr_sum = tr.rolling(period).sum()
    hh = df["high"].rolling(period).max()
    ll = df["low"].rolling(period).min()
    rng = (hh - ll).replace(0, np.nan)
    return 100 * np.log10(atr_sum / rng) / np.log10(period)


# ============================================================================
# DATA FETCHING (ccxt)
# ============================================================================

def fetch_ohlcv(exchange_id: str, symbol: str, timeframe: str, since_ms: int, until_ms: int) -> pd.DataFrame:
    """Fetch complete OHLCV data using CCXT with pagination."""
    import ccxt

    exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    all_rows = []
    cursor = since_ms

    while cursor < until_ms:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=1000)
        if not batch:
            break
        all_rows.extend(batch)
        cursor = batch[-1][0] + 1
        if len(batch) < 2:
            break
        time.sleep(exchange.rateLimit / 1000)

    if not all_rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.drop_duplicates("ts").set_index("ts")
    df = df[(df.index >= pd.to_datetime(since_ms, unit="ms", utc=True)) &
            (df.index <= pd.to_datetime(until_ms, unit="ms", utc=True))]
    return df


def list_exchange_products(exchange_id: str) -> list:
    """Return a list of product symbols from CCXT exchange (e.g., 'BTC/USDT')."""
    try:
        import ccxt
        exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        markets = exchange.load_markets()
        return list(markets.keys())
    except Exception:
        return []

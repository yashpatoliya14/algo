import pandas as pd
from backtest_cli import fetch_ohlcv, run_trend_rider_backtest, TrendRiderParams, get_metrics
from backtest_cli import _fetch_year_delta
from datetime import datetime, timezone

SYMBOL = "AVAX/USDT"
EXCHANGE = "binance"
year = 2026

start = f"{year}-01-01"
now = datetime.now(timezone.utc)
end_dt = now if year >= now.year else datetime(year + 1, 1, 1, tzinfo=timezone.utc)
since_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
until_ms = int(end_dt.timestamp() * 1000)

print(f"Fetching 4H from Binance for {SYMBOL}")
df4h = fetch_ohlcv(EXCHANGE, SYMBOL, "4h", since_ms, until_ms)

print(f"Fetching 1H from Delta for {SYMBOL}")
# Delta symbol for AVAX/USDT is AVAXUSD
df_ltf = _fetch_year_delta(year, "AVAX/USDT") # Wait, _fetch_year_delta gets 4H. Let me use CCXT or just simulate.
# Actually I need the 1H data from Delta.
import requests
base_url = "https://api.india.delta.exchange"
start_ts = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp())
end_ts = int(end_dt.timestamp())
all_candles = []
cursor = start_ts
while cursor < end_ts:
    params = {"symbol": "AVAXUSD", "resolution": "1h", "start": cursor, "end": end_ts}
    resp = requests.get(f"{base_url}/v2/history/candles", params=params, timeout=15)
    batch = resp.json().get("result", [])
    if not batch: break
    all_candles.extend(batch)
    last_time = max(c["time"] for c in batch)
    if last_time <= cursor: break
    cursor = last_time + 1
df_ltf = pd.DataFrame(all_candles)
df_ltf["ts"] = pd.to_datetime(df_ltf["time"], unit="s", utc=True)
df_ltf = df_ltf.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
df_ltf = df_ltf.sort_values("ts").drop_duplicates("ts").set_index("ts")

params = TrendRiderParams(
    trail_pct_activation=0.5,
    trail_pct_distance=0.3,
    ltf_enabled=True,
    ltf_confirm_mode="majority",
)

trades, eq_df = run_trend_rider_backtest(df4h, params, capital=10000.0, df_ltf=df_ltf)
metrics = get_metrics(trades, eq_df, 10000.0)

print("TOTAL RETURN:", metrics["total_return_pct"])
print("WIN RATE:", metrics["win_rate"])
print("TOTAL TRADES:", metrics["total_trades"])

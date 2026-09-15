import pandas as pd
from backtest_cli import fetch_ohlcv, run_trend_rider_backtest, TrendRiderParams, get_metrics
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

print(f"Fetching 1H from Binance for {SYMBOL}")
df_ltf = fetch_ohlcv(EXCHANGE, SYMBOL, "1h", since_ms, until_ms)

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

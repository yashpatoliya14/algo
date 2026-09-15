import pandas as pd
from backtest_cli import fetch_ohlcv, run_trend_rider_backtest, TrendRiderParams, get_metrics
from datetime import datetime, timezone
import concurrent.futures

symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "LINK/USDT", "DOT/USDT", "ADA/USDT", "XRP/USDT", "DOGE/USDT", "AVAX/USDT", "UNI/USDT", "MATIC/USDT"]
EXCHANGE = 'binance'
year = 2026

start = f'{year}-01-01'
now = datetime.now(timezone.utc)
end_dt = now if year >= now.year else datetime(year + 1, 1, 1, tzinfo=timezone.utc)
since_ms = int(pd.Timestamp(start, tz='UTC').timestamp() * 1000)
until_ms = int(end_dt.timestamp() * 1000)

def test_symbol(sym):
    try:
        df4h = fetch_ohlcv(EXCHANGE, sym, '4h', since_ms, until_ms)
        df_ltf = fetch_ohlcv(EXCHANGE, sym, '1h', since_ms, until_ms)
        params = TrendRiderParams(trail_pct_activation=0.5, trail_pct_distance=0.3, ltf_enabled=True, ltf_confirm_mode='majority')
        trades, eq_df = run_trend_rider_backtest(df4h, params, capital=10000.0, df_ltf=df_ltf)
        metrics = get_metrics(trades, eq_df, 10000.0)
        return sym, metrics['total_return_pct'], metrics['total_trades']
    except Exception as e:
        return sym, None, None

with concurrent.futures.ThreadPoolExecutor() as executor:
    results = list(executor.map(test_symbol, symbols))

for r in results:
    print(r)

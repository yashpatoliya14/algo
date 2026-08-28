# 05: Backtesting Engine

Before deploying a trading strategy with real capital, it must be validated against historical data. The backtesting framework allows you to simulate the 4H Crypto Trend Rider over years of data in seconds.

## How it Works

The backtesting suite is primarily driven by two files:
1. `backtest_cli.py`: The command-line interface and main orchestrator.
2. `crypto_trend_backtest.py`: Utilities for fetching, formatting, and preparing the historical data.

### 1. Data Fetching and Caching
Because downloading years of 4-hour candles takes time and API limits can be restrictive, the system uses a local caching mechanism.
* **Source:** By default, it uses the CCXT library to connect to Binance and download historical data, as Binance provides deep, reliable history for most crypto assets.
* **Cache Directory:** Data is saved as JSON files in the `cache/` directory.
* **File Structure:** Caches are split by symbol and year (e.g., `cache/trend_rider_BTC_USDT_2023.json`).
* When you run a backtest, the engine first checks the cache. If the required data is present, it loads it instantly from disk. If not, it fetches it via CCXT and saves it for next time.

### 2. Simulation
Once the historical dataframe is loaded, it is passed into `trend_rider_engine.py` using the `run_trend_rider_backtest()` function.
* The engine computes all indicators (EMA, ATR, RSI, SuperTrend) across the entire dataframe at once (vectorized) for speed.
* It then simulates iterating through the candles one by one, exactly as the live execution engine would, checking for entry signals and updating trailing stops.
* It maintains a ledger of all executed trades.

### 3. Output and Metrics
After the simulation completes, `backtest_cli.py` processes the ledger and outputs a detailed performance summary to the terminal.

Key metrics include:
* **Total Return:** The absolute percentage return if you traded 1 unit of risk per trade without compounding.
* **Win Rate:** Percentage of trades that were profitable (Keep in mind, trend following systems often have win rates near 40-50%, but massive profit factors because winners are much larger than losers).
* **Profit Factor:** Gross Profit divided by Gross Loss. (A value > 1.0 means the strategy is profitable. > 1.5 is excellent).
* **Max Drawdown:** The largest peak-to-trough drop in account equity. Crucial for understanding risk.

## Running the Backtester

To run a backtest, simply execute:
```bash
python backtest_cli.py
```

By default, it will read the `SYMBOLS` from your `.env` file and attempt to backtest them over a recent multi-year period (e.g., 2020-Present).

### Managing the Cache
Over time, the `cache/` folder can grow large. The CLI includes a command-line flag to clean up old cache files:

```bash
python backtest_cli.py --prune-cache
```

This ensures you are running on fresh data if needed, or freeing up disk space.

---

*This concludes the Developer Manual. With this knowledge, you should be fully equipped to understand, modify, and deploy the 4H Crypto Trend Rider.*

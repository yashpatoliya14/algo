# 01: Overview and Setup

## What is the 4H Crypto Trend Rider?

The 4H Crypto Trend Rider is a professional, institutional-grade automated trading algorithm designed specifically for cryptocurrency perpetual futures (like BTC/USDT) on Delta Exchange. 

It is a **trend-following system** built on the philosophy that crypto markets exhibit real, persistent, and directional runs. Rather than trying to predict tops and bottoms, the algorithm waits for a macro trend to establish itself on the 4-hour timeframe, waits for a high-probability pullback or breakout, and then rides the trend using a dynamic trailing stop.

### Key Features
* **Fully Rule-Based:** No discretionary judgment calls. Every entry, position size, stop loss, and exit is governed by strict mathematical logic.
* **Multi-Layer Filtering:** Uses EMA crossover (21/55), SuperTrend, EMA slope, and RSI to filter out choppy markets and low-probability signals.
* **Dynamic Risk Management:** Adaptive stop-losses based on ATR (Average True Range) meaning it automatically adjusts to high-volatility or low-volatility regimes.
* **Profit Maximization:** Uses a Chandelier-style trailing stop system that gives the trade room to breathe early on, but tightly locks in profits when the trade moves deep into profit (R-multiple trailing).
* **Live Execution:** Fully integrated with Delta Exchange REST API v2 for live or paper trading execution.
* **Backtesting Engine:** Includes a fast, cached backtesting CLI to evaluate performance over historical data.
* **Telegram Integration:** Sends real-time notifications for bot startup, entry signals, order executions, and exits.

---

## Quick Start Guide

### 1. Requirements
* Python 3.10 or higher.
* A Delta Exchange account with API keys (for live/paper trading).
* A Telegram Bot token (optional, for notifications).

### 2. Installation
First, clone the repository or open the project folder `yash_algo`.
Create a virtual environment and install the dependencies:

```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Mac/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Environment Configuration
The system relies heavily on environment variables for configuration. A template file `.env.example` is provided.
Copy `.env.example` to a new file named `.env`:

```bash
cp .env.example .env
```

Edit `.env` to configure your settings:
* **API Keys:** `DELTA_API_KEY` and `DELTA_API_SECRET`.
* **Symbols:** The assets you want to trade (e.g., `SYMBOLS=BTC/USDT,ETH/USDT`).
* **Dry Run:** Set `DRY_RUN=true` to test the logic without placing real orders, or `DRY_RUN=false` for live trading.
* **Risk/Margin:** Configure leverage (`LEVERAGE=50`) and either a fixed margin (`FIXED_MARGIN_USD=5`) or risk percentage (`SPLIT_BALANCE_MARGIN=true`).
* **Telegram:** `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to receive notifications.

### 4. Running a Backtest
Before trading live, you can evaluate the strategy against historical data.

```bash
python backtest_cli.py
```
This will fetch historical candles, run the algorithm, and output a performance summary (Win Rate, Profit Factor, Returns).

### 5. Running the Live/Paper Trader
To start the live execution loop that polls for new candles and places orders on Delta Exchange:

```bash
python delta_trader.py
```
*Note: Ensure `DRY_RUN=true` if you are just testing the connection and logic without risking capital.*

---

## What's Next?
* To understand how the components fit together, read **[02 System Architecture](02_System_Architecture.md)**.
* To dive deep into the math and logic behind the entry and exit signals, read **[03 Trading Strategy](03_Trading_Strategy.md)**.
* To see how orders are actually placed and managed, check out **[04 Live Execution Engine](04_Live_Execution_Engine.md)**.

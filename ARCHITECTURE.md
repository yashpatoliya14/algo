# 🏛️ Architecture Documentation: 4H Crypto Trend Rider

## 1. System Overview

The **Crypto Trend Rider** system is an institutional-grade 4-Hour trend-following trading framework designed for Bitcoin (BTCUSD). It combines multi-indicator trend identification, dynamic pullback/breakout triggers, percentage-based trailing stops, and a direct execution adapter for **Delta Exchange**.

```
                           +------------------------+
                           |  Binance / Delta API   |
                           |   (4H OHLCV Data)      |
                           +-----------+------------+
                                       |
                                       v
                           +------------------------+
                           |   Trend Rider Engine   |
                           | (trend_rider_engine.py)|
                           +-----------+------------+
                                       |
                   +-------------------+-------------------+
                   |                                       |
                   v                                       v
     +---------------------------+           +---------------------------+
     |   Terminal Backtest CLI   |           |    Delta Exchange Bot     |
     |     (backtest_cli.py)     |           |     (delta_trader.py)     |
     +---------------------------+           +---------------------------+
```

---

## 2. Core Modules

| Module | File | Purpose |
| :--- | :--- | :--- |
| **Strategy Engine** | [trend_rider_engine.py](file:///c:/Users/yashp/OneDrive/Desktop/yash_algo/trend_rider_engine.py) | Contains indicator logic (EMA21/55, Supertrend, Donchian, ATR), signal triggers (Pullback, Breakout, ST Flip), and position management rules. |
| **Data & Indicators** | [crypto_trend_backtest.py](file:///c:/Users/yashp/OneDrive/Desktop/yash_algo/crypto_trend_backtest.py) | Provides CCXT data fetching helper and baseline indicator math (EMA, ATR, RSI, ADX, Supertrend, Choppiness). |
| **Terminal CLI** | [backtest_cli.py](file:///c:/Users/yashp/OneDrive/Desktop/yash_algo/backtest_cli.py) | Interactive terminal backtester with colorized output, annual win rate & return boxes, equity sparklines, and caching. |
| **Live Trader Bot** | [delta_trader.py](file:///c:/Users/yashp/OneDrive/Desktop/yash_algo/delta_trader.py) | Live / paper-trading execution engine connecting directly to Delta Exchange REST API v2 for signal evaluation and order placement. |

---

## 3. Signal & Execution Pipeline

1. **Market Data Sync**: Every 4 hours (at candle close), fetch 4H OHLCV data.
2. **Regime Identification**:
   - `EMA(21) > EMA(55)` and `Supertrend(10,3) == Bullish` and `EMA(21) Slope > 0` $\rightarrow$ **Bullish Regime**
   - `EMA(21) < EMA(55)` and `Supertrend(10,3) == Bearish` and `EMA(21) Slope < 0` $\rightarrow$ **Bearish Regime**
3. **Signal Generation**:
   - **Pullback**: Price touches/dips to `EMA 21` and closes back in trend direction with a bullish candle.
   - **Donchian Breakout**: Price breaks 30-period (~5 day) high/low.
   - **Supertrend Flip**: Supertrend transitions direction in trend alignment.
4. **Position Sizing & Risk**:
   $$\text{Position Size} = \frac{\text{Account Equity} \times \text{Risk \%}}{\text{Entry Price} - \text{Stop Loss Price}}$$
5. **Trailing Stop Management**:
   - Initial Stop: $2.0 \times \text{ATR}$
   - Activation: When price moves $+1.0\%$ in profit, activate trailing stop.
   - Trail Distance: $0.4\%$ behind peak price achieved.

---

## 4. Delta Exchange Integration Architecture

```
[delta_trader.py]
  │
  ├── 1. Auth Headers: HMAC-SHA256 (api-key, timestamp, signature)
  ├── 2. GET /v2/history/candles?symbol=BTCUSD&resolution=4h  ──> Signal Check
  ├── 3. GET /v2/positions (Check current position state)
  ├── 4. POST /v2/orders (Submit Market / Stop-Loss orders)
  └── 5. PUT /v2/orders (Update trailing stop on peak move)
```

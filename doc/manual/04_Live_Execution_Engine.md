# 04: Live Execution Engine

The file `delta_trader.py` is the live execution engine that bridges the mathematical logic of the strategy with the real world of exchange APIs and live market data.

## The Polling Loop

Instead of relying on webhooks or streaming WebSockets (which can drop connections or miss data), the engine uses a robust **polling architecture**.

1. **Wake Up:** Every X seconds (configurable via `POLL_INTERVAL_SEC` in `.env`, default 60s), the bot wakes up.
2. **Fetch Data:** For each symbol defined in `SYMBOLS` (e.g., `BTC/USDT`), it fetches the last ~100 completed 4H candles. It primarily uses the Delta Exchange API, but has a fallback mechanism.
3. **Compute Indicators:** The candles are passed to `trend_rider_engine.py` which computes the EMAs, ATR, SuperTrend, etc.
4. **Manage Existing Positions:** If there is an open position for a symbol:
    * It checks the current price against the trailing stop logic.
    * If the price hit the stop, or if the SuperTrend flipped against the position, it executes a market close order immediately.
    * Otherwise, it updates the "Peak Price" (highest high for longs, lowest low for shorts) and recalculates the trailing stop. If the new stop is tighter, it modifies the stop-loss order on the exchange.
5. **Check for Entries:** If there is NO open position, and the cooldown period has expired:
    * It checks the `trend_rider_engine` for a valid entry signal (Pullback, Breakout, Fresh Trend).
    * If a signal is found, it calculates position sizing.
6. **Execute Entry:** It fires a market order to enter the trade, and immediately places a stop-loss order at the initial calculated distance.
7. **Sleep:** The bot goes back to sleep until the next polling cycle.

## Position Sizing Math

The engine calculates how many contracts to buy/sell based on your `.env` configuration.

### Option 1: Split Balance (Default)
If `SPLIT_BALANCE_MARGIN=true`:
* Calculates `Margin per symbol = Total Equity / Number of Symbols`.
* Uses `Notional Value = Margin * Leverage`.
* Calculates contracts based on current price.
* *Example:* $1000 account, 4 symbols = $250 allocated per symbol.

### Option 2: Fixed Margin
If `FIXED_MARGIN_USD=5` (and Split Balance is false):
* Every trade uses exactly $5 of margin, regardless of account size.

### Option 3: Risk-Based
If both above are false, it defaults to risking a specific percentage of the account:
* Calculates `Dollar Risk = Equity * Risk %`.
* Calculates position size such that if the initial stop-loss is hit, the loss equals exactly that Dollar Risk amount.

## API Integration (`delta_client.py`)

The engine relies on a custom wrapper for Delta Exchange's REST API. 
* **Authentication:** Uses API Key, Timestamp, and Ed25519 Signature hashing.
* **Orders:** Supports placing Market orders, Stop Market orders (for stop-loss), and canceling orders.
* **Safety:** Ensures trailing stops are modified safely by canceling the old stop and placing a new one.

## Telegram Integration

If configured in `.env`, the engine pushes state updates to a Telegram chat:
* **Startup:** "🚀 Delta Trader started. Trading: BTC/USDT..."
* **Signal:** Detailed breakdown of a signal when found (Entry price, Stop loss, Type of signal).
* **Execution:** Confirmation that the order was actually filled on the exchange.
* **Exit:** Notification of closure, including the R-multiple (how much profit/loss relative to initial risk).

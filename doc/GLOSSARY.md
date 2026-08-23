# 📖 Trading & Technical Terminology Glossary

A complete reference of every term, abbreviation, and concept used in the Trend Rider 4H algo trading system. If you encounter any term in the code, logs, or signals that you don't understand, look it up here.

---

## A

### ATR (Average True Range)
**What:** A volatility indicator that measures the average range (size) of price candles over a period.
**How it works:** Takes the True Range (maximum of: High-Low, |High-PrevClose|, |Low-PrevClose|) and averages it over N periods using exponential smoothing.
**Our setting:** Period = 14 candles (= 56 hours on 4H chart)
**Used for:** Setting stop-loss distances, trailing stop calculations. Higher ATR = wider stops (more volatile market).
**Example:** If BTC ATR = $1,374, a 2× ATR stop means your stop is $2,749 away from entry.

### API Key / API Secret
**What:** Authentication credentials provided by the exchange (Delta Exchange) to allow the bot to read data and place orders on your behalf.
**Security:** The secret is like a password — never share it. The key identifies who you are, the secret proves it's really you.

---

## B

### Backtest
**What:** Running the strategy on historical data to see how it would have performed in the past.
**Why:** To test and validate strategy parameters before risking real money.
**Command:** `python backtest_cli.py`

### Break-Even (BE)
**What:** Moving the stop-loss to the entry price (or slightly above) so the trade can no longer lose money.
**In our algo:** When the trade reaches 1R profit, the stop moves to `entry + 0.2 × ATR` (slightly above break-even for longs).

### Breakout
**What:** When price closes above a resistance level (long) or below a support level (short) for the first time.
**In our algo:** Specifically, closing above the 30-period Donchian High or below the 30-period Donchian Low.

---

## C

### Candle / Candlestick
**What:** A single time period's worth of price data showing Open, High, Low, Close (OHLC).
**4H candle:** Represents 4 hours of trading. Shows where the price opened, the highest point, lowest point, and where it closed.
**Bullish candle:** Close > Open (green) — buyers won that period
**Bearish candle:** Close < Open (red) — sellers won that period

### CAGR (Compound Annual Growth Rate)
**What:** The annualized rate of return assuming compounding. Tells you the yearly % return if the growth was smooth and consistent.
**Formula:** `((final_equity / initial_equity) ^ (1/years) - 1) × 100`

### CCXT
**What:** A Python library (CryptoCurrency eXchange Trading Library) that provides a unified API to interact with many crypto exchanges.
**In our algo:** Used as a fallback to fetch candle data from Binance when Delta Exchange doesn't have data.

### Chandelier Stop
**What:** A trailing stop method that sets the stop at a fixed ATR distance below the highest high (for longs) or above the lowest low (for shorts).
**In our algo:**
- Phase 2 (2R-4R): `peak_price - 2.5 × ATR` for longs
- Phase 3 (4R+): `peak_price - 1.8 × ATR` for longs (tighter = more profit locked)

### Contract Value
**What:** The value that each contract represents on the exchange. On Delta Exchange, 1 contract of BTCUSD might equal 0.001 BTC.
**Why it matters:** Determines how many contracts to buy for a given dollar amount.

### Cooldown (Period/Bars)
**What:** A mandatory waiting period after closing a trade before the algo can enter a new one on the same symbol.
**Our setting:** 3 bars = 12 hours (on 4H timeframe)
**Why:** Prevents rapid-fire entries after a loss (whipsaw protection).

---

## D

### Delta Exchange
**What:** A cryptocurrency derivatives exchange that offers perpetual futures trading. The India version (`api.india.delta.exchange`) is used in this algo.

### Donchian Channel
**What:** The highest high and lowest low over the last N periods. Named after Richard Donchian, the "father of trend following."
**Our setting:** Period = 30 candles (= 5 days on 4H chart), shifted by 1 bar
**Donchian High:** `max(high) of last 30 candles`
**Donchian Low:** `min(low) of last 30 candles`
**Used for:** Breakout signal detection

### DRY_RUN (Paper Trading)
**What:** A mode where the bot simulates trades without placing real orders or risking real money.
**Set:** `DRY_RUN=true` in `.env` file
**Use:** Always test in dry run before going live!

### Drawdown
**What:** The decline from a peak equity value to a trough. Measures the worst loss from top to bottom.
**Max Drawdown:** The largest peak-to-trough decline, expressed as a percentage.
**Example:** If equity peaked at $15,000 then dropped to $12,000, max drawdown = -20%.

---

## E

### EMA (Exponential Moving Average)
**What:** A moving average that gives more weight to recent prices, making it more responsive to new information than a Simple Moving Average (SMA).
**EMA21 ("Fast"):** Reacts quickly to price changes, acts as dynamic support/resistance
**EMA55 ("Slow"):** Reacts more slowly, confirms the medium-term trend
**Crossover:** When EMA21 crosses above EMA55 = bullish; below = bearish

### EMA Slope
**What:** Whether the EMA is currently rising or falling, measured by comparing the current EMA value to the value 3 bars ago.
**Bull slope:** `EMA21_now > EMA21_3bars_ago` (EMA is going up)
**Bear slope:** `EMA21_now < EMA21_3bars_ago` (EMA is going down)
**Why:** Prevents entries when the trend is flattening out.

### Entry Price
**What:** The price at which you open a position (buy for long, sell for short).

### Equity
**What:** Your total account value including unrealized P&L. In backtesting, starts at $10,000 by default.

### Exit
**What:** Closing a position (selling for long, buying for short).
**Exit reasons in this algo:**
- `trail_stop` — trailing stop was hit
- `st_reversed` — SuperTrend direction reversed
- `end_of_data` — backtest ended with position still open

### Expectancy (R-Expectancy)
**What:** The average R-multiple across all trades. Tells you how much you expect to make per unit of risk.
**Formula:** Average of all R-multiples
**Good:** > 0.3R means the strategy has a positive edge

---

## F

### Fresh Trend
**What:** An entry signal that fires when the SuperTrend indicator just flipped direction (from bear to bull, or bull to bear) within the last 1-2 candles, AND price confirms by being on the right side of EMA21.
**Why:** Catches the very beginning of new trend moves.

---

## H

### HMAC (Hash-based Message Authentication Code)
**What:** A cryptographic signing method used to authenticate API requests to Delta Exchange.
**In the code:** `hmac.new(api_secret, signature_data, sha256)` creates a signature that proves the request came from you.

---

## L

### Leverage
**What:** Borrowing power from the exchange to trade with more money than you have.
**Example:** 50× leverage means $10 of your money controls $500 worth of crypto.
**Risk:** Amplifies both profits AND losses. At 50×, a 2% move against you = 100% loss.
**Our setting:** Default 50× in `.env`

### Limit Order
**What:** An order that only executes at a specific price or better. Not used in this algo (we use market orders for immediate fills).

---

## M

### Market Order
**What:** An order that executes immediately at the best available price. Used for all entries and exits in this algo for guaranteed fills.

### Mark Price
**What:** The fair value of a contract calculated by the exchange, used for margin/liquidation calculations. May differ slightly from the last traded price.

### Margin
**What:** The collateral (your money) required to hold a leveraged position.
**Example:** At 50× leverage, you need $200 margin to hold a $10,000 position.

### Max Consecutive Losses
**What:** The longest streak of losing trades in a row. Important for psychological preparation.

---

## N

### Notional Value
**What:** The total value of a position. `Notional = margin × leverage`
**Example:** $5 margin × 50× leverage = $250 notional

---

## O

### OHLCV
**What:** Open, High, Low, Close, Volume — the five data points that define a price candle.

### Overbought
**What:** When RSI is above a threshold (78 in our algo), indicating the asset may have risen too fast and could pull back.
**Effect:** Prevents breakout entries when momentum is exhausted.

### Oversold
**What:** When RSI is below a threshold (22 in our algo), indicating the asset may have fallen too fast and could bounce.
**Effect:** Prevents short breakout entries when momentum is exhausted.

---

## P

### PnL (Profit and Loss)
**What:** The profit or loss on a trade.
**Long PnL:** `qty × (exit_price - entry_price)`
**Short PnL:** `qty × (entry_price - exit_price)`

### Peak Price
**What:** The best price reached since a trade was opened.
**Long:** Highest price since entry
**Short:** Lowest price since entry
**Used for:** Calculating trailing stop levels

### Perpetual Futures / Perps
**What:** Crypto derivative contracts that have no expiry date (unlike traditional futures). You can hold a long or short position indefinitely.
**Used by:** Delta Exchange (what this algo trades on)

### Poll / Polling Loop
**What:** The bot checks the market at regular intervals (every 60 seconds by default) instead of receiving real-time updates.

### Profit Factor
**What:** Ratio of gross profits to gross losses. Measures the quality of a strategy.
**Formula:** `sum(winning trades PnL) / abs(sum(losing trades PnL))`
**Good:** > 1.5 is considered good, > 2.0 is excellent

### Pullback
**What:** A temporary price movement against the prevailing trend. In an uptrend, a pullback is a short-term dip; in a downtrend, a short-term rally.
**In our algo:** The primary entry method — buying the dip to EMA21 in an uptrend, or selling the rally to EMA21 in a downtrend.

---

## R

### R-Multiple (R)
**What:** A standardized way to measure trade performance relative to the initial risk taken.
**Formula:** `R = (exit_price - entry_price) / initial_risk` for longs
**Example:** If you risk $100 (stop distance) and make $300, that's a 3R trade.
- 1R = you made exactly what you risked
- 0R = break-even
- -1R = you lost exactly what you risked
- 3R = you made 3× what you risked

### REST API
**What:** A web protocol used to communicate with exchanges. The bot sends HTTP requests (GET, POST, DELETE) to Delta Exchange endpoints.

### RSI (Relative Strength Index)
**What:** A momentum oscillator (0-100) that measures the speed and magnitude of recent price changes.
**How:** Compares average gains to average losses over the period (14).
**Levels:**
- Above 78 = overbought (algo blocks breakout longs)
- Below 22 = oversold (algo blocks breakout shorts)
- Around 50 = neutral

---

## S

### Sharpe Ratio
**What:** Risk-adjusted return metric. Higher = better return per unit of risk.
**Formula:** `(mean_daily_return / std_daily_return) × sqrt(365)`
**Good:** > 1.0 is good, > 2.0 is excellent

### Signal
**What:** A trade entry opportunity detected by the algo. Contains direction (long/short), type (pullback/breakout/fresh_trend), and price levels.

### Slippage
**What:** The difference between the expected trade price and the actual execution price. More common in volatile or illiquid markets.

### Sortino Ratio
**What:** Like Sharpe, but only penalizes downside volatility (not upside). Better for strategies with asymmetric returns.
**Formula:** `(mean_daily_return / downside_std) × sqrt(365)`

### Stop-Loss (SL)
**What:** A pre-set price level where the position is automatically closed to limit losses.
**Initial stop in our algo:** `entry_price ± 2.0 × ATR`

### Stop Market Order
**What:** An order that becomes a market order when a specific price (the stop price) is reached. Used for stop-losses.

### SuperTrend
**What:** A trend-following overlay indicator that plots a line above or below the price.
**When bullish (dir=1):** Line is below price, acts as dynamic support
**When bearish (dir=-1):** Line is above price, acts as dynamic resistance
**Parameters:** Period=10 (ATR lookback), Multiplier=3.0 (band width)
**Key events:**
- **Flip bull:** Direction changes from -1 to +1 (buy signal area)
- **Flip bear:** Direction changes from +1 to -1 (sell signal area)
- **Recent flip:** Flipped within the last 1-2 candles

### Symbol
**What:** The trading pair identifier.
**Formats used in this algo:**
- **Canonical (CCXT):** `BTC/USDT` — used internally
- **Delta:** `BTCUSD` — used for Delta Exchange API
- **Binance:** `BTC/USDT` — used for Binance data fallback

---

## T

### Telegram Notifier
**What:** A module that sends trading alerts to your Telegram account via a bot.
**Messages sent:**
- Bot started (with config)
- Signal detected (with full details)
- Order executed
- Position closed

### Timeframe
**What:** The duration of each candle. Our algo uses 4H (4-hour) candles.
**Why 4H:** Balances between catching meaningful trends and filtering out noise. Smaller timeframes (1H, 15M) have more noise; larger (1D) are too slow.

### Trailing Stop
**What:** A stop-loss that moves in the direction of your profit but never backward. "Locks in" gains as price moves favorably.
**Our implementation:** Multi-layered (percentage trail + R-multiple trail + SuperTrend floor)

### Trend
**What:** The overall direction of price movement over time.
**Uptrend (Bull):** Higher highs and higher lows
**Downtrend (Bear):** Lower highs and lower lows
**In our algo:** Trend = EMA21 > EMA55 AND SuperTrend = Bull

### True Range (TR)
**What:** The maximum of three values: High-Low, |High-PrevClose|, |Low-PrevClose|. Captures gaps and volatility better than simple high-low range.

---

## V

### Volatility
**What:** How much price fluctuates over time. Measured by ATR in our algo.
**High volatility:** Wider stops needed, larger position swings
**Low volatility:** Tighter stops, smaller swings

---

## W

### Webhook
**What:** A URL endpoint that receives data when an event occurs. Some platforms (AlgoLive, TradingView) use webhooks to trigger trades from external signals.

### Whipsaw
**What:** Rapid entry and exit of trades caused by noisy price action, resulting in multiple small losses. The cooldown period and trend filters exist to prevent this.

### Win Rate
**What:** The percentage of trades that were profitable.
**Formula:** `(winning trades / total trades) × 100`
**Our algo:** Typically 55-74% depending on market conditions.

---

## Special Terms in Code/Logs

| Term | Meaning |
|------|---------|
| `st_dir` | SuperTrend direction: 1 = bull, -1 = bear |
| `st_val` | SuperTrend value (support/resistance level) |
| `st_flip_bull` | SuperTrend just flipped to bullish |
| `st_recent_bull` | SuperTrend flipped bull in last 1-2 candles |
| `trend_bull` | All bull conditions met (EMA + ST) |
| `ema_fast_slope` | EMA21 is rising |
| `donchian_high` | 30-period highest high |
| `init_risk` | Initial stop distance in $ |
| `trail_stop` | Current trailing stop price |
| `peak_price` | Best price since entry |
| `r_now` | Current R-multiple of open trade |
| `pct_move` | How far price has moved from entry (%) |
| `DRY_RUN` | Paper trading mode (no real orders) |
| `SPLIT_BALANCE_MARGIN` | Divide equity equally across all symbols |
| `pos_size` | Number of exchange contracts |
| `contract_val` | Dollar value of 1 contract |

---

## Quick Reference: Common Log Messages

| Message | Meaning |
|---------|---------|
| `No signal on current closed 4H candle` | Algo checked but no entry conditions met |
| `Cooldown active: N bars since last exit` | Too soon after last trade, waiting |
| `Signal already processed for this candle` | Same signal was already acted on |
| `SIGNAL DETECTED: LONG pullback` | Entry opportunity found |
| `EXECUTING ENTRY` | Placing orders |
| `TRAILING STOP UPDATED` | Stop moved in your favor |
| `POSITION CLOSED trail_stop` | Exited via trailing stop |
| `POSITION CLOSED st_reversed` | Exited because SuperTrend reversed |
| `CONFLICTING TREND` | EMA and SuperTrend disagree (common cause of no signals) |

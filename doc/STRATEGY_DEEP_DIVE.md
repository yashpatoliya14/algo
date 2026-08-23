# 📘 Strategy Deep Dive — 4H Trend Rider (Complete Guide)

This document explains **every aspect** of the Trend Rider 4H strategy in complete detail, so you can replicate it on any platform (AlgoLive, TradingView, 3Commas, etc.).

---

## 📋 Table of Contents

1. [Strategy Philosophy](#1-strategy-philosophy)
2. [Indicators Used](#2-indicators-used)
3. [Trend Detection (When Does It Analyse?)](#3-trend-detection-when-does-it-analyse)
4. [Entry Signals (When Does It Take a Trade?)](#4-entry-signals-when-does-it-take-a-trade)
5. [Position Sizing (How Much Does It Risk?)](#5-position-sizing-how-much-does-it-risk)
6. [Exit & Trailing Stop System](#6-exit--trailing-stop-system)
7. [Cooldown Period](#7-cooldown-period)
8. [Complete Trading Cycle Flowchart](#8-complete-trading-cycle-flowchart)
9. [All Parameters Reference](#9-all-parameters-reference)
10. [Deploying on AlgoLive / Other Platforms](#10-deploying-on-algolive--other-platforms)

---

## 1. Strategy Philosophy

> **"Detect trend → Wait for clean signal → Enter with controlled risk → Trail stop to protect profits"**

The strategy is a **trend-following system** that:
- Only trades in the **direction of the confirmed trend**
- Waits for **high-probability entry points** (pullbacks, breakouts, or fresh trends)
- Never uses fixed take-profit targets — instead rides trends with **dynamic trailing stops**
- Uses multiple **filters** to avoid false signals in choppy/sideways markets

**Key Principle:** It's designed to be **patient** — it may go days without a trade, but when it enters, the odds are heavily in its favor.

---

## 2. Indicators Used

The strategy uses 6 technical indicators computed on **4-hour candles**:

### 2.1 EMA 21 (Fast Moving Average)
- **What:** Exponential Moving Average of close price, period = 21
- **Formula:** `EMA(close, 21)` — ewm(span=21, adjust=False)
- **Purpose:** Short-term trend direction and dynamic support/resistance level
- **Called:** `ema_fast` in code

### 2.2 EMA 55 (Slow Moving Average)
- **What:** Exponential Moving Average of close price, period = 55
- **Formula:** `EMA(close, 55)` — ewm(span=55, adjust=False)
- **Purpose:** Medium-term trend direction, used with EMA21 for crossover
- **Called:** `ema_slow` in code

### 2.3 EMA21 Slope
- **What:** Checks if EMA21 is rising or falling vs 3 bars (12 hours) ago
- **Bull slope:** `ema_fast > ema_fast.shift(3)` — EMA21 is higher than 12 hours ago
- **Bear slope:** `ema_fast < ema_fast.shift(3)` — EMA21 is lower than 12 hours ago
- **Purpose:** Prevents entries when the EMA is flat/against the trade direction

### 2.4 ATR (Average True Range) — Period 14
- **What:** Measures average volatility over the last 14 candles
- **Formula:** Exponential moving average of True Range (`alpha = 1/14`)
- **True Range = max(High-Low, |High-PrevClose|, |Low-PrevClose|)`
- **Purpose:** Sets stop-loss distance and trailing stop calculations
- **Called:** `atr` in code

### 2.5 RSI (Relative Strength Index) — Period 14
- **What:** Momentum oscillator measuring speed/change of price movements
- **Range:** 0 to 100
- **Overbought threshold:** 78 (default)
- **Oversold threshold:** 22 (default)
- **Purpose:** Filters breakout entries — prevents entering when momentum is exhausted
- **Called:** `rsi` in code

### 2.6 SuperTrend (Period 10, Multiplier 3.0)
- **What:** A trend-following overlay that plots above/below price
- **How it works:**
  - Calculates upper band = `HL2 + 3.0 × ATR(10)`
  - Calculates lower band = `HL2 - 3.0 × ATR(10)`
  - Direction flips BULL when close > previous upper band
  - Direction flips BEAR when close < previous lower band
- **Outputs:**
  - `st_dir` = 1 (bullish) or -1 (bearish)
  - `st_val` = the current support (bull) or resistance (bear) level
  - `st_flip_bull` = True on the candle where direction changes from -1 to +1
  - `st_flip_bear` = True on the candle where direction changes from +1 to -1
  - `st_recent_bull` = True if SuperTrend flipped bull in the last 1-2 candles
  - `st_recent_bear` = True if SuperTrend flipped bear in the last 1-2 candles

### 2.7 Donchian Channel (Period 30)
- **What:** Highest high and lowest low of the previous 30 candles (shifted by 1)
- **Donchian High:** `max(high) over last 30 bars (shifted 1 bar)`
- **Donchian Low:** `min(low) over last 30 bars (shifted 1 bar)`
- **Purpose:** Identifies breakout levels — a new high/low in the last 30 candles
- **Called:** `donchian_high` / `donchian_low` in code

---

## 3. Trend Detection (When Does It Analyse?)

The bot runs on a **polling loop** (default: every 60 seconds). On every cycle, for every tracked symbol, it:

### Step 1: Fetch Candle Data
- Fetches the last ~100 four-hour candles
- **Priority:** Delta Exchange API first, Binance as fallback
- Uses the **last completed candle** (not the currently forming one)

### Step 2: Compute All Indicators
Runs `compute_indicators()` which calculates all 6 indicators on the dataframe.

### Step 3: Determine Trend Alignment

The algo requires **dual confirmation** before even considering an entry:

#### BULLISH Trend (Long mode):
```
trend_bull = (EMA21 > EMA55) AND (SuperTrend direction = BULL)
```
PLUS: `ema_fast_slope = True` (EMA21 is rising vs 3 bars ago)

#### BEARISH Trend (Short mode):
```
trend_bear = (EMA21 < EMA55) AND (SuperTrend direction = BEAR)
```
PLUS: `ema_fast_slope_short = True` (EMA21 is falling vs 3 bars ago)

#### NO TREND (Do Nothing):
If EMA and SuperTrend **disagree** (e.g., EMA says bull but SuperTrend says bear), the algo does **nothing**. This is the most common reason for no signals in choppy markets.

---

## 4. Entry Signals (When Does It Take a Trade?)

Once the trend is confirmed, the algo checks for **3 types of entry signals**, in priority order:

### 4.1 PULLBACK Entry (Highest Priority)

**LONG Pullback:**
```
ALL of these must be true on the LAST COMPLETED 4H candle:
1. Previous candle's low <= EMA21 × 1.003   (price dipped near the moving average)
2. Current candle close > EMA21              (price bounced back above the MA)
3. Current candle close > current open       (bullish/green candle — shows buying pressure)
```

**SHORT Pullback:**
```
ALL of these must be true:
1. Previous candle's high >= EMA21 × 0.997   (price rose near the moving average)
2. Current candle close < EMA21              (price rejected back below the MA)
3. Current candle close < current open       (bearish/red candle — shows selling pressure)
```

**Why this works:** In a trending market, price often "pulls back" to the 21 EMA before continuing. This is the highest-probability entry because you're buying support (or selling resistance) in a confirmed trend.

### 4.2 BREAKOUT Entry (Second Priority)

**LONG Breakout:**
```
ALL of these must be true:
1. Current candle close > Donchian High (30-period)   (new 30-candle high = 5-day high)
2. RSI < 78                                           (not overbought — has room to run)
```

**SHORT Breakout:**
```
ALL of these must be true:
1. Current candle close < Donchian Low (30-period)    (new 30-candle low = 5-day low)
2. RSI > 22                                           (not oversold — has room to drop)
```

**Why this works:** Breaking a multi-day high/low in a confirmed trend signals strong momentum continuation. The RSI filter prevents chasing exhausted moves.

### 4.3 FRESH TREND Entry (Third Priority)

**LONG Fresh Trend:**
```
ALL of these must be true:
1. SuperTrend recently flipped to BULL   (flipped in this candle or the previous one)
2. Current candle close > EMA21          (price is above the fast moving average)
```

**SHORT Fresh Trend:**
```
ALL of these must be true:
1. SuperTrend recently flipped to BEAR   (flipped in this candle or the previous one)
2. Current candle close < EMA21          (price is below the fast moving average)
```

**Why this works:** A SuperTrend flip represents a significant trend change. Getting in early after a confirmed flip (with EMA alignment) catches the start of new trends.

### Entry Priority Flow

```
IF trend is confirmed (EMA + SuperTrend + Slope aligned):
    IF pullback conditions met → ENTER (pullback)
    ELSE IF breakout conditions met → ENTER (breakout)
    ELSE IF fresh_trend conditions met → ENTER (fresh_trend)
    ELSE → No signal, wait for next candle
ELSE:
    → No signal possible, trend not aligned
```

---

## 5. Position Sizing (How Much Does It Risk?)

The bot offers 3 sizing modes configured via `.env`:

### Mode 1: Split Balance (Default — `SPLIT_BALANCE_MARGIN=true`)
```
margin_per_coin = total_equity / number_of_symbols
notional = margin_per_coin × leverage
contracts = notional / (current_price × contract_value)
```
Example: $100 equity, 6 symbols, 50× leverage
→ $100 / 6 = $16.67 per symbol → $16.67 × 50 = $833.33 notional per trade

### Mode 2: Fixed Margin (`FIXED_MARGIN_USD > 0`)
```
notional = fixed_margin_usd × leverage
contracts = notional / (current_price × contract_value)
```
Example: $5 fixed margin, 50× leverage → $250 notional

### Mode 3: Risk-Based (`FIXED_MARGIN_USD=0` and `SPLIT_BALANCE_MARGIN=false`)
```
risk_amount = equity × (risk_pct / 100)
contracts = risk_amount / stop_distance
```
This sizes the trade so that if the stop-loss is hit, the loss equals exactly `risk_pct` of equity.

---

## 6. Exit & Trailing Stop System

The exit system has **multiple layers** that work together. This is the most sophisticated part of the strategy.

### 6.1 Initial Stop Loss
```
LONG:  stop = entry_price - (2.0 × ATR)
SHORT: stop = entry_price + (2.0 × ATR)
```
This is the initial "catastrophic" stop. It's always placed as a stop-market order on the exchange.

### 6.2 Percentage Trailing Stop
```
Activation: When price moves 1.0% in profit from entry
Trail Distance: 0.4% behind peak price

LONG:
  peak_price = highest price seen since entry
  pct_move = (peak_price - entry) / entry × 100
  IF pct_move >= 1.0%:
      pct_stop = peak_price × (1 - 0.4/100)
      trail = max(trail, pct_stop)

SHORT:
  peak_price = lowest price seen since entry (best price)
  pct_move = (entry - peak_price) / entry × 100
  IF pct_move >= 1.0%:
      pct_stop = peak_price × (1 + 0.4/100)
      trail = min(trail, pct_stop)
```

### 6.3 R-Multiple Phased Trailing

R-multiple = how many times the initial risk the trade has moved in your favor.

```
R = (current_close - entry_price) / initial_risk   [for longs]
R = (entry_price - current_close) / initial_risk   [for shorts]
```

**Phase 1: Break-Even (1R ≤ R < 2R)**
```
Move stop to entry + 0.2 × ATR   (slightly above break-even for longs)
```

**Phase 2: Chandelier 2.5× (2R ≤ R < 4R)**
```
LONG:  trail = peak_price - 2.5 × ATR
SHORT: trail = peak_price + 2.5 × ATR
```

**Phase 3: Tight Chandelier 1.8× (R ≥ 4R)**
```
LONG:  trail = peak_price - 1.8 × ATR
SHORT: trail = peak_price + 1.8 × ATR
```

### 6.4 SuperTrend Value as Trail Floor/Ceiling
```
LONG:  IF SuperTrend value > current trail → trail = SuperTrend value
SHORT: IF SuperTrend value < current trail → trail = SuperTrend value
```
The SuperTrend level acts as an additional safety net — the trail can never be worse than the SuperTrend level.

### 6.5 Exit Triggers

The position is closed when **either** condition is met:

1. **Trail Stop Hit:** Current price ≤ trail_stop (long) or ≥ trail_stop (short)
2. **SuperTrend Reversal:** SuperTrend direction flips against the position (BULL→BEAR for longs, BEAR→BULL for shorts)

```
Exit price:
  - If trail stop hit → exit at trail_stop price
  - If SuperTrend reversed → exit at current market price
```

### 6.6 Trail Stop Priority (All Layers Combined)

The trail stop is the **maximum** (for longs) or **minimum** (for shorts) of all trail values. Each layer can only move the stop in a favorable direction — it never goes backward:

```
trail = max(
    initial_stop,
    percentage_trail,         // 1% activation, 0.4% distance
    r_multiple_trail,         // BE → Chandelier 2.5 → Chandelier 1.8
    supertrend_value_trail    // SuperTrend support level
)
```

---

## 7. Cooldown Period

After a position is closed (either by trail stop or SuperTrend reversal), the algo enforces a **3-candle cooldown** before entering a new trade on the same symbol.

```
cooldown_bars = 3   (= 12 hours on 4H timeframe)
```

This prevents whipsawing — entering and exiting rapidly in choppy conditions.

Additionally, there's a **duplicate signal guard**: the same signal type on the same candle for the same symbol is only processed once.

---

## 8. Complete Trading Cycle Flowchart

```
Every 60 seconds, for each symbol:
│
├─ 1. FETCH DATA: Get last 100 4H candles (Delta → Binance fallback)
│
├─ 2. COMPUTE INDICATORS: EMA21, EMA55, ATR, RSI, SuperTrend, Donchian
│
├─ 3. CHECK EXISTING POSITION
│   ├─ IF position open → Run trail management (§6)
│   │   ├─ Update peak price
│   │   ├─ Calculate R-multiple
│   │   ├─ Update trail from % trail, R-multiple trail, SuperTrend floor
│   │   ├─ Check exit conditions
│   │   └─ IF exit → Close position, record cooldown time
│   │
│   └─ IF no position → Continue to entry check
│
├─ 4. COOLDOWN CHECK
│   └─ IF less than 3 candles since last exit → Skip (wait)
│
├─ 5. DUPLICATE SIGNAL GUARD
│   └─ IF same signal already processed this candle → Skip
│
├─ 6. TREND CHECK
│   ├─ Bull: EMA21 > EMA55 AND SuperTrend = BULL AND EMA21 rising
│   ├─ Bear: EMA21 < EMA55 AND SuperTrend = BEAR AND EMA21 falling
│   └─ Neither: → No signal possible
│
├─ 7. ENTRY SIGNAL CHECK (if trend confirmed)
│   ├─ Check Pullback → if yes, signal = pullback
│   ├─ Check Breakout → if yes, signal = breakout
│   └─ Check Fresh Trend → if yes, signal = fresh_trend
│
├─ 8. EXECUTE ENTRY (if signal found)
│   ├─ Calculate stop distance (2 × ATR)
│   ├─ Calculate position size
│   ├─ Place market order + stop-loss order
│   └─ Send Telegram notification
│
└─ 9. WAIT for next poll cycle (60 seconds)
```

---

## 9. All Parameters Reference

| Parameter | Default | Location | Description |
|-----------|---------|----------|-------------|
| `ema_fast` | 21 | TrendRiderParams | Fast EMA period |
| `ema_slow` | 55 | TrendRiderParams | Slow EMA period |
| `st_period` | 10 | TrendRiderParams | SuperTrend ATR period |
| `st_mult` | 3.0 | TrendRiderParams | SuperTrend multiplier |
| `atr_period` | 14 | TrendRiderParams | ATR period for volatility |
| `rsi_period` | 14 | TrendRiderParams | RSI period |
| `rsi_ob` | 78 | TrendRiderParams | RSI overbought threshold (breakout filter) |
| `rsi_os` | 22 | TrendRiderParams | RSI oversold threshold (breakout filter) |
| `donchian_period` | 30 | TrendRiderParams | Donchian channel lookback |
| `stop_atr_mult` | 2.0 | TrendRiderParams | Initial stop = entry ± N × ATR |
| `trail_be_buffer` | 0.2 | TrendRiderParams | Break-even buffer (× ATR) at 1R |
| `trail_phase2_mult` | 2.5 | TrendRiderParams | Chandelier multiplier at 2R-4R |
| `trail_phase3_mult` | 1.8 | TrendRiderParams | Chandelier multiplier at 4R+ |
| `trail_pct_activation` | 1.0% | TrendRiderParams / .env | Trailing stop activation threshold |
| `trail_pct_distance` | 0.4% | TrendRiderParams / .env | Trail distance behind peak |
| `risk_pct` | 1.5% | TrendRiderParams / .env | Risk per trade (% of equity) |
| `cooldown_bars` | 3 | TrendRiderParams | Bars to wait after exit before re-entry |
| `LEVERAGE` | 50 | .env | Position leverage |
| `FIXED_MARGIN_USD` | 5 | .env | Fixed margin per trade ($) |
| `POLL_INTERVAL_SEC` | 60 | .env | Seconds between checks |
| `TIMEFRAME` | 4h | .env | Candle timeframe |

---

## 10. Deploying on AlgoLive / Other Platforms

### What You Need to Replicate

To rebuild this strategy on another platform, you need:

1. **Data Source:** 4H OHLCV candles for your symbols
2. **Indicators to compute:**
   - EMA(21) and EMA(55) of close
   - EMA slope: `EMA21 > EMA21[3 bars ago]`
   - ATR(14) using exponential smoothing
   - RSI(14)
   - SuperTrend(10, 3.0)
   - Donchian Channel(30) with 1-bar shift
3. **Entry logic:** Exactly as described in §4
4. **Exit logic:** Exactly as described in §6
5. **Cooldown:** 3-bar gap between trades

### Platform-Specific Notes

**TradingView / Pine Script:**
- All indicators are available as built-in functions
- Use `strategy.entry()` and `strategy.exit()` for orders
- SuperTrend is available as `ta.supertrend()`
- Donchian is `ta.highest(high, 30)[1]` and `ta.lowest(low, 30)[1]`

**AlgoLive:**
- Implement as a webhook strategy
- Use the Telegram signal format this bot already sends
- Map signal types (pullback/breakout/fresh_trend) to entry actions
- The trailing stop logic will need to be implemented in AlgoLive's trail system

**3Commas / Cornix:**
- Send signals via Telegram → Bot reads and executes
- Current Telegram messages already contain: direction, entry, stop, size
- Configure trail stop as 1% activation, 0.4% distance

### Signal Message Format (For Webhook/Telegram)

The bot already sends signals in this format:
```
Signal
Symbol: BTC/USDT
Direction: LONG
Type: pullback
Candle Time: 2026-08-19 12:00 UTC
Signal Price: 77222.00
Suggested Entry: 77222.00
Size: 5
Stop Loss: 74473.92
Risk %: 1.5%
Trail: activate after +1.00% move, then trail 0.40% behind peak
TP / Exit Plan: No fixed TP; exit on trailing stop or trend reversal
```

You can use this signal directly as webhook input for most platforms.

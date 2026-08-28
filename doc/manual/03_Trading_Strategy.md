# 03: Trading Strategy

This document details the exact mathematical rules governing the 4H Crypto Trend Rider.

> **Core Philosophy:** "Detect trend → Wait for clean signal → Enter with controlled risk → Trail stop to protect profits"

## 1. Technical Indicators
All calculations are performed on **4-Hour (4H)** candles.

* **EMA 21 (Fast):** Short-term trend direction and dynamic support/resistance.
* **EMA 55 (Slow):** Medium-term trend direction.
* **EMA21 Slope:** Checks if EMA21 is rising or falling compared to 3 bars ago to avoid flat markets.
* **ATR (14):** Average True Range. Measures volatility to dictate stop-loss distance.
* **RSI (14):** Momentum filter to prevent buying into overbought breakouts.
* **SuperTrend (10, 3.0):** An ATR-band overlay that provides strict Bull/Bear regime confirmation.
* **Donchian Channel (30):** Highlights 30-candle highs and lows for breakout entries.

## 2. Trend Alignment (The Gatekeeper)
Before any trade is considered, the system must confirm a clear trend.

**BULLISH Regime (Longs Allowed):**
1. EMA21 > EMA55
2. SuperTrend is BULL
3. EMA21 is higher than it was 3 candles ago (rising slope).

**BEARISH Regime (Shorts Allowed):**
1. EMA21 < EMA55
2. SuperTrend is BEAR
3. EMA21 is lower than it was 3 candles ago (falling slope).

*If EMA and SuperTrend disagree, the market is considered choppy, and NO trades are taken.*

## 3. Entry Signals
If the trend is aligned, the algorithm checks for three specific entry triggers (in priority order).

### Priority 1: Pullback
Entering on a dip to the moving average within a trend.
* **Long:** Previous candle dipped near/below EMA21. Current candle is green and closed above EMA21.
* **Short:** Previous candle rallied near/above EMA21. Current candle is red and closed below EMA21.

### Priority 2: Breakout
Entering when price breaks a multi-day high/low.
* **Long:** Close > 30-period Donchian High, AND RSI < 78 (not completely overbought).
* **Short:** Close < 30-period Donchian Low, AND RSI > 22 (not completely oversold).

### Priority 3: Fresh Trend
Catching a trend right as it starts.
* **Long:** SuperTrend flipped BULL in the last 2 candles, AND close > EMA21.
* **Short:** SuperTrend flipped BEAR in the last 2 candles, AND close < EMA21.

## 4. Exit & Trailing Stop System
The system does *not* use fixed take-profit targets. Instead, it uses a multi-layered trailing stop to let winners run.

### Layer 1: Initial Stop
Placed immediately upon entry based on volatility.
* **Stop Distance:** 2.0 × ATR away from entry price.

### Layer 2: Break-Even Buffer
When the trade moves 1R (1 × initial risk) in profit:
* Move stop to Entry Price + (0.2 × ATR) to guarantee a small profit.

### Layer 3: Chandelier R-Multiple Trail
As the trade becomes massively profitable, the stop tightens to protect gains.
* **2R to 4R Profit:** Stop trails at Peak Price - (2.5 × ATR).
* **> 4R Profit:** Stop tightens further to Peak Price - (1.8 × ATR).

### Layer 4: Percentage Trail (Micro-Management)
Activates when the price moves 1.0% in profit.
* Trails tightly at 0.4% behind the peak price.

### Layer 5: SuperTrend Floor
The trail stop will never be lower (for longs) than the current SuperTrend value. If SuperTrend flips against the position, the trade is exited immediately at market.

*Note: The actual stop used on the exchange is the maximum/tightest value of all the layers above.*

## 5. Cooldown Guard
After any trade is closed, the bot enforces a strict **3-candle (12 hour) cooldown** on that symbol to prevent whipsawing in sudden choppy conditions.

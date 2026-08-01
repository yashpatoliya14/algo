# Institutional-Grade Crypto Trend-Following Algorithm
### 4H Trend / 1H Confirmation — BTC, ETH, SOL Futures — Fully Rule-Based

---

## 1. Strategy Overview

A multi-timeframe trend-following system. The 4H EMA9/EMA20 crossover defines *trade direction*, a 1H RSI momentum filter defines *timing*, and a stack of trend/volatility/structure filters decides whether the signal is worth taking at all. Risk is controlled by an adaptive (not fixed) stop, and profit is captured through a hybrid trailing + partial-exit system rather than one static target.

Design philosophy: **the crossover is the trigger, not the edge.** The edge comes from filtering out the ~70% of crossovers that happen in chop, exhaustion, or against the higher-timeframe trend. This is a low-frequency, high-quality swing system — expect roughly 2-6 qualifying trades per asset per month.

---

## 2. Indicators Used (and why each earns its place)

| Indicator | Timeframe | Role |
|---|---|---|
| EMA 9 / EMA 20 | 4H | Entry trigger (crossover) |
| EMA 200 | 4H | Macro trend filter — only trade with it |
| RSI (14) | 1H | Momentum confirmation, tuned via slope not level |
| ADX (14) | 4H | Trend strength gate — rejects chop |
| ATR (14) | 4H | Volatility measurement for stops/sizing |
| Supertrend (10, 3) | 4H | Secondary trend-direction confirmation + trailing stop input |
| Choppiness Index (14) | 4H | Sideways-market filter, catches what ADX misses |
| Volume MA (20) | 4H | Confirms crossover isn't happening on dead volume |

Deliberately excluded: VWAP (better suited to intraday/session-based markets, less meaningful on 4H swing crypto which trades 24/7 with no clean session anchor), Bollinger/Keltner squeeze (Choppiness Index + ATR already capture this with less redundancy), Donchian (redundant with swing-structure stop logic in Section 6).

---

## 3. Entry Rules

**Long setup (mirror for short):**

1. 4H EMA9 crosses above EMA20 (the trigger candle, call it candle `C0`)
2. Price at `C0` close is above 4H EMA200 (macro trend agreement)
3. 4H ADX(14) ≥ 20 **and** rising over the last 3 candles (trend has strength and is building, not fading)
4. 4H Choppiness Index ≤ 55 (market not in a range-bound regime)
5. 4H Supertrend(10,3) is in bullish state at `C0`
6. 4H volume on `C0` ≥ 1.2 × 20-period volume MA (participation confirms the move)
7. 1H RSI momentum condition is met (Section 5) within 3 completed 1H candles after `C0` closes
8. `C0` is not an exhaustion candle (Section 8, rule 4)

All 8 conditions must be true. This is intentionally strict — a filtered system that skips 80% of raw crossovers is the point.

---

## 4. Trend Filters

- **EMA 200 (4H):** the macro regime filter. Trading only in the direction of EMA200 removes the majority of counter-trend crossover failures — this is the single highest-value filter in the system.
- **ADX rising, not just high:** a high-but-falling ADX means the trend is already maturing/decelerating — a late entry. Requiring it to rise over 3 candles biases entries toward the *acceleration* phase of a trend.
- **Supertrend direction:** acts as a second vote using a different calculation method (ATR-band based rather than EMA-based). When EMA and Supertrend disagree, it's usually a transitional/choppy period — hence requiring agreement.
- HH/HL structure was considered but deliberately omitted as a hard gate — it's largely captured by Supertrend + ADX and adding it raises the false-negative rate (misses valid trends during a shallow pullback) more than it improves precision.

---

## 5. Momentum Filters (1H RSI)

Rather than static "RSI > 50," use **RSI slope + zone re-entry confirmation**:

- Compute RSI(14) on 1H.
- **Long confirmation:** RSI must cross back above 40 from below (a pullback-and-resume pattern) OR be rising for 3 consecutive 1H candles while staying above 45 — whichever occurs first within the 3-candle confirmation window.
- **Reject if** RSI is already above 70 at the time of confirmation — this is the overbought-entry guard the base prompt specifically asked for. An entry chasing an overbought RSI has a materially worse risk-reward profile even in strong trends.
- **Short is the mirror:** cross back below 60 from above, OR falling for 3 candles while below 55; reject if RSI already below 30.

Why slope over level: a static "RSI>50" fires on every minor uptick and gives no information about whether momentum is *building*. Slope + zone re-entry specifically targets the "pullback within a trend has just ended" moment, which historically has better forward expectancy than a raw threshold cross.

---

## 6. Smart Stop-Loss Engine (adaptive, no fixed distance)

Decision tree evaluated at entry, long example:

```
candle_range = C0.high - C0.low
atr = ATR(14, 4H)

IF candle_range > 1.8 * atr:
    # entry candle is abnormally large — using its full range = poor R:R
    stop = entry_price - (1.3 * atr)          # cap risk to volatility-normalized distance
ELSE:
    swing_low = lowest low of last 5 candles (excluding C0)
    structural_stop = swing_low - (0.2 * atr)  # small buffer past structure
    atr_stop = entry_price - (1.5 * atr)

    # use whichever is TIGHTER, but never tighter than 0.8*ATR (avoid noise stop-outs)
    stop = max(structural_stop, atr_stop)
    IF (entry_price - stop) < 0.8 * atr:
        stop = entry_price - 0.8 * atr
```

Logic explained:
- **Oversized entry candle → ATR cap.** This directly solves the exact failure mode called out in the brief: a huge trigger candle shouldn't dictate a huge stop.
- **Normal candle → tighter of structure vs. ATR.** Structure (last swing low) respects the market's own logic; ATR caps it so a single quiet-then-random wick doesn't blow the risk budget.
- **Floor at 0.8×ATR** prevents the stop from being so tight that normal volatility noise triggers it prematurely.

This single decision tree adapts automatically across low-vol (BTC in a range) and high-vol (news-driven altcoin spikes) regimes because everything is ATR-relative, not fixed in dollar/percent terms.

---

## 7. Trailing Stop Engine (hybrid, tightens with profit)

Three-phase hybrid, long example:

**Phase 1 — Pre-1R (open risk):** no trailing. Stop stays at the initial smart stop from Section 6. Moving it early just adds noise-driven stop-outs before the trade has proven itself.

**Phase 2 — 1R to 2R achieved:** move stop to breakeven + 0.1×ATR (locks in a small buffer past entry, removes downside risk entirely).

**Phase 3 — Beyond 2R:** switch to a **Chandelier-style ATR trail**:
```
trail_stop = highest_high_since_entry - (2.5 * ATR)
```
Recalculated every new 4H candle; the stop only ever moves up (long) / down (short), never back toward entry.

**Phase 4 — Beyond 4R:** tighten the multiplier from 2.5×ATR to 1.8×ATR, and additionally trail behind Supertrend(10,3) if Supertrend is tighter than the ATR chandelier level on that candle — whichever is closer to price wins, giving strong trends room early and locking in gains aggressively once the move is extended.

This satisfies the brief's requirement directly: wide room while unproven, and progressively tighter as profit accumulates, without capping upside in a strong trend (no fixed target overrides the trail once Phase 3 begins).

---

## 8. Exit Rules

Exit if **any** of the following triggers:

1. **Trailing stop hit** (Section 7) — primary exit mechanism for winners.
2. **Initial stop hit** (Section 6) — primary exit mechanism for losers.
3. **Reverse EMA9/20 crossover on 4H** — the original trend thesis is invalidated; exit remaining position regardless of trail level.
4. **Exhaustion candle at/near target zone:** a 4H candle with range > 2.5×ATR closing in the bottom (long) or top (short) third of its own range, occurring after ≥2R profit — this is a blow-off-top pattern; exit 100% remaining.
5. **Momentum deterioration:** 1H RSI makes a lower high while price makes a higher high (bearish divergence for longs, mirrored for shorts) while position is ≥1.5R in profit — take partial or full profit.
6. **Choppiness Index crosses back above 60** while in profit — the trend regime that justified the trade has broken down structurally, independent of price hitting the trail.

**Partial profit taking (hybrid approach — chosen over pure fixed-R or pure trailing):**
- Close 40% of position at 1.5R — de-risks the trade and locks partial profit; this material because raw win rate on the untouched crossover is only moderate, so banking something early materially improves expectancy consistency.
- Close another 30% at 3R.
- Trail the final 30% using the Section 7 engine with no cap — this is the piece designed to catch outsized trend moves.

A pure fixed 1:3 exit was rejected because it caps the tail (where most of a trend-following system's total expectancy actually comes from). A pure trailing-only exit was rejected because it gives back too much on the more common "trend runs 1.5-2R then reverses" case. The 40/30/30 split is a reasonable starting point — treat 30-50% as the tunable range for the first tranche depending on backtested win-rate distribution per asset.

---

## 9. False Signal Protection

| Filter | Blocks | Why |
|---|---|---|
| Choppiness Index ≤ 55 at entry | Sideways/ranging markets | Chop index directly measures range-bound vs trending price action; EMA crossovers in chop are essentially coin-flips |
| ADX ≥ 20 and rising | Low conviction trends | Weak/flat ADX means the crossover has no underlying strength behind it |
| Volume ≥ 1.2× MA | Fake breakouts | A crossover on thin volume is more likely to fail/reverse — real participation is required |
| Exhaustion candle check (>2.5×ATR range, closing against the move, after extension) | Late/exhaustion entries | Entering right as a move is climaxing has structurally worse forward returns |
| Max distance from EMA200 (< 3×ATR) | Extremely overextended trends | Entering a trend already stretched far from its mean has poor reward relative to reversion risk |
| No entry within 2 candles of a known high-impact macro/news event (CPI, FOMC, major exchange outage) | News-driven spikes | Volatility here is event-driven, not technical — indicator behavior is unreliable in this window |

---

## 10. Risk Management

- **Risk per trade:** 0.5%–1% of account equity (start at the low end; this is a swing system with wider stops than scalping, so % risk per trade should stay modest even though R:R is favorable).
- **Position sizing:** `position_size = (account_equity * risk_%) / (entry_price - stop_price)` — fully volatility-adjusted since the stop distance itself is ATR-derived.
- **Daily loss limit:** stop taking new entries for 24h after cumulative daily loss reaches 2.5% of equity.
- **Max consecutive losses:** after 3 consecutive stopped-out trades, cut position size by 50% until a winning trade resets it.
- **Max concurrent exposure:** no more than 3 open positions at once; no more than 2 positions in directionally-correlated assets (e.g., long BTC + long ETH simultaneously counts as correlated exposure, size accordingly).
- **Drawdown-based de-risking:** if account drawdown from equity high exceeds 8%, cut risk-per-trade in half; at 15% drawdown, pause the system entirely and require manual review before resuming.
- **Max total portfolio heat:** sum of all open positions' risk-to-stop should never exceed 3% of equity at any time.

---

## 11. Trade Management Flow

```
1. New 4H candle closes
2. Check EMA9/EMA20 for crossover → if none, wait
3. If crossover: check EMA200 side, ADX level+slope, Choppiness, Supertrend, Volume
   → any fail = discard signal, no trade
4. If all pass: watch 1H RSI for confirmation, up to 3x 1H candles
   → no confirmation in window = signal expires, no trade
5. If confirmed: check for exhaustion candle / overextension from EMA200
   → fail = discard
6. Calculate adaptive stop (Section 6), size position (Section 10)
7. Enter trade
8. Monitor each new 1H/4H candle for:
   a. Initial stop hit → exit, log result
   b. 1.5R reached → close 40%, move remaining stop logic to Phase 2 rules
   c. 3R reached → close another 30%
   d. Beyond 2R → engage chandelier trail on remainder
   e. Any hard exit condition (Section 8) → close relevant portion immediately
9. Position fully closed → log trade (entry, exit, R-multiple, exit reason) for review
10. Return to step 1
```

---

## 12. Complete Pseudocode

```python
def check_entry(candles_4h, candles_1h, direction):
    c0 = candles_4h[-1]
    ema9, ema20, ema200 = ema(candles_4h, 9), ema(candles_4h, 20), ema(candles_4h, 200)
    atr4h = atr(candles_4h, 14)
    adx4h = adx(candles_4h, 14)
    chop = choppiness_index(candles_4h, 14)
    st = supertrend(candles_4h, 10, 3)
    vol_ma = sma(volumes(candles_4h), 20)

    crossed = crossover(ema9, ema20, direction)
    if not crossed:
        return None

    trend_ok = (c0.close > ema200[-1]) if direction == "long" else (c0.close < ema200[-1])
    adx_ok = adx4h[-1] >= 20 and adx4h[-1] > adx4h[-4]
    chop_ok = chop[-1] <= 55
    st_ok = st.direction == direction
    vol_ok = c0.volume >= 1.2 * vol_ma[-1]
    dist_from_ema200 = abs(c0.close - ema200[-1]) / atr4h[-1]
    not_overextended = dist_from_ema200 < 3.0
    not_exhaustion = not is_exhaustion_candle(c0, atr4h[-1], direction)

    if not all([trend_ok, adx_ok, chop_ok, st_ok, vol_ok, not_overextended, not_exhaustion]):
        return None

    if wait_for_rsi_confirmation(candles_1h, direction, max_candles=3):
        return build_signal(c0, direction)
    return None


def calculate_stop(c0, candles_4h, atr4h, direction):
    candle_range = c0.high - c0.low
    sign = 1 if direction == "long" else -1

    if candle_range > 1.8 * atr4h:
        stop = c0.close - sign * 1.3 * atr4h
    else:
        swing = swing_low(candles_4h[-6:-1]) if direction == "long" else swing_high(candles_4h[-6:-1])
        structural_stop = swing - sign * 0.2 * atr4h
        atr_stop = c0.close - sign * 1.5 * atr4h
        stop = max(structural_stop, atr_stop) if direction == "long" else min(structural_stop, atr_stop)
        min_dist = 0.8 * atr4h
        if abs(c0.close - stop) < min_dist:
            stop = c0.close - sign * min_dist
    return stop


def manage_position(position, candles_4h, candles_1h, atr4h):
    r = current_r_multiple(position)

    if r >= 1.5 and not position.partial1_taken:
        close_position(position, pct=0.40)
        position.partial1_taken = True

    if r >= 3.0 and not position.partial2_taken:
        close_position(position, pct=0.30)
        position.partial2_taken = True

    if r >= 2.0:
        multiplier = 1.8 if r >= 4.0 else 2.5
        chandelier = highest_high_since_entry(position) - multiplier * atr4h[-1]
        st_level = supertrend(candles_4h, 10, 3).value
        new_trail = max(chandelier, st_level) if position.direction == "long" else min(chandelier, st_level)
        position.stop = max(position.stop, new_trail) if position.direction == "long" else min(position.stop, new_trail)
    elif r >= 1.0:
        position.stop = position.entry + 0.1 * atr4h[-1]  # breakeven buffer

    if hard_exit_triggered(position, candles_4h, candles_1h):
        close_position(position, pct=1.0)

    return position
```

---

## 13. Flowchart

```
                    ┌─────────────────────┐
                    │  New 4H candle close │
                    └──────────┬───────────┘
                               ▼
                  ┌─────────────────────────┐
                  │ EMA9/EMA20 crossover?    │──No──► wait
                  └──────────┬───────────────┘
                             │Yes
                             ▼
        ┌────────────────────────────────────────┐
        │ Trend/strength/vol/chop/ST filters pass?│──No──► discard signal
        └──────────────┬───────────────────────────┘
                        │Yes
                        ▼
        ┌────────────────────────────────────────┐
        │ 1H RSI confirms within 3 candles?       │──No──► signal expires
        └──────────────┬───────────────────────────┘
                        │Yes
                        ▼
        ┌────────────────────────────────────────┐
        │ Exhaustion / overextension check clean? │──No──► discard
        └──────────────┬───────────────────────────┘
                        │Yes
                        ▼
              ┌────────────────────┐
              │ Compute adaptive    │
              │ stop + position size│
              └─────────┬───────────┘
                        ▼
                 ┌─────────────┐
                 │ ENTER TRADE  │
                 └──────┬───────┘
                        ▼
        ┌───────────────────────────────┐
        │ Monitor each candle:           │
        │ - Stop hit → exit               │
        │ - 1.5R → partial 40%            │
        │ - 3R → partial 30%              │
        │ - >2R → chandelier trail engaged│
        │ - Hard exit trigger → close     │
        └───────────────┬─────────────────┘
                        ▼
                 ┌─────────────┐
                 │ Log & repeat │
                 └─────────────┘
```

---

## 14. Recommended Parameter Ranges

| Parameter | Suggested Range | Notes |
|---|---|---|
| EMA fast/slow | 9/20 (fixed per spec) | Could test 8/21, 10/22 in optimization but keep close to spec |
| EMA macro filter | 150–250 | 200 is standard; shorter reacts faster but noisier |
| RSI period | 12–16 | 14 is standard, minimal edge from deviating |
| RSI long re-entry zone | 35–45 | Lower = more permissive/earlier, higher = more conservative |
| ADX threshold | 18–25 | Lower admits more (weaker) trends; test per-asset |
| ADX rising lookback | 2–4 candles | Shorter = more sensitive to short accel bursts |
| Choppiness threshold | 50–60 | Lower = stricter chop rejection |
| Initial stop ATR multiplier (normal candle) | 1.2–1.8× | Wider on higher-vol assets (SOL) vs BTC |
| Oversized-candle cap multiplier | 1.1–1.5× | Keep tighter than normal-case ATR mult |
| Min stop floor | 0.6–1.0× ATR | Prevents noise stop-outs on very tight setups |
| Chandelier trail multiplier (2R–4R) | 2.0–3.0× | Wider on SOL/altcoins, tighter on BTC |
| Chandelier trail multiplier (>4R) | 1.5–2.0× | Locks in extended winners |
| Partial 1 trigger / size | 1.2R–1.8R / 30–50% | Backtest per-asset win-rate distribution to tune |
| Partial 2 trigger / size | 2.5R–3.5R / 20–35% | |
| Risk per trade | 0.5–1.0% | Lower for altcoins given fatter tails |
| Daily loss limit | 2–3% | |
| Max drawdown de-risk trigger | 6–10% | |

Wider parameter ranges are appropriate for SOL/altcoins given fatter volatility tails; tighter ranges suit BTC given its comparatively lower realized vol.

---

## 15. Advantages

- Multi-layer confirmation substantially reduces false-signal rate vs. a raw crossover.
- Fully volatility-adjusted stop and trail — same logic scales sensibly from BTC to a much more volatile altcoin without manual re-tuning of dollar/percent stops.
- Partial-exit structure balances consistency (locks in early profit) with expectancy (lets a piece run for outsized trend moves).
- Every rule is objective and backtestable/automatable — no discretionary judgment calls.
- Drawdown-aware risk sizing reduces the chance of a bad streak compounding into account-threatening losses.

---

## 16. Weaknesses

- Low trade frequency (heavy filtering) means slower statistical validation — needs a long backtest window (multiple market cycles) to get a reliable sample size.
- Multiple simultaneous filter conditions increase curve-fitting risk during parameter optimization — walk-forward testing is essential, not optional.
- In a strongly trending, low-chop, sustained bull/bear market, the extra filters may cause some late entries relative to a pure crossover (opportunity cost of the caution).
- ATR-based stops can still be whipsawed during sudden volatility regime shifts (e.g., a flash crash) faster than the system reprices — no protection against true tail/gap risk beyond position sizing.
- Requires reliable, low-latency 1H and 4H data feeds; confirmation-window logic (waiting up to 3× 1H candles) adds implementation complexity vs. a single-timeframe system.

---

## 17. Market Conditions Where the Strategy Performs Best

- Sustained directional trends with moderate-to-high ADX and low choppiness — textbook trend-following environment.
- Post-consolidation breakouts backed by real volume expansion.
- Markets with clear macro-trend alignment (price clearly above/below EMA200) rather than sitting right on top of it.
- Performs worst in prolonged range-bound/low-volatility regimes (many crossovers will simply be filtered out — a sign the system is working correctly, but frequency drops toward zero) and during sudden news/gap events where ATR hasn't repriced yet.

---

## 18. Suggested Improvements (future iterations)

- Add a correlation-aware portfolio layer so BTC/ETH/SOL signals firing simultaneously don't stack effectively-identical directional risk.
- Consider a regime classifier (e.g., simple HMM or rolling-vol bucket) to dynamically switch ATR multipliers instead of static ranges.
- Layer in funding-rate data (perp-specific) as an additional filter — extreme funding often precedes mean-reversion against the crossover direction.
- Explore machine-learning-assisted false-signal scoring on top of the rule-based filters as a research extension, while keeping the rule-based version as the deployed/auditable baseline.

---

## 19. Pine Script (v5) Implementation Considerations

- Use `request.security()` carefully for the 1H RSI confirmation when running on the 4H chart — apply `barmerge.gaps_off` and `barmerge.lookahead_off` to avoid repainting/future-leak.
- The "confirmation within 3× 1H candles after 4H crossover" logic needs a persistent `var` counter that resets on new crossover and increments per 1H bar — this is the trickiest part to implement without repainting.
- Chandelier/trailing logic should use `var float` state carried across bars, updated only in the direction that tightens/extends, never loosened.
- Use `strategy.exit()` with `qty_percent` for the partial-exit tranches (40%/30%/30%) rather than manual order math.
- Backtest in Pine using bar replay first to visually confirm no lookahead bias before trusting the Strategy Tester equity curve.
- Given your existing 9/20 EMA + ATR-confirmation Pine script, this design is a natural extension — the smart-stop and chandelier-trail blocks are the main new components to bolt on to what you already have.

---

## 20. Python Implementation Considerations

- Use `pandas` + `pandas_ta` (or `ta-lib` if available) for indicator calculation; vectorize signal generation, but simulate trade management (partials/trailing) with an explicit event loop since state (partial-exit flags, trail level) is path-dependent and doesn't vectorize cleanly.
- Resample 1H data to 4H carefully — align candle boundaries to your exchange's actual 4H close times (00:00/04:00/08:00 UTC etc.), don't just naive-resample or you'll introduce look-ahead.
- For the RSI confirmation window, iterate 1H bars forward from each 4H signal bar rather than trying to vectorize the "within N bars" logic — much less error-prone.
- Use `vectorbt` or a custom event-driven backtester (not pure vectorized backtesting) once partials/trailing are involved — vectorized backtesters struggle with the path-dependent partial-exit logic here.
- Keep raw OHLCV, computed indicators, and trade logs in separate DataFrames/tables for clean walk-forward slicing.

---

## 21. Backtesting Checklist

**Recommended assets:** BTC, ETH, SOL perpetual futures (highest liquidity, cleanest price action for trend-following; avoid illiquid alts where slippage will dominate results).

**Historical testing period:** minimum 3 years of 1H/4H data, spanning at least one full bull, one bear, and one extended chop/range regime — a single-cycle backtest will overfit to that cycle's character.

**Process:**
1. In-sample fit on ~60% of data (parameter selection within the ranges in Section 14).
2. Walk-forward validation: roll the in-sample/out-of-sample window forward in segments (e.g., 6-month train / 2-month test, rolled repeatedly) rather than one static split.
3. Out-of-sample test on the untouched final ~20–25% of data, no further parameter changes after this point.
4. Monte Carlo resampling of the trade sequence (shuffle trade order, randomize entry timing slightly) to test whether results depend on a lucky sequence.
5. Sensitivity test: perturb each key parameter (ATR multiplier, ADX threshold, RSI zones) ±10–20% and confirm performance degrades gracefully rather than falling off a cliff — a sign of robustness vs. overfitting.

**Metrics to report:** Win Rate, Profit Factor, Sharpe Ratio, Sortino Ratio, Maximum Drawdown, Expectancy (per trade, in R), Average R-Multiple, CAGR, and additionally: average holding period, trade frequency per month, and max consecutive losses observed (to validate the risk-management assumptions in Section 10 against real data).

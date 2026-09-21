# Bug Tracker — Trend Rider

Legend: `[x]` fixed & verified · `[ ]` open · severity in the heading.
Files reviewed: `trend_rider_engine.py`, `backtest_cli.py`, `delta_trader.py`.

---

## 🔴 MAJOR (results wrong / real money at risk)

- [x] **M1 — Equity curve ignored open-trade P&L → drawdown understated.**
  `trend_rider_engine.py`. Equity only changed on trade *close*, so intra-trade
  losses were invisible and `max_drawdown`/`sharpe`/`sortino` were optimistic.
  **Fixed:** equity curve now marks-to-market unrealized P&L each bar (~L456).

- [x] **M2 — Backtest stops filled at the exact stop price, even on gaps.**
  `trend_rider_engine.py`. A bar gapping through the stop still filled at the
  stop level, overstating P&L. **Fixed:** stop now fills at the worse of trail
  vs bar open (~L318). (Fees/funding/slippage still not modelled — see O-open list.)

- [x] **M3 — Percentage micro-trail (0.5%/0.3%) scratched every winner.**
  Turned profitable years negative (2023 -5.7% → +28.4% after fix; 2024
  +18.9% → +79.4%). **Fixed:** `trail_pct_activation` default → 999 (off) in
  engine + CLI; chandelier/SuperTrend trail now drives exits.

- [x] **M4 — Live legacy position sizing ignored `contract_val`.**
  `delta_trader.py:1007` computed `contracts = risk_amount / stop_dist`, ~1000×
  off for BTC (contract_value 0.001). **Fixed:** now divides by
  `stop_dist * contract_val`, matching the other sizing branches.

- [x] **M5 — Trailing-stop progress never persisted.**
  `delta_trader.py`. `_manage_active_position` mutated `pos` in place but
  `save_state()` only ran on entry/exit assignment; a restart reverted a
  tightened stop to entry-time values. **Fixed:** `save_state()` now fires on
  every trail tighten in both long/short branches (~L1250, ~L1320).

### 🔴 MAJOR — still OPEN (need sign-off; they change live exchange orders)

- [ ] **M6 — Trail is "soft" only; exchange stop is never re-issued as it moves.**
  `delta_trader.py` ~L1197-1315. The exchange stop order is placed once at entry.
  As the in-memory trail advances to breakeven+, the exchange still holds the
  *original* loss-level stop. If the bot is down/disconnected, on-exchange
  protection is the entry stop, not the trail. Fix = cancel+replace the exchange
  stop each time the trail tightens (real orders, rate limits, partial fills).

- [ ] **M7 — Recovered/reconstructed positions run with NO exchange stop.**
  `delta_trader.py` ~L466-489 (reconcile) & ~L917-926 (in-cycle rebuild).
  A position recovered on startup gets a fabricated ±5% stop in memory but no
  protective order is placed, and `stop_order_id` is absent, so
  `cancel_algo_orders` has nothing to cancel. A recovered live position can run
  completely unprotected. **Recommend fixing this first** — highest real-money risk.

---

## 🟡 MEDIUM (logic divergence / realism) — all OPEN

- [ ] **Md1 — Backtest LTF confirmation uses a different 1H bar than live.**
  `trend_rider_engine.py:423`. `ltf_d[ltf_d.index <= t]` grabs the 1H bar opening
  at the same instant as the 4H bar (earliest of the window), not the latest
  completed one. Not lookahead, but backtest ≠ live.

- [ ] **Md2 — Recovered position `init_risk = entry*0.05` breaks R-phases.**
  `delta_trader.py:474,488`. R-multiple = move / init_risk drives the 2R/4R
  chandelier tightening. With init_risk ~5% of price, real moves rarely reach 2R,
  so a recovered position trails completely differently from a normal one.

- [ ] **Md3 — Manual-close PnL notification omits `contract_val`.**
  `delta_trader.py:814`. `pnl = (exit-entry)*size` vs every other path
  `*contract_val`. Notification-only, but off by the contract-value factor.

- [ ] **Md4 — Queued manual OPEN silently dropped if a position exists.**
  `delta_trader.py:830-838` vs 859/932. `_force_open` flag is popped but entry
  only runs in the `no active position` branch, so the command is consumed and
  lost with no error to the user.

- [ ] **Md5 — Non-atomic entry: fill can end up with wrong/absent stop.**
  `delta_trader.py:1057-1119`. Market entry placed before the stop order and
  before `active_position` is set; if stop placement throws, the fill exists but
  is reconstructed next cycle with the generic `stop_atr_mult` stop (not the
  adaptive SL) and — per M7 — no real stop order.

- [ ] **Md6 — Entry-bar stop not checked on the entry bar (backtest).**
  `trend_rider_engine.py`. Position opens at signal-bar close; stop-hit tested
  from the next bar only. Combined with M2's gap handling if the next bar gaps.

---

## 🟢 MINOR (cosmetic / edge cases) — all OPEN

- [ ] **mn1 —** `trend_rider_engine.py:557`: `profit_factor` returns `999.99`
  sentinel when there are no losses — pollutes any aggregation.
- [ ] **mn2 —** `backtest_cli.py` `save_csv`: writes trade CSVs to the current
  working dir, not `CACHE_DIR`.
- [ ] **mn3 —** `backtest_cli.py` main loop: `SYMBOL` global left overridden if
  `run_year` raises (restore line skipped by the exception).
- [ ] **mn4 —** `backtest_cli.py:329`: `len(df4h)` assumes `fetch_year_data`
  never returns `None`; fallback contract not enforced.
- [ ] **mn5 —** `delta_trader.py:717`: `dropna` subset has `donchian_high` but
  not `donchian_low`; a NaN `donchian_low` makes the short-breakout compare
  silently False instead of being excluded — early short breakouts can be missed.
- [ ] **mn6 —** `delta_trader.py`: state keys inconsistent — `positions` &
  `_notified_signals` keyed by canonical symbol, `_last_exit_candle_ts` by Delta
  symbol. Consistent today, fragile for future lookups.
- [ ] **mn7 —** `delta_trader.py:230,233`: `stop_price`/`limit_price` hard-rounded
  to 2 decimals regardless of instrument tick size — can misplace/reject orders
  on fine-tick contracts.
- [ ] **mn8 —** `delta_trader.py:795,798`: ticker-fetch fallback uses the
  currently-forming candle's close as "current price" (stale, fallback path only).

---

## ✅ Verified NOT bugs (checked, no action)

- Trail update conditions only ever tighten the stop (no wrong-direction/loosening).
- Exit order sides correct (sell to close long, buy to close short).
- Live signal eval uses `iloc[-2]` as last closed / `iloc[-3]` as prev — no lookahead.
- `_notified_signals` dedup key committed only after successful entry — failed
  entries correctly retry.
- Manual `/sl` command can set a worse stop, but that's an explicit user override.

---

## Status summary
- **Fixed:** 5 of 7 majors (all backtest-correctness + 2 live) — M1–M5.
- **Open majors:** M6, M7 — both change live exchange order placement, awaiting go-ahead.
- **Open mediums:** 6 · **Open minors:** 8.

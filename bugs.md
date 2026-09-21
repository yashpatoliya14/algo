# Bug Tracker — Trend Rider

Legend: `[x]` fixed & verified · `[ ]` open. Files: `trend_rider_engine.py`,
`backtest_cli.py`, `delta_trader.py`.

---

## 🔴 MAJOR — all FIXED

- [x] **M1 — Equity curve ignored open-trade P&L → drawdown understated.**
  Engine now marks-to-market unrealized P&L each bar; drawdown/Sharpe/Sortino honest.
- [x] **M2 — Backtest stops filled at exact stop even on gaps.**
  Stop now fills at the worse of trail vs bar open.
- [x] **M3 — 0.5%/0.3% micro-trail scratched every winner.**
  Disabled (`trail_pct_activation=999`); chandelier/SuperTrend trail drives exits.
- [x] **M4 — Live legacy sizing ignored `contract_val` (~1000× off).**
  Now divides by `stop_dist * contract_val`.
- [x] **M5 — Trailing-stop progress not persisted across restart.**
  `save_state()` fires on every trail tighten.
- [x] **M6 — Trail was soft-only; exchange stop never re-issued as it moved.**
  Added `_reissue_stop_order()` — cancels + replaces the exchange stop on each tighten.
- [x] **M7 — Recovered positions ran with NO exchange stop.**
  `_reconstruct_recovered_position()` places a protective stop + tracks its id.

---

## 🟡 MEDIUM — 1 fixed, 5 OPEN

- [x] **Md1 — Backtest LTF confirmation used a stale 1H bar (3h behind).**
  Now selects newest 1H bar closed by the 4H close (`index < t + htf_delta`),
  lookahead-free. Fixed the broken baseline.

- [ ] **Md2 — Recovered position stop is a crude ±5% from entry.**
  `delta_trader.py` `_reconstruct_recovered_position`. `init_risk` now = actual
  stop distance (R-phases work), but the stop itself isn't the strategy's adaptive
  SL — we can't recover the original ATR context. Protective but not optimal.

- [ ] **Md3 — Manual-close PnL notification omits `contract_val`.**
  `delta_trader.py:814`. Off by the contract-value factor. Notification-only.

- [ ] **Md4 — Queued manual OPEN silently dropped if a position exists.**
  `delta_trader.py` ~830-838 vs 859/932. `_force_open` flag popped but entry only
  runs in the no-active-position branch; command consumed and lost, no error.

- [ ] **Md5 — Non-atomic entry: fill can end up with wrong/absent stop.**
  `delta_trader.py` ~1057-1119. Market entry placed before stop order and before
  `active_position` set; if stop placement throws, next-cycle reconstruction uses
  the generic stop, not the adaptive SL.

- [ ] **Md6 — Entry-bar stop not checked on the entry bar (backtest).**
  `trend_rider_engine.py`. Stop-hit tested from the next bar only.

---

## 🟢 MINOR — all OPEN

- [ ] **mn1 —** `trend_rider_engine.py`: `profit_factor` returns `999.99` sentinel
  when there are no losses — pollutes aggregation.
- [ ] **mn2 —** `backtest_cli.py` `save_csv`: writes CSVs to cwd, not `CACHE_DIR`.
- [ ] **mn3 —** `backtest_cli.py` main loop: `SYMBOL` global left overridden if
  `run_year` raises (restore skipped by exception).
- [ ] **mn4 —** `backtest_cli.py`: `len(df4h)` assumes `fetch_year_data` never
  returns `None`; fallback contract not enforced.
- [ ] **mn5 —** `delta_trader.py:717`: `dropna` subset has `donchian_high` but not
  `donchian_low`; NaN `donchian_low` makes short-breakout compare silently False.
- [ ] **mn6 —** `delta_trader.py`: state keys inconsistent — positions/notified by
  canonical symbol, `_last_exit_candle_ts` by Delta symbol. Fragile.
- [ ] **mn7 —** `delta_trader.py` ~230,233: prices hard-rounded to 2 decimals
  regardless of tick size — can misplace/reject fine-tick orders.
- [ ] **mn8 —** `delta_trader.py` ~795,798: ticker fallback uses the forming
  candle's close as current price (stale, fallback path only).

---

## Status
- **Majors:** 7/7 fixed.
- **Mediums:** 1/6 fixed (Md1). Open: Md2–Md6.
- **Minors:** 0/8 fixed. Open: mn1–mn8.
- Live-order fixes (M4–M7) verified by byte-compile only — **not yet run against
  live/testnet exchange.** Run a dry_run/testnet cycle before trusting.

## Tuning (separate from bugs)
- RSI gate 78/22 → 65/35 (breakout entries only): WR 34.9→36.8%, expectancy
  +0.30→+0.36R, 6yr compounded +1174→+1377%, avg DD −25→−23%.
- Harness: `scratch/experiment.py`.
- Still open perf work: 2022/bear-market edge (−15% best case); fees/funding/slippage
  not modelled.

// Full port of Python trend_rider_engine indicators to Node.js
// Implements EMA, TR, ATR, RSI, Supertrend, Donchian, and a backtest runner

function ema(series, period) {
  const out = new Array(series.length).fill(NaN);
  const alpha = 2 / (period + 1);
  let prev = series[0];
  out[0] = prev;
  for (let i = 1; i < series.length; i++) {
    const v = series[i];
    prev = prev * (1 - alpha) + v * alpha;
    out[i] = prev;
  }
  return out;
}

function trueRange(high, low, close) {
  const out = new Array(high.length).fill(0);
  for (let i = 0; i < high.length; i++) {
    if (i === 0) {
      out[i] = high[i] - low[i];
      continue;
    }
    const prevClose = close[i - 1];
    out[i] = Math.max(high[i] - low[i], Math.abs(high[i] - prevClose), Math.abs(low[i] - prevClose));
  }
  return out;
}

function atr_from_tr(tr, period = 14) {
  const out = new Array(tr.length).fill(NaN);
  let prev = tr[0];
  out[0] = prev;
  const alpha = 1 / period;
  for (let i = 1; i < tr.length; i++) {
    prev = prev * (1 - alpha) + tr[i] * alpha;
    out[i] = prev;
  }
  return out;
}

function rsi(series, period = 14) {
  const out = new Array(series.length).fill(NaN);
  const delta = new Array(series.length).fill(0);
  for (let i = 1; i < series.length; i++) delta[i] = series[i] - series[i - 1];
  let gain = 0, loss = 0;
  for (let i = 1; i <= period && i < series.length; i++) {
    if (delta[i] > 0) gain += delta[i]; else loss += -delta[i];
  }
  let avgGain = gain / period;
  let avgLoss = loss / period;
  out[period] = 100 - 100 / (1 + (avgGain / (avgLoss || 1e-9)));
  for (let i = period + 1; i < series.length; i++) {
    const d = delta[i];
    const g = d > 0 ? d : 0;
    const l = d < 0 ? -d : 0;
    avgGain = (avgGain * (period - 1) + g) / period;
    avgLoss = (avgLoss * (period - 1) + l) / period;
    const rs = avgGain / (avgLoss || 1e-9);
    out[i] = 100 - 100 / (1 + rs);
  }
  // fill-na with 50
  for (let i = 0; i < out.length; i++) if (isNaN(out[i])) out[i] = 50;
  return out;
}

function supertrend_full(high, low, close, period = 10, mult = 3.0) {
  const tr = trueRange(high, low, close);
  const atr_arr = atr_from_tr(tr, period);
  const hl2 = high.map((h, i) => (h + low[i]) / 2);

  const upper = hl2.map((v, i) => v + mult * (atr_arr[i] || 0));
  const lower = hl2.map((v, i) => v - mult * (atr_arr[i] || 0));

  const final_upper = upper.slice();
  const final_lower = lower.slice();
  const direction = new Array(close.length).fill(1);
  const value = new Array(close.length).fill(NaN);

  for (let i = 1; i < close.length; i++) {
    final_upper[i] = (upper[i] < final_upper[i - 1] || close[i - 1] > final_upper[i - 1]) ? upper[i] : final_upper[i - 1];
    final_lower[i] = (lower[i] > final_lower[i - 1] || close[i - 1] < final_lower[i - 1]) ? lower[i] : final_lower[i - 1];

    if (close[i] > final_upper[i - 1]) direction[i] = 1;
    else if (close[i] < final_lower[i - 1]) direction[i] = -1;
    else direction[i] = direction[i - 1];

    value[i] = direction[i] === 1 ? final_lower[i] : final_upper[i];
  }

  return { direction, value, atr: atr_arr };
}

function compute_indicators(candles, p = {}) {
  const n = candles.length;
  const close = candles.map(c => c.close);
  const high = candles.map(c => c.high);
  const low = candles.map(c => c.low);

  const ema_fast = ema(close, p.ema_fast || 21);
  const ema_slow = ema(close, p.ema_slow || 55);
  const tr = trueRange(high, low, close);
  const atr_arr = atr_from_tr(tr, p.atr_period || 14);
  const rsi_arr = rsi(close, p.rsi_period || 14);
  const st = supertrend_full(high, low, close, p.st_period || 10, p.st_mult || 3.0);

  // Donchian
  const donchian_high = new Array(n).fill(NaN);
  const donchian_low = new Array(n).fill(NaN);
  const donPeriod = p.donchian_period || 30;
  for (let i = donPeriod; i < n; i++) {
    let maxH = -Infinity, minL = Infinity;
    for (let j = i - donPeriod; j < i; j++) {
      if (high[j] > maxH) maxH = high[j];
      if (low[j] < minL) minL = low[j];
    }
    donchian_high[i] = maxH;
    donchian_low[i] = minL;
  }

  const out = [];
  for (let i = 0; i < n; i++) {
    out.push({
      ts: candles[i].ts,
      open: candles[i].open,
      high: high[i],
      low: low[i],
      close: close[i],
      volume: candles[i].volume,
      ema_fast: ema_fast[i],
      ema_slow: ema_slow[i],
      atr: atr_arr[i],
      rsi: rsi_arr[i],
      st_dir: st.direction[i],
      st_val: st.value[i],
      donchian_high: donchian_high[i],
      donchian_low: donchian_low[i],
      ema_fast_slope: (i >= 3) ? (ema_fast[i] > ema_fast[i - 3]) : false,
      ema_fast_slope_short: (i >= 3) ? (ema_fast[i] < ema_fast[i - 3]) : false,
      st_flip_bull: (i >= 1) ? (st.direction[i] === 1 && st.direction[i - 1] === -1) : false,
      st_flip_bear: (i >= 1) ? (st.direction[i] === -1 && st.direction[i - 1] === 1) : false,
      st_recent_bull: false,
      st_recent_bear: false,
      trend_bull: (ema_fast[i] > (ema_slow[i] || 0)) && (st.direction[i] === 1),
      trend_bear: (ema_fast[i] < (ema_slow[i] || 0)) && (st.direction[i] === -1),
    });
  }

  // compute st_recent_bull/bear similar to Python (flip now or previous bar)
  for (let i = 0; i < n; i++) {
    if (i >= 1) {
      out[i].st_recent_bull = out[i].st_flip_bull || out[i - 1].st_flip_bull;
      out[i].st_recent_bear = out[i].st_flip_bear || out[i - 1].st_flip_bear;
    } else {
      out[i].st_recent_bull = out[i].st_flip_bull || false;
      out[i].st_recent_bear = out[i].st_flip_bear || false;
    }
  }

  return out;
}

// Basic backtest runner: mirrors Python run_trend_rider_backtest semantics
function run_trend_rider_backtest(candles, p = {}) {
  const params = Object.assign({
    ema_fast: 21,
    ema_slow: 55,
    st_period: 10,
    st_mult: 3.0,
    atr_period: 14,
    rsi_period: 14,
    rsi_ob: 78.0,
    rsi_os: 22.0,
    donchian_period: 30,
    stop_atr_mult: 2.0,
    trail_be_buffer: 0.2,
    trail_phase2_mult: 2.5,
    trail_phase3_mult: 1.8,
    trail_pct_activation: 1.0,
    trail_pct_distance: 0.4,
    risk_pct: 1.5,
    cooldown_bars: 3,
  }, p);

  // Build indicator array similar to Python DataFrame rows
  const d = compute_indicators(candles, params);
  // filter out rows missing required fields
  const rows = d.filter(r => r.ema_fast && r.ema_slow && r.atr && r.st_dir !== undefined && r.donchian_high !== undefined);

  const trades = [];
  let open_trade = null;
  let equity = 10000.0;
  let last_exit_bar = -999;

  const equity_curve = [];
  // start curve with first timestamp
  if (rows.length) equity_curve.push({ time: rows[0].ts, equity });
  for (let i = 1; i < rows.length; i++) {
    const prev = rows[i - 1];
    const row = rows[i];

    // Manage open trade
    if (open_trade) {
      const atrv = row.atr || 1;
      if (open_trade.direction === 'long') {
        open_trade.highest_since = Math.max(open_trade.highest_since || row.high, row.high);
        const r_now = (row.close - open_trade.entry_price) / open_trade.init_risk;

        const pct_move = (open_trade.highest_since - open_trade.entry_price) / open_trade.entry_price * 100.0;
        if (pct_move >= params.trail_pct_activation) {
          const pct_stop = open_trade.highest_since * (1.0 - params.trail_pct_distance / 100.0);
          open_trade.trail = Math.max(open_trade.trail, pct_stop);
        }

        // phased trailing
        if (r_now >= 1.0 && r_now < 2.0) {
          const be = open_trade.entry_price + (params.trail_be_buffer * atrv);
          open_trade.trail = Math.max(open_trade.trail, be);
        } else if (r_now >= 2.0 && r_now < 4.0) {
          const chand = open_trade.highest_since - params.trail_phase2_mult * atrv;
          open_trade.trail = Math.max(open_trade.trail, chand);
        } else if (r_now >= 4.0) {
          const chand = open_trade.highest_since - params.trail_phase3_mult * atrv;
          open_trade.trail = Math.max(open_trade.trail, chand);
        }

        // supertrend floor
        if (row.st_val !== undefined && row.st_val !== null) {
          if (row.st_val > open_trade.trail) open_trade.trail = row.st_val;
        }

        const stop_hit = row.low <= open_trade.trail;
        const st_reversed = row.st_dir === -1;
        if (stop_hit || st_reversed) {
          const exit_price = stop_hit ? open_trade.trail : row.close;
          const pnl = open_trade.qty * (exit_price - open_trade.entry_price);
          open_trade.exit_time = row.ts;
          open_trade.exit_price = exit_price;
          open_trade.pnl = pnl;
          open_trade.r_multiple = (exit_price - open_trade.entry_price) / open_trade.init_risk;
          open_trade.exit_reason = stop_hit ? 'trail_stop' : 'st_reversed';
          trades.push(Object.assign({ exit: true }, open_trade));
          equity += pnl;
          equity_curve.push({ time: row.ts, equity });
          open_trade = null;
          last_exit_bar = i;
        }
      } else {
        open_trade.lowest_since = Math.min(open_trade.lowest_since || row.low, row.low);
        const r_now = (open_trade.entry_price - row.close) / open_trade.init_risk;

        const pct_move = (open_trade.entry_price - open_trade.lowest_since) / open_trade.entry_price * 100.0;
        if (pct_move >= params.trail_pct_activation) {
          const pct_stop = open_trade.lowest_since * (1.0 + params.trail_pct_distance / 100.0);
          open_trade.trail = Math.min(open_trade.trail, pct_stop);
        }

        if (r_now >= 1.0 && r_now < 2.0) {
          const be = open_trade.entry_price - (params.trail_be_buffer * atrv);
          open_trade.trail = Math.min(open_trade.trail, be);
        } else if (r_now >= 2.0 && r_now < 4.0) {
          const chand = open_trade.lowest_since + params.trail_phase2_mult * atrv;
          open_trade.trail = Math.min(open_trade.trail, chand);
        } else if (r_now >= 4.0) {
          const chand = open_trade.lowest_since + params.trail_phase3_mult * atrv;
          open_trade.trail = Math.min(open_trade.trail, chand);
        }

        if (row.st_val !== undefined && row.st_val !== null) {
          if (row.st_val < open_trade.trail) open_trade.trail = row.st_val;
        }

        const stop_hit = row.high >= open_trade.trail;
        const st_reversed = row.st_dir === 1;
        if (stop_hit || st_reversed) {
          const exit_price = stop_hit ? open_trade.trail : row.close;
          const pnl = open_trade.qty * (open_trade.entry_price - exit_price);
          open_trade.exit_time = row.ts;
          open_trade.exit_price = exit_price;
          open_trade.pnl = pnl;
          open_trade.r_multiple = (open_trade.entry_price - exit_price) / open_trade.init_risk;
          open_trade.exit_reason = stop_hit ? 'trail_stop' : 'st_reversed';
          trades.push(Object.assign({ exit: true }, open_trade));
          equity += pnl;
          equity_curve.push({ time: row.ts, equity });
          open_trade = null;
          last_exit_bar = i;
        }
      }
    }

    // Entry checks
    if (!open_trade && (i - last_exit_bar) >= params.cooldown_bars) {
      let signal = null;
      let signal_type = '';
      const atrv = row.atr || 1;
      const ema_val = row.ema_fast;

      if (row.trend_bull && row.ema_fast_slope) {
        const is_pullback = (prev.low <= ema_val * 1.003) && (row.close > ema_val) && (row.close > row.open);
        const is_breakout = (row.close > row.donchian_high) && (row.rsi < params.rsi_ob);
        const is_st_flip = row.st_recent_bull && (row.close > ema_val);
        if (is_pullback) { signal = 'long'; signal_type = 'pullback'; }
        else if (is_breakout) { signal = 'long'; signal_type = 'breakout'; }
        else if (is_st_flip) { signal = 'long'; signal_type = 'fresh_trend'; }
      } else if (row.trend_bear && row.ema_fast_slope_short) {
        const is_pullback = (prev.high >= ema_val * 0.997) && (row.close < ema_val) && (row.close < row.open);
        const is_breakout = (row.close < row.donchian_low) && (row.rsi > params.rsi_os);
        const is_st_flip = row.st_recent_bear && (row.close < ema_val);
        if (is_pullback) { signal = 'short'; signal_type = 'pullback'; }
        else if (is_breakout) { signal = 'short'; signal_type = 'breakout'; }
        else if (is_st_flip) { signal = 'short'; signal_type = 'fresh_trend'; }
      }

      if (signal) {
        const entry_price = row.close;
        const stop = signal === 'long' ? entry_price - params.stop_atr_mult * atrv : entry_price + params.stop_atr_mult * atrv;
        const risk_dist = Math.abs(entry_price - stop);
        if (risk_dist > 0) {
          const qty = (equity * (params.risk_pct / 100.0)) / risk_dist;
          open_trade = {
            direction: signal,
            entry_time: row.ts,
            entry_price: entry_price,
            stop: stop,
            init_risk: risk_dist,
            qty: qty,
            signal_type: signal_type,
            trail: stop,
            highest_since: row.high,
            lowest_since: row.low,
            equity_at_entry: equity,
          };
          trades.push(Object.assign({ entry: true }, open_trade));
          // record equity at entry bar
          equity_curve.push({ time: row.ts, equity });
        }
      }
    }
  }

  // close open trade at end
  if (open_trade) {
    const last = rows[rows.length - 1];
    const exit_price = last.close;
    const pnl = open_trade.qty * (open_trade.direction === 'long' ? (exit_price - open_trade.entry_price) : (open_trade.entry_price - exit_price));
    open_trade.exit_time = last.ts;
    open_trade.exit_price = exit_price;
    open_trade.pnl = pnl;
    open_trade.r_multiple = (open_trade.direction === 'long' ? (exit_price - open_trade.entry_price) : (open_trade.entry_price - exit_price)) / open_trade.init_risk;
    open_trade.exit_reason = 'end_of_data';
    trades.push(Object.assign({ exit: true }, open_trade));
    equity += pnl;
    equity_curve.push({ time: last.ts, equity });
    open_trade = null;
  }

  return { trades, equity_curve, equity };
}

module.exports = { compute_indicators, run_trend_rider_backtest };


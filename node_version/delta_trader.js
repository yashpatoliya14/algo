require('dotenv').config();
const axios = require('axios');
const TelegramNotifier = require('./telegram_notifier');
const { toCanonical, toDelta } = require('./symbol_utils');
const { compute_indicators: computeIndicators } = require('./trend_rider_engine');

const POLL_INTERVAL = parseInt(process.env.POLL_INTERVAL_SEC || '60', 10);
const TIMEFRAME = process.env.TIMEFRAME || '4h';
const DRY_RUN = (process.env.DRY_RUN || 'true').toLowerCase() === 'true';
const RISK_PCT = parseFloat(process.env.RISK_PCT || '1.5');
const LEVERAGE = parseInt(process.env.LEVERAGE || '5', 10);

const notifier = new TelegramNotifier();
const lastSignalBySymbol = new Map();

function stripQuotes(s) {
  if (!s) return s;
  s = s.trim();
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) return s.slice(1, -1);
  return s;
}

function parseSymbols() {
  const env = stripQuotes(process.env.SYMBOLS || '');
  const out = [];
  if (env) {
    env.split(',').forEach(p => {
      const s = p.trim();
      if (!s) return;
      const canon = toCanonical(s);
      const delta = toDelta(canon);
      out.push({ canon, delta });
    });
  } else if (process.env.SYMBOL) {
    const canon = toCanonical(process.env.SYMBOL);
    out.push({ canon, delta: toDelta(canon) });
  }
  if (out.length === 0) out.push({ canon: 'BTC/USDT', delta: 'BTCUSDT' });
  return out;
}

async function fetchCandles(deltaSymbol, resolution = '4h', limit = 150) {
  const base = (process.env.DELTA_BASE_URL || 'https://api.india.delta.exchange').replace(/\/$/, '');
  const params = { symbol: deltaSymbol, resolution };
  const url = `${base}/v2/history/candles`;
  try {
    const r = await axios.get(url, { params, timeout: 10000 });
    return r.data.result || [];
  } catch (e) {
    return [];
  }
}

function fmtTime(ts) {
  const d = new Date(Number(ts) * 1000);
  if (Number.isNaN(d.getTime())) return '';
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  return `${y}-${m}-${day} ${hh}:${mm} UTC`;
}

function round2(v) {
  return Number(Number(v || 0).toFixed(2));
}

async function runCycle(symbol) {
  try {
    const candles = await fetchCandles(symbol.delta, TIMEFRAME, 200);
    if (!candles || candles.length < 10) return;
    const sorted = candles
      .map(c => ({ ts: Number(c.time), open: Number(c.open), high: Number(c.high), low: Number(c.low), close: Number(c.close), volume: Number(c.volume) }))
      .sort((a, b) => a.ts - b.ts);
    const d = computeIndicators(sorted);
    const rows = d.filter(r => r.ema_fast && r.ema_slow && r.atr && r.st_dir !== undefined && r.donchian_high !== undefined);
    if (rows.length < 5) return;

    const curr = rows[rows.length - 2];
    const prev = rows[rows.length - 3];
    const emaVal = curr.ema_fast;
    const atrVal = curr.atr || 1;

    let signal = null;
    let signalType = '';
    if (curr.trend_bull && curr.ema_fast_slope) {
      const isPullback = (prev.low <= emaVal * 1.003) && (curr.close > emaVal) && (curr.close > curr.open);
      const isBreakout = (curr.close > curr.donchian_high) && (curr.rsi < 78.0);
      const isStFlip = curr.st_recent_bull && (curr.close > emaVal);
      if (isPullback) { signal = 'long'; signalType = 'pullback'; }
      else if (isBreakout) { signal = 'long'; signalType = 'breakout'; }
      else if (isStFlip) { signal = 'long'; signalType = 'fresh_trend'; }
    } else if (curr.trend_bear && curr.ema_fast_slope_short) {
      const isPullback = (prev.high >= emaVal * 0.997) && (curr.close < emaVal) && (curr.close < curr.open);
      const isBreakout = (curr.close < curr.donchian_low) && (curr.rsi > 22.0);
      const isStFlip = curr.st_recent_bear && (curr.close < emaVal);
      if (isPullback) { signal = 'short'; signalType = 'pullback'; }
      else if (isBreakout) { signal = 'short'; signalType = 'breakout'; }
      else if (isStFlip) { signal = 'short'; signalType = 'fresh_trend'; }
    }

    if (!signal) {
      lastSignalBySymbol.delete(symbol.canon);
      return;
    }

    const candleTime = fmtTime(curr.ts);
    const signalKey = `${symbol.canon}|${signal}|${signalType}`;
    const previousSignalKey = lastSignalBySymbol.get(symbol.canon) || '';

    if (previousSignalKey === signalKey) {
      console.log(`[${candleTime}] Signal already notified for ${symbol.canon}`);
      return;
    }

    lastSignalBySymbol.set(symbol.canon, signalKey);

    const entry = round2(curr.close);
    const stopPrice = signal === 'long'
      ? round2(entry - (2.0 * atrVal))
      : round2(entry + (2.0 * atrVal));
    const riskAmount = 10000 * (RISK_PCT / 100.0);
    const contracts = Math.max(1, Math.floor(riskAmount / Math.max(1e-8, Math.abs(entry - stopPrice))));

    await notifier.signalDetailed(
      symbol.canon,
      signal,
      signalType,
      entry,
      entry,
      contracts,
      stopPrice,
      RISK_PCT,
      candleTime,
      1.0,
      0.4,
      'No fixed TP; exit on trailing stop or trend reversal'
    );
  } catch (e) {
    // ignore
  }
}

async function main() {
  const symbols = parseSymbols();
  await notifier.started(symbols.map(s => s.canon), TIMEFRAME, DRY_RUN, RISK_PCT, LEVERAGE);
  console.log(`Monitoring ${symbols.length} symbols: ${symbols.map(s=>s.canon).join(', ')}`);

  while (true) {
    for (const s of symbols) {
      await runCycle(s);
      await new Promise(r => setTimeout(r, 500));
    }
    await new Promise(r => setTimeout(r, POLL_INTERVAL * 1000));
  }
}

main().catch(e => console.error(e));

/**
 * BTCUSD 4H Trend Rider — Node.js Backtest Dashboard
 * =====================================================
 * Full-featured backtest with colorful terminal output matching Python version.
 * Includes: performance summary, trade breakdown, equity sparkline, trade log,
 * strategy verdict, and expert suggestions.
 *
 * Usage:
 *   node backtest.js BTCUSD 2024
 *   node backtest.js BTCUSD 2023
 *   node backtest.js          # defaults to BTCUSD current year
 */

require('dotenv').config();
const fs = require('fs');
const path = require('path');
const axios = require('axios');
const { run_trend_rider_backtest, compute_indicators } = require('./trend_rider_engine');
const { toCanonical, toDelta } = require('./symbol_utils');

const CACHE_DIR = path.join(__dirname, 'cache');
if (!fs.existsSync(CACHE_DIR)) fs.mkdirSync(CACHE_DIR, { recursive: true });

const INITIAL_EQUITY = 10000;

// ============================================================================
// TERMINAL COLORS
// ============================================================================

const C = {
  RESET:   '\x1b[0m',
  BOLD:    '\x1b[1m',
  DIM:     '\x1b[2m',
  RED:     '\x1b[91m',
  GREEN:   '\x1b[92m',
  YELLOW:  '\x1b[93m',
  BLUE:    '\x1b[94m',
  MAGENTA: '\x1b[95m',
  CYAN:    '\x1b[96m',
  WHITE:   '\x1b[97m',
  GRAY:    '\x1b[90m',
};

// ============================================================================
// DISPLAY HELPERS
// ============================================================================

function colorVal(val, good = 0, great = null, suffix = '') {
  if (great !== null && val >= great) return `${C.GREEN}${C.BOLD}${val}${suffix}${C.RESET}`;
  if (val >= good) return `${C.GREEN}${val}${suffix}${C.RESET}`;
  if (val > 0) return `${C.YELLOW}${val}${suffix}${C.RESET}`;
  return `${C.RED}${val}${suffix}${C.RESET}`;
}

function sparkline(values, width = 56) {
  if (!values || values.length < 2) return '';
  const blocks = ' .,:-=+*#@';
  const mn = Math.min(...values);
  const mx = Math.max(...values);
  const rng = mx - mn || 1;
  const step = Math.max(1, Math.floor(values.length / width));
  const sampled = [];
  for (let i = 0; i < values.length && sampled.length < width; i += step) {
    sampled.push(values[i]);
  }
  return sampled.map(v => blocks[Math.floor((v - mn) / rng * (blocks.length - 1))]).join('');
}

function fmtDate(ts) {
  if (!ts) return '-';
  const d = new Date(Number(ts) * 1000);
  if (isNaN(d.getTime())) return '-';
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  return `${y}-${m}-${day} ${hh}:${mm}`;
}

function divider(ch = '-', w = 62) {
  console.log(`  ${C.GRAY}${ch.repeat(w)}${C.RESET}`);
}

function section(title, icon = '') {
  console.log();
  console.log(`  ${C.CYAN}${C.BOLD}[${icon}] ${title}${C.RESET}`);
  divider();
}

function sortCandles(candles) {
  return [...candles].sort((a, b) => {
    const at = Number(a.time ?? a.ts ?? 0);
    const bt = Number(b.time ?? b.ts ?? 0);
    return at - bt;
  });
}

// ============================================================================
// DATA FETCHING & CACHING
// ============================================================================

function cachePath(symbol, year) {
  const safe = symbol.replace(/[^A-Za-z0-9_]/g, '_');
  return path.join(CACHE_DIR, `rider_${safe}_${year}.json`);
}

async function fetchCandlesDelta(symbol, start_ts, end_ts, resolution = '4h') {
  const base = (process.env.DELTA_BASE_URL || 'https://api.india.delta.exchange').replace(/\/$/, '');
  const url = `${base}/v2/history/candles`;
  const params = { symbol, resolution, start: start_ts, end: end_ts };
  try {
    const r = await axios.get(url, { params, timeout: 20000 });
    return r.data.result || [];
  } catch (_) {
    return [];
  }
}

/**
 * Convert Delta-style symbol to Binance symbol.
 * BTCUSD -> BTCUSDT, ETHUSD -> ETHUSDT, etc.
 */
function toBinanceSymbol(deltaSymbol) {
  let s = deltaSymbol.replace(/[^A-Za-z0-9]/g, '').toUpperCase();
  // Delta uses USD, Binance uses USDT for perp-equivalent spot data
  if (s.endsWith('USD') && !s.endsWith('USDT')) {
    s = s + 'T'; // BTCUSD -> BTCUSDT
  }
  return s;
}

/**
 * Fetch candles from Binance public API (no API key needed).
 * Uses pagination (limit 1000 per request).
 * Returns candles in same format as Delta: [{time, open, high, low, close, volume}]
 */
async function fetchCandlesBinance(symbol, start_ts, end_ts, interval = '4h') {
  const binanceSymbol = toBinanceSymbol(symbol);
  const url = 'https://api.binance.com/api/v3/klines';
  const allCandles = [];
  let cursor = start_ts * 1000; // Binance uses milliseconds
  const endMs = end_ts * 1000;

  while (cursor < endMs) {
    try {
      const params = {
        symbol: binanceSymbol,
        interval,
        startTime: cursor,
        endTime: endMs,
        limit: 1000,
      };
      const r = await axios.get(url, { params, timeout: 20000 });
      const batch = r.data;
      if (!batch || batch.length === 0) break;

      for (const k of batch) {
        // Binance kline: [openTime, open, high, low, close, volume, closeTime, ...]
        allCandles.push({
          time: Math.floor(k[0] / 1000), // convert ms to seconds
          open: k[1],
          high: k[2],
          low: k[3],
          close: k[4],
          volume: k[5],
        });
      }

      // Move cursor past last candle
      cursor = batch[batch.length - 1][0] + 1;
      if (batch.length < 2) break;

      // Rate limit pause
      await new Promise(r => setTimeout(r, 200));
    } catch (e) {
      console.log(`\n  ${C.RED}[Binance API Error] ${e.message}${C.RESET}`);
      break;
    }
  }

  return allCandles;
}

async function loadCachedOrFetch(symbol, year) {
  const file = cachePath(symbol, year);
  const yearComplete = year < new Date().getUTCFullYear();
  if (fs.existsSync(file) && yearComplete) {
    try {
      const cached = sortCandles(JSON.parse(fs.readFileSync(file, 'utf8')));
      if (cached.length >= 100) {
        return { candles: cached, cached: true, source: 'cache' };
      }
    } catch (e) { /* refetch */ }
  }

  const start = Math.floor(new Date(`${year}-01-01T00:00:00Z`).getTime() / 1000);
  const end = Math.floor(new Date(`${year}-12-31T23:59:59Z`).getTime() / 1000);

  // Step 1: Try Delta Exchange first
  process.stdout.write(`  ${C.GRAY}Fetching ${symbol} 4H data for ${year} from Delta...${C.RESET}`);
  const deltaCandles = await fetchCandlesDelta(symbol, start, end, '4h');
  const deltaSorted = sortCandles(deltaCandles);

  if (deltaSorted.length >= 100) {
    console.log(` ${C.GREEN}${deltaSorted.length} bars ${C.CYAN}[DELTA]${C.RESET}`);
    if (yearComplete) {
      try { fs.writeFileSync(file, JSON.stringify(deltaSorted), 'utf8'); } catch (e) { /* ignore */ }
    }
    return { candles: deltaSorted, cached: false, source: 'delta' };
  }

  // Step 2: Delta data insufficient — fallback to Binance
  console.log(` ${C.YELLOW}${deltaSorted.length} bars (insufficient)${C.RESET}`);
  const binanceSymbol = toBinanceSymbol(symbol);
  process.stdout.write(`  ${C.GRAY}Falling back to Binance (${binanceSymbol}) for ${year}...${C.RESET}`);
  const binanceCandles = await fetchCandlesBinance(symbol, start, end, '4h');
  const binanceSorted = sortCandles(binanceCandles);
  console.log(` ${C.GREEN}${binanceSorted.length} bars ${C.MAGENTA}[BINANCE]${C.RESET}`);

  if (yearComplete && binanceSorted.length >= 100) {
    try { fs.writeFileSync(file, JSON.stringify(binanceSorted), 'utf8'); } catch (e) { /* ignore */ }
  }
  return { candles: binanceSorted, cached: false, source: 'binance' };
}

function pruneCache() {
  const maxMB = parseFloat(process.env.CACHE_MAX_SIZE_MB || '200');
  const maxAgeDays = parseInt(process.env.CACHE_MAX_AGE_DAYS || '90', 10);
  let files;
  try {
    files = fs.readdirSync(CACHE_DIR).map(f => {
      const p = path.join(CACHE_DIR, f);
      const stat = fs.statSync(p);
      return { path: p, mtime: stat.mtimeMs, size: stat.size };
    });
  } catch (_) { return; }
  const now = Date.now();
  for (const f of files) {
    const ageDays = (now - f.mtime) / (1000 * 60 * 60 * 24);
    if (ageDays > maxAgeDays) {
      try { fs.unlinkSync(f.path); } catch (_) { /* ignore */ }
    }
  }
  let remaining;
  try {
    remaining = fs.readdirSync(CACHE_DIR).map(f => {
      const p = path.join(CACHE_DIR, f);
      const s = fs.statSync(p);
      return { path: p, mtime: s.mtimeMs, size: s.size };
    });
  } catch (_) { return; }
  let total = remaining.reduce((a, b) => a + b.size, 0);
  const maxBytes = maxMB * 1024 * 1024;
  if (total <= maxBytes) return;
  remaining.sort((a, b) => a.mtime - b.mtime);
  for (const f of remaining) {
    try { fs.unlinkSync(f.path); total -= f.size; } catch (_) { /* ignore */ }
    if (total <= maxBytes) break;
  }
}

// ============================================================================
// METRICS COMPUTATION
// ============================================================================

function computeMetrics(tradeRows, equityCurve, initialEquity) {
  const pnls = tradeRows.map(t => t.pnl || 0);
  const wins = pnls.filter(p => p > 0);
  const losses = pnls.filter(p => p <= 0);
  const totalTrades = tradeRows.length;
  const winRate = totalTrades ? (wins.length / totalTrades) * 100 : 0;
  const grossWin = wins.reduce((s, v) => s + v, 0);
  const grossLoss = Math.abs(losses.reduce((s, v) => s + v, 0));
  const profitFactor = grossLoss > 0 ? (grossWin / grossLoss) : (grossWin > 0 ? 999.99 : 0);
  const totalPnl = pnls.reduce((s, v) => s + v, 0);
  const avgPnl = totalTrades ? totalPnl / totalTrades : 0;
  const avgWin = wins.length ? grossWin / wins.length : 0;
  const avgLoss = losses.length ? losses.reduce((s, v) => s + v, 0) / losses.length : 0;

  // R-multiples
  const rMultiples = tradeRows.map(t => t.r_multiple || 0);
  const winningR = rMultiples.filter(r => r > 0);
  const losingR = rMultiples.filter(r => r <= 0);
  const avgR = rMultiples.length ? rMultiples.reduce((s, v) => s + v, 0) / rMultiples.length : 0;
  const avgWinnerR = winningR.length ? winningR.reduce((s, v) => s + v, 0) / winningR.length : 0;
  const avgLoserR = losingR.length ? losingR.reduce((s, v) => s + v, 0) / losingR.length : 0;

  // Largest winner / loser
  const largestWinner = pnls.length ? Math.max(...pnls) : 0;
  const largestLoser = pnls.length ? Math.min(...pnls) : 0;

  // Max consecutive losses
  let maxConsecLosses = 0, cur = 0;
  for (const p of pnls) {
    if (p <= 0) { cur++; maxConsecLosses = Math.max(maxConsecLosses, cur); }
    else { cur = 0; }
  }

  // Trade breakdown
  const longTrades = tradeRows.filter(t => t.direction === 'long').length;
  const shortTrades = tradeRows.filter(t => t.direction === 'short').length;
  const pullbackEntries = tradeRows.filter(t => t.signal_type === 'pullback').length;
  const breakoutEntries = tradeRows.filter(t => t.signal_type === 'breakout').length;
  const freshTrendEntries = tradeRows.filter(t => t.signal_type === 'fresh_trend').length;

  // Daily returns for Sharpe/Sortino
  const eqCurve = equityCurve.slice().sort((a, b) => a.time - b.time);
  const dayMap = new Map();
  for (const p of eqCurve) {
    const d = new Date(p.time * 1000);
    const key = d.toISOString().slice(0, 10);
    dayMap.set(key, p.equity);
  }
  const dailyEquities = Array.from(dayMap.entries()).sort((a, b) => a[0].localeCompare(b[0])).map(x => x[1]);
  const dailyReturns = [];
  for (let i = 1; i < dailyEquities.length; i++) {
    dailyReturns.push((dailyEquities[i] - dailyEquities[i - 1]) / dailyEquities[i - 1]);
  }
  const mean = arr => arr.reduce((s, v) => s + v, 0) / (arr.length || 1);
  const std = arr => {
    const m = mean(arr);
    return Math.sqrt(arr.reduce((s, v) => s + (v - m) * (v - m), 0) / (arr.length - 1 || 1));
  };
  const sharpe = dailyReturns.length ? (mean(dailyReturns) / (std(dailyReturns) || 1) * Math.sqrt(365)) : 0;
  const downside = dailyReturns.filter(r => r < 0);
  const sortino = downside.length ? (mean(dailyReturns) / (std(downside) || 1) * Math.sqrt(365)) : 0;

  // Max drawdown
  let peak = -Infinity, maxDdPct = 0;
  for (const p of eqCurve) {
    if (p.equity > peak) peak = p.equity;
    const dd = (p.equity - peak) / (peak || 1);
    if (dd < maxDdPct) maxDdPct = dd;
  }
  const maxDrawdown = Math.abs(maxDdPct) * 100;

  // CAGR
  let cagr = 0;
  if (eqCurve.length >= 2) {
    const startD = new Date(eqCurve[0].time * 1000);
    const endD = new Date(eqCurve[eqCurve.length - 1].time * 1000);
    const days = Math.max(1, Math.floor((endD - startD) / (1000 * 60 * 60 * 24)));
    const years = days / 365.25;
    const finalEq = eqCurve[eqCurve.length - 1].equity;
    cagr = years > 0 && finalEq > 0 ? (Math.pow(finalEq / initialEquity, 1 / years) - 1) * 100 : 0;
  }

  const finalEquity = equityCurve.length ? equityCurve[equityCurve.length - 1].equity : initialEquity;
  const totalReturnPct = ((finalEquity - initialEquity) / initialEquity) * 100;
  const netProfit = finalEquity - initialEquity;
  const tradesPerMonth = eqCurve.length >= 2 ? (() => {
    const startD = new Date(eqCurve[0].time * 1000);
    const endD = new Date(eqCurve[eqCurve.length - 1].time * 1000);
    const months = Math.max(1, (endD - startD) / (1000 * 60 * 60 * 24 * 30.44));
    return totalTrades / months;
  })() : 0;

  return {
    totalTrades, wins: wins.length, losses: losses.length,
    winRate: +winRate.toFixed(1), totalPnl: +totalPnl.toFixed(2),
    avgPnl: +avgPnl.toFixed(2), avgWin: +avgWin.toFixed(2), avgLoss: +avgLoss.toFixed(2),
    profitFactor: +(Number.isFinite(profitFactor) ? profitFactor.toFixed(2) : 999.99),
    maxDrawdown: +maxDrawdown.toFixed(2), sharpe: +sharpe.toFixed(2), sortino: +sortino.toFixed(2),
    cagr: +cagr.toFixed(2), finalEquity: +finalEquity.toFixed(2),
    totalReturnPct: +totalReturnPct.toFixed(2), netProfit: +netProfit.toFixed(2),
    maxConsecLosses, tradesPerMonth: +tradesPerMonth.toFixed(2),
    avgR: +avgR.toFixed(2), avgWinnerR: +avgWinnerR.toFixed(2), avgLoserR: +avgLoserR.toFixed(2),
    largestWinner: +largestWinner.toFixed(2), largestLoser: +largestLoser.toFixed(2),
    longTrades, shortTrades, pullbackEntries, breakoutEntries, freshTrendEntries,
  };
}

// ============================================================================
// STRATEGY VERDICT & SUGGESTIONS
// ============================================================================

function getVerdict(m, year) {
  const lines = [];
  lines.push('');
  lines.push(`  ${C.CYAN}${C.BOLD}[💡] STRATEGY VERDICT & ANALYSIS — ${year}${C.RESET}`);
  divider('=', 62);

  // Overall grade
  let grade, gradeColor, gradeEmoji;
  const score = (m.totalReturnPct > 0 ? 1 : 0) + (m.winRate >= 50 ? 1 : 0) +
    (m.profitFactor >= 1.5 ? 1 : 0) + (m.sharpe >= 1.0 ? 1 : 0) + (m.maxDrawdown <= 15 ? 1 : 0);

  if (score >= 4) { grade = 'A+ EXCELLENT'; gradeColor = C.GREEN; gradeEmoji = '🏆'; }
  else if (score >= 3) { grade = 'B GOOD'; gradeColor = C.GREEN; gradeEmoji = '✅'; }
  else if (score >= 2) { grade = 'C AVERAGE'; gradeColor = C.YELLOW; gradeEmoji = '⚠️'; }
  else { grade = 'D POOR'; gradeColor = C.RED; gradeEmoji = '❌'; }

  console.log(`\n  ${gradeEmoji} ${C.BOLD}OVERALL GRADE: ${gradeColor}${grade}${C.RESET}\n`);

  // Individual verdicts
  // Return
  if (m.totalReturnPct >= 30) {
    console.log(`  ${C.GREEN}✅ RETURN: ${m.totalReturnPct.toFixed(1)}% — Bahut shaandaar! Isse paisa banta hai bhai.${C.RESET}`);
  } else if (m.totalReturnPct >= 10) {
    console.log(`  ${C.GREEN}✅ RETURN: ${m.totalReturnPct.toFixed(1)}% — Accha hai, decent returns. Bank FD se toh better hai!${C.RESET}`);
  } else if (m.totalReturnPct >= 0) {
    console.log(`  ${C.YELLOW}⚠️  RETURN: ${m.totalReturnPct.toFixed(1)}% — Positive but kam hai. Risk ke hisab se aur chahiye.${C.RESET}`);
  } else {
    console.log(`  ${C.RED}❌ RETURN: ${m.totalReturnPct.toFixed(1)}% — Loss year! Is year strategy ne kaam nahi kiya.${C.RESET}`);
  }

  // Win rate
  if (m.winRate >= 55) {
    console.log(`  ${C.GREEN}✅ WIN RATE: ${m.winRate.toFixed(1)}% — Strong. 50% se upar trend system ke liye bohot accha.${C.RESET}`);
  } else if (m.winRate >= 40) {
    console.log(`  ${C.YELLOW}⚠️  WIN RATE: ${m.winRate.toFixed(1)}% — Average, but agar avg winner > avg loser toh chalega.${C.RESET}`);
  } else {
    console.log(`  ${C.RED}❌ WIN RATE: ${m.winRate.toFixed(1)}% — Low. Bohot loss trades, frustrating hoga real money se.${C.RESET}`);
  }

  // Profit Factor
  if (m.profitFactor >= 2.0) {
    console.log(`  ${C.GREEN}✅ PROFIT FACTOR: ${m.profitFactor} — Excellent! Har ₹1 loss pe ₹${m.profitFactor.toFixed(0)}+ profit ban raha hai.${C.RESET}`);
  } else if (m.profitFactor >= 1.3) {
    console.log(`  ${C.GREEN}✅ PROFIT FACTOR: ${m.profitFactor} — Good, profitable system. Edge hai.${C.RESET}`);
  } else if (m.profitFactor >= 1.0) {
    console.log(`  ${C.YELLOW}⚠️  PROFIT FACTOR: ${m.profitFactor} — Barely profitable. Slippage + fees se real trading mai aur kam hoga.${C.RESET}`);
  } else {
    console.log(`  ${C.RED}❌ PROFIT FACTOR: ${m.profitFactor} — Below 1 = losing money. Strategy ko improve karna padega.${C.RESET}`);
  }

  // Drawdown
  if (m.maxDrawdown <= 10) {
    console.log(`  ${C.GREEN}✅ MAX DRAWDOWN: ${m.maxDrawdown.toFixed(1)}% — Bahut safe! Capital protection acchi hai.${C.RESET}`);
  } else if (m.maxDrawdown <= 20) {
    console.log(`  ${C.YELLOW}⚠️  MAX DRAWDOWN: ${m.maxDrawdown.toFixed(1)}% — Manageable, but 20%+ drawdown psychologically tough hota hai.${C.RESET}`);
  } else {
    console.log(`  ${C.RED}❌ MAX DRAWDOWN: ${m.maxDrawdown.toFixed(1)}% — Dangerous! Itna drawdown real mai handle karna mushkil hai.${C.RESET}`);
  }

  // Sharpe
  if (m.sharpe >= 1.5) {
    console.log(`  ${C.GREEN}✅ SHARPE RATIO: ${m.sharpe} — Top tier risk-adjusted returns. Institutional level.${C.RESET}`);
  } else if (m.sharpe >= 0.5) {
    console.log(`  ${C.YELLOW}⚠️  SHARPE: ${m.sharpe} — Decent but room for improvement.${C.RESET}`);
  } else {
    console.log(`  ${C.RED}❌ SHARPE: ${m.sharpe} — Poor risk-adjusted return. Volatility zyada, return kam.${C.RESET}`);
  }

  // Consecutive losses
  if (m.maxConsecLosses >= 5) {
    console.log(`  ${C.RED}⚠️  ${m.maxConsecLosses} consecutive losses ek baar mili — mentally handle karna mushkil hoga.${C.RESET}`);
  }

  // Suggestion
  console.log();
  divider('-', 62);

  if (score >= 3) {
    console.log(`  ${C.GREEN}${C.BOLD}💰 VERDICT: Haan bhai, is strategy se paisa ban sakta hai!${C.RESET}`);
    console.log(`  ${C.WHITE}   $10,000 se shuru karo toh ${year} mai $${m.finalEquity.toLocaleString()} ban jate.${C.RESET}`);
    if (m.profitFactor >= 1.5) {
      console.log(`  ${C.WHITE}   Profit factor ${m.profitFactor} matlab edge real hai — sirf discipline chahiye.${C.RESET}`);
    }
  } else if (score >= 2) {
    console.log(`  ${C.YELLOW}${C.BOLD}⚠️  VERDICT: Strategy theek hai but not great for this year.${C.RESET}`);
    console.log(`  ${C.WHITE}   Risk management tight rakho. Position size chota rakho jab tak confidence na bane.${C.RESET}`);
  } else {
    console.log(`  ${C.RED}${C.BOLD}❌ VERDICT: Is year strategy underperform ki. Real money mat lagao jab tak improve na ho.${C.RESET}`);
    console.log(`  ${C.WHITE}   Multiple years ka data dekho — ek saal ka result decisive nahi hota.${C.RESET}`);
  }

  console.log();
  console.log(`  ${C.GRAY}${C.DIM}Tip: Multiple years run karo (2020-2025) for full picture.${C.RESET}`);
  console.log(`  ${C.GRAY}${C.DIM}Tip: Real trading mai slippage ~0.1% + fees ~0.05% hoga — returns thode kam honge.${C.RESET}`);
  console.log();
}

// ============================================================================
// DISPLAY RESULTS
// ============================================================================

function printHeader() {
  console.log();
  console.log(`  ${C.CYAN}${C.BOLD}+${'='.repeat(58)}+${C.RESET}`);
  console.log(`  ${C.CYAN}${C.BOLD}|${C.RESET}      ${C.MAGENTA}${C.BOLD}BTCUSD 4H TREND RIDER${C.RESET}  ${C.GRAY}-- Crypto Trend Strategy${C.RESET}    ${C.CYAN}${C.BOLD}|${C.RESET}`);
  console.log(`  ${C.CYAN}${C.BOLD}|${C.RESET}      ${C.GRAY}Pullback + Breakout + ST Flip + 1%->0.4% Trail${C.RESET}      ${C.CYAN}${C.BOLD}|${C.RESET}`);
  console.log(`  ${C.CYAN}${C.BOLD}+${'='.repeat(58)}+${C.RESET}`);
  console.log();
}

function printSummaryCard(m, year, cached, elapsed, source = '') {
  const sourceTag = source === 'binance' ? `${C.MAGENTA}[BINANCE]${C.RESET}` :
                    source === 'delta' ? `${C.CYAN}[DELTA]${C.RESET}` :
                    cached ? `${C.BLUE}[CACHED]${C.RESET}` : `${C.GREEN}[FRESH]${C.RESET}`;
  const retColor = m.totalReturnPct >= 15 ? C.GREEN : (m.totalReturnPct >= 0 ? C.YELLOW : C.RED);
  const wrColor = m.winRate >= 50 ? C.GREEN : C.YELLOW;

  console.log(`\n  ${C.CYAN}${C.BOLD}+${'='.repeat(64)}+${C.RESET}`);
  console.log(`  ${C.CYAN}${C.BOLD}|${C.RESET}  ${C.WHITE}${C.BOLD}ANNUAL BACKTEST OVERVIEW -- YEAR ${year}${C.RESET}  ${sourceTag} (${elapsed.toFixed(1)}s)  ${C.CYAN}${C.BOLD}|${C.RESET}`);
  console.log(`  ${C.CYAN}${C.BOLD}+${'='.repeat(64)}+${C.RESET}`);
  console.log(`  ${C.BOLD}TOTAL RETURN FOR ${year}:${C.RESET}     ${retColor}${C.BOLD}${m.totalReturnPct >= 0 ? '+' : ''}${m.totalReturnPct.toFixed(1)}%${C.RESET}  (${m.netProfit >= 0 ? '+' : ''}${m.netProfit.toFixed(2)} USD)`);
  console.log(`  ${C.BOLD}OVERALL WIN RATE:${C.RESET}          ${wrColor}${C.BOLD}${m.winRate.toFixed(1)}%${C.RESET}  (${m.totalTrades} total trades)`);
  console.log(`  ${C.BOLD}PROFIT FACTOR:${C.RESET}             ${C.WHITE}${Number.isFinite(m.profitFactor) ? m.profitFactor.toFixed(2) : 'Infinity'}${C.RESET}`);
  console.log(`  ${C.BOLD}MAX DRAWDOWN:${C.RESET}              ${C.RED}${m.maxDrawdown.toFixed(1)}%${C.RESET}`);
  console.log(`  ${C.BOLD}FINAL EQUITY:${C.RESET}              ${C.WHITE}$${m.finalEquity.toLocaleString(undefined, { minimumFractionDigits: 2 })}${C.RESET}  (from $${INITIAL_EQUITY.toLocaleString()})`);
  console.log(`  ${C.CYAN}${C.BOLD}+${'='.repeat(64)}+${C.RESET}\n`);
}

function displayResults(m, tradeRows, equityCurve, year, cached, elapsed, source) {
  printHeader();
  printSummaryCard(m, year, cached, elapsed, source);

  // -- DETAILED METRICS TABLE --
  section('DETAILED METRICS', '#');
  const rows = [
    ['Total Return', colorVal(m.totalReturnPct, 0, 15, '%'), 'Net Profit', `${m.netProfit >= 0 ? C.GREEN : C.RED}$${m.netProfit >= 0 ? '+' : ''}${m.netProfit.toFixed(2)}${C.RESET}`],
    ['Win Rate', colorVal(m.winRate, 35, 50, '%'), 'Total Trades', `${C.WHITE}${m.totalTrades}${C.RESET}`],
    ['CAGR', colorVal(m.cagr, 0, 15, '%'), 'Trades/Month', `${C.WHITE}${m.tradesPerMonth}${C.RESET}`],
    ['Profit Factor', colorVal(m.profitFactor, 1.0, 1.5), 'Avg R-Multiple', colorVal(m.avgR, 0, 0.5, 'R')],
    ['Sharpe Ratio', colorVal(m.sharpe, 0, 1.0), 'Sortino Ratio', colorVal(m.sortino, 0, 1.0)],
    ['Max Drawdown', `${m.maxDrawdown <= 15 ? C.GREEN : (m.maxDrawdown <= 25 ? C.YELLOW : C.RED)}${m.maxDrawdown.toFixed(1)}%${C.RESET}`, 'Consec Losses', `${C.WHITE}${m.maxConsecLosses}${C.RESET}`],
    ['Final Equity', `${C.WHITE}$${m.finalEquity.toLocaleString(undefined, { minimumFractionDigits: 2 })}${C.RESET}`, 'Capital', `${C.GRAY}$${INITIAL_EQUITY.toLocaleString()}${C.RESET}`],
  ];
  for (const [ll, lv, rl, rv] of rows) {
    // Pad with visible chars only (color codes don't count, but we keep it simple)
    console.log(`  ${C.GRAY}${ll.padEnd(18)}${C.RESET} ${lv}${''.padEnd(Math.max(0, 18 - ll.length))}  ${C.GRAY}${rl.padEnd(18)}${C.RESET} ${rv}`);
  }

  // -- TRADE BREAKDOWN --
  if (m.totalTrades > 0) {
    section('TRADE BREAKDOWN', '~');
    console.log(`  ${C.GRAY}Long/Short:${C.RESET}       ${C.GREEN}${m.longTrades} longs${C.RESET} / ${C.RED}${m.shortTrades} shorts${C.RESET}`);
    console.log(`  ${C.GRAY}Entry Types:${C.RESET}      ${C.CYAN}${m.pullbackEntries} pullback${C.RESET} | ${C.MAGENTA}${m.breakoutEntries} breakout${C.RESET} | ${C.YELLOW}${m.freshTrendEntries} fresh trend${C.RESET}`);
    console.log(`  ${C.GRAY}Avg Winner R:${C.RESET}     ${C.GREEN}${m.avgWinnerR}R${C.RESET}`);
    console.log(`  ${C.GRAY}Avg Loser R:${C.RESET}      ${C.RED}${m.avgLoserR}R${C.RESET}`);
    console.log(`  ${C.GRAY}Largest Win:${C.RESET}      ${C.GREEN}$${m.largestWinner >= 0 ? '+' : ''}${m.largestWinner.toFixed(2)}${C.RESET}`);
    console.log(`  ${C.GRAY}Largest Loss:${C.RESET}     ${C.RED}$${m.largestLoser.toFixed(2)}${C.RESET}`);
  }

  // -- EQUITY CURVE SPARKLINE --
  const eqValues = equityCurve.map(p => p.equity);
  if (eqValues.length > 1) {
    section('EQUITY CURVE', '$');
    const color = eqValues[eqValues.length - 1] >= eqValues[0] ? C.GREEN : C.RED;
    const spark = sparkline(eqValues);
    console.log(`  ${C.GRAY}$${eqValues[0].toLocaleString(undefined, { maximumFractionDigits: 0 })}${C.RESET} ${color}${spark}${C.RESET} ${C.GRAY}$${eqValues[eqValues.length - 1].toLocaleString(undefined, { maximumFractionDigits: 0 })}${C.RESET}`);
  }

  // -- TRADE LOG --
  if (tradeRows.length > 0) {
    section(`TRADE LOG (${tradeRows.length} trades)`, '>>');
    console.log(`  ${C.GRAY}${'#'.padStart(3)} ${'Dir'.padStart(5)} ${'Type'.padEnd(12)} ${'Entry Date'.padEnd(17)} ${'Entry$'.padStart(10)} ${'Exit Date'.padEnd(17)} ${'Exit$'.padStart(10)} ${'R'.padStart(7)} ${'PnL'.padStart(10)} ${'Exit'.padEnd(12)}${C.RESET}`);
    divider('-', 112);

    for (let i = 0; i < tradeRows.length; i++) {
      const t = tradeRows[i];
      const dc = t.direction === 'long' ? C.GREEN : C.RED;
      const ds = t.direction === 'long' ? 'LONG' : 'SHORT';
      const pc = (t.pnl || 0) < 0 ? C.RED : C.GREEN;
      const rc = (t.r_multiple || 0) < 0 ? C.RED : C.GREEN;
      const tc = { pullback: C.CYAN, breakout: C.MAGENTA, fresh_trend: C.YELLOW }[t.signal_type] || C.GRAY;
      const r = (t.r_multiple || 0).toFixed(2);
      const pnl = (t.pnl || 0).toFixed(2);

      console.log(
        `  ${C.GRAY}${String(i + 1).padStart(3)}${C.RESET} ${dc}${ds.padStart(5)}${C.RESET} ${tc}${(t.signal_type || '').padEnd(12)}${C.RESET} ${fmtDate(t.entry_time).padEnd(17)} ${C.WHITE}$${Number(t.entry_price || 0).toFixed(2).padStart(9)}${C.RESET} ${fmtDate(t.exit_time).padEnd(17)} ${C.WHITE}$${Number(t.exit_price || 0).toFixed(2).padStart(9)}${C.RESET} ${rc}${(r >= 0 ? '+' + r : r).padStart(7)}R${C.RESET} ${pc}${(pnl >= 0 ? '+' + pnl : pnl).padStart(10)}${C.RESET} ${C.GRAY}${(t.exit_reason || '').padEnd(12)}${C.RESET}`
      );
    }
  }

  // -- STRATEGY VERDICT --
  getVerdict(m, year);

  // -- FINAL SUMMARY CARD AT BOTTOM --
  printSummaryCard(m, year, cached, elapsed, source);
}

// ============================================================================
// MAIN RUN
// ============================================================================

async function run(symbol, year) {
  const t0 = Date.now();
  pruneCache();

  const { candles, cached, source } = await loadCachedOrFetch(symbol, year);
  if (!candles || candles.length === 0) {
    console.log(`${C.RED}No candles for ${symbol} ${year}. Check symbol name — Delta Exchange India uses BTCUSD not BTCUSDT.${C.RESET}`);
    return;
  }

  const formatted = sortCandles(candles).map(c => ({
    ts: Number(c.time), open: parseFloat(c.open), high: parseFloat(c.high),
    low: parseFloat(c.low), close: parseFloat(c.close), volume: parseFloat(c.volume)
  }));

  console.log(`  ${C.GRAY}Running Trend Rider backtest on ${formatted.length} candles...${C.RESET}`);
  const res = run_trend_rider_backtest(formatted, {});

  // Build trade rows with R-multiples, signal types, and exit reasons
  const tradeRows = [];
  let lastEntry = null;
  let equity = INITIAL_EQUITY;
  const equityCurve = [{ time: formatted.length ? formatted[0].ts : Math.floor(Date.now() / 1000), equity }];

  for (const t of res.trades) {
    if (t.entry) {
      lastEntry = Object.assign({}, t);
    }
    if (t.exit) {
      const exitTime = t.exit_time || t.ts || Math.floor(Date.now() / 1000);
      const exitPrice = t.exit_price || 0;
      let pnl = t.pnl !== undefined ? t.pnl : 0;
      const direction = lastEntry ? lastEntry.direction : t.direction || 'unknown';
      const entryPrice = lastEntry ? lastEntry.entry_price : (t.entry_price || 0);
      const signalType = lastEntry ? lastEntry.signal_type : (t.signal_type || '');
      const entryTime = lastEntry ? lastEntry.entry_time : (t.entry_time || null);
      const rMultiple = t.r_multiple || 0;
      const exitReason = t.exit_reason || '';

      if (pnl === 0 && lastEntry && entryPrice) {
        const qty = lastEntry.qty || 1;
        if (direction === 'long') pnl = (exitPrice - entryPrice) * qty;
        else if (direction === 'short') pnl = (entryPrice - exitPrice) * qty;
      }

      equity += pnl;
      tradeRows.push({
        entry_time: entryTime, entry_price: entryPrice,
        exit_time: exitTime, exit_price: exitPrice,
        direction, signal_type: signalType, pnl,
        r_multiple: rMultiple, exit_reason: exitReason
      });
      equityCurve.push({ time: exitTime, equity });
      lastEntry = null;
    }
  }

  tradeRows.sort((a, b) => (a.entry_time || 0) - (b.entry_time || 0));
  equityCurve.sort((a, b) => a.time - b.time);

  const elapsed = (Date.now() - t0) / 1000;
  const m = computeMetrics(tradeRows, equityCurve, INITIAL_EQUITY);

  displayResults(m, tradeRows, equityCurve, year, cached, elapsed, source);

  // Write results JSON and CSV
  try {
    const outFile = path.join(CACHE_DIR, `backtest_${symbol}_${year}.json`);
    fs.writeFileSync(outFile, JSON.stringify({
      symbol, year, initialEquity: INITIAL_EQUITY, equity: m.finalEquity,
      trades: tradeRows, equity_curve: equityCurve, stats: m
    }, null, 2), 'utf8');

    const csvFile = path.join(CACHE_DIR, `backtest_${symbol}_${year}.csv`);
    const header = 'entry_time,entry_price,exit_time,exit_price,direction,signal_type,r_multiple,pnl,exit_reason\n';
    const csvLines = tradeRows.map(r =>
      `${r.entry_time || ''},${r.entry_price || ''},${r.exit_time || ''},${r.exit_price || ''},${r.direction || ''},${r.signal_type || ''},${r.r_multiple || 0},${r.pnl || 0},${r.exit_reason || ''}`
    );
    fs.writeFileSync(csvFile, header + csvLines.join('\n'), 'utf8');
  } catch (e) {
    console.error('Failed to write backtest outputs', e);
  }
}

// ============================================================================
// ENTRY POINT
// ============================================================================

if (require.main === module) {
  const sym = process.env.BACKTEST_SYMBOL || process.argv[2] || 'BTCUSD';
  const year = process.env.BACKTEST_YEAR || process.argv[3] || new Date().getUTCFullYear();
  run(sym, year).catch(e => { console.error(e); process.exit(1); });
}

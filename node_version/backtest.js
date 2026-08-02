require('dotenv').config();
const fs = require('fs');
const path = require('path');
const axios = require('axios');
const { run_trend_rider_backtest } = require('./trend_rider_engine');

const CACHE_DIR = path.join(__dirname, 'cache');
if (!fs.existsSync(CACHE_DIR)) fs.mkdirSync(CACHE_DIR, { recursive: true });

function fmtDate(ts) {
  if (!ts) return '-';
  const d = new Date(ts * 1000);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  return `${y}-${m}-${day} ${hh}:${mm}`;
}

function sortCandles(candles) {
  return [...candles].sort((a, b) => {
    const at = Number(a.time ?? a.ts ?? 0);
    const bt = Number(b.time ?? b.ts ?? 0);
    return at - bt;
  });
}

function cachePath(symbol, year) {
  const safe = symbol.replace(/[^A-Za-z0-9_]/g, '_');
  return path.join(CACHE_DIR, `rider_${safe}_${year}.json`);
}

async function fetchCandlesDelta(symbol, start_ts, end_ts, resolution='4h') {
  const base = (process.env.DELTA_BASE_URL || 'https://api.india.delta.exchange').replace(/\/$/, '');
  const url = `${base}/v2/history/candles`;
  const params = { symbol, resolution, start: start_ts, end: end_ts };
  const r = await axios.get(url, { params, timeout: 20000 });
  return r.data.result || [];
}

async function loadCachedOrFetch(symbol, year) {
  const file = cachePath(symbol, year);
  if (fs.existsSync(file)) {
    try { return sortCandles(JSON.parse(fs.readFileSync(file, 'utf8'))); } catch(e){}
  }
  const start = Math.floor(new Date(`${year}-01-01T00:00:00Z`).getTime()/1000);
  const end = Math.floor(new Date(`${year}-12-31T23:59:59Z`).getTime()/1000);
  const candles = await fetchCandlesDelta(symbol, start, end, '4h');
  const sorted = sortCandles(candles);
  try { fs.writeFileSync(file, JSON.stringify(sorted), 'utf8'); } catch(e){}
  return sorted;
}

function prune_cache() {
  const maxMB = parseFloat(process.env.CACHE_MAX_SIZE_MB || '200');
  const maxAgeDays = parseInt(process.env.CACHE_MAX_AGE_DAYS || '90', 10);
  const files = fs.readdirSync(CACHE_DIR).map(f => {
    const p = path.join(CACHE_DIR, f);
    const stat = fs.statSync(p);
    return { path: p, mtime: stat.mtimeMs, size: stat.size };
  });
  const now = Date.now();
  // Evict by age
  for (const f of files) {
    const ageDays = (now - f.mtime) / (1000*60*60*24);
    if (ageDays > maxAgeDays) {
      try { fs.unlinkSync(f.path); } catch(e){}
    }
  }
  // Recompute total size
  const remaining = fs.readdirSync(CACHE_DIR).map(f => {
    const p = path.join(CACHE_DIR, f); const s = fs.statSync(p); return { path: p, mtime: s.mtimeMs, size: s.size };
  });
  let total = remaining.reduce((a,b)=>a+b.size, 0);
  const maxBytes = maxMB * 1024 * 1024;
  if (total <= maxBytes) return;
  // delete oldest until under limit
  remaining.sort((a,b)=>a.mtime - b.mtime);
  for (const f of remaining) {
    try { fs.unlinkSync(f.path); total -= f.size; } catch(e){}
    if (total <= maxBytes) break;
  }
}

async function run(symbol, year) {
  prune_cache();
  const candles = await loadCachedOrFetch(symbol, year);
  if (!candles || candles.length === 0) {
    console.log('No candles for', symbol, year); return;
  }
  // convert candles to format {ts, open, high, low, close, volume}
  const formatted = sortCandles(candles).map(c => ({ ts: Number(c.time), open: parseFloat(c.open), high: parseFloat(c.high), low: parseFloat(c.low), close: parseFloat(c.close), volume: parseFloat(c.volume) }));
  const res = run_trend_rider_backtest(formatted, {});

  // Build trade rows and equity curve
  const initialEquity = 10000;
  let equity = initialEquity;
  const equityCurve = [{ time: formatted.length ? formatted[0].ts : Math.floor(Date.now() / 1000), equity }];
  const tradeRows = [];
  let lastEntry = null;

  for (const t of res.trades) {
    if (t.entry) {
      lastEntry = Object.assign({}, t);
    }
    if (t.exit) {
      const exitTime = t.exit_time || t.ts || Math.floor(Date.now() / 1000);
      const exitPrice = t.exit_price || t.price || 0;
      let pnl = t.pnl !== undefined ? t.pnl : 0;
      let direction = lastEntry ? lastEntry.direction : 'unknown';
      let entryPrice = lastEntry ? lastEntry.entry_price : null;
      let size = lastEntry ? lastEntry.size : (t.size || 0);
      if (pnl === 0 && lastEntry && entryPrice !== null) {
        if (direction === 'long') pnl = (exitPrice - entryPrice) * size;
        else if (direction === 'short') pnl = (entryPrice - exitPrice) * size;
      }
      equity += pnl;
      tradeRows.push({ entry_time: lastEntry ? lastEntry.entry_time : null, entry_price: entryPrice, exit_time: exitTime, exit_price: exitPrice, direction, size, pnl });
      equityCurve.push({ time: exitTime, equity });
      lastEntry = null;
    }
  }

  tradeRows.sort((a, b) => (a.entry_time || 0) - (b.entry_time || 0) || (a.exit_time || 0) - (b.exit_time || 0));
  equityCurve.sort((a, b) => a.time - b.time);

  // Write results JSON and CSV
  try {
    const outFile = path.join(CACHE_DIR, `backtest_${symbol}_${year}.json`);
    fs.writeFileSync(outFile, JSON.stringify({ symbol, year, initialEquity, equity, trades: tradeRows, equity_curve: equityCurve }, null, 2), 'utf8');
    const csvFile = path.join(CACHE_DIR, `backtest_${symbol}_${year}.csv`);
    const header = 'entry_time,entry_price,exit_time,exit_price,direction,size,pnl\n';
    const lines = tradeRows.map(r => `${r.entry_time||''},${r.entry_price||''},${r.exit_time||''},${r.exit_price||''},${r.direction||''},${r.size||''},${r.pnl||0}`);
    fs.writeFileSync(csvFile, header + lines.join('\n'), 'utf8');
  } catch (e) {
    console.error('Failed to write backtest outputs', e);
  }
  
  // Compute metrics similar to Python get_metrics
  const tradesCompleted = tradeRows; // already paired
  const pnls = tradesCompleted.map(t => t.pnl || 0);
  const wins = pnls.filter(p => p > 0);
  const losses = pnls.filter(p => p <= 0);
  const totalTrades = tradesCompleted.length;
  const winRate = totalTrades ? (wins.length / totalTrades) * 100 : 0;
  const grossWin = wins.reduce((s, v) => s + v, 0);
  const grossLoss = Math.abs(losses.reduce((s, v) => s + v, 0));
  const profitFactor = grossLoss > 0 ? (grossWin / grossLoss) : (grossWin > 0 ? Infinity : 0);
  // avg pnl
  const totalPnl = pnls.reduce((s, v) => s + v, 0);
  const avgPnl = totalTrades ? totalPnl / totalTrades : 0;
  const avgWin = wins.length ? wins.reduce((s, v) => s + v, 0) / wins.length : 0;
  const avgLoss = losses.length ? losses.reduce((s, v) => s + v, 0) / losses.length : 0;

  // equity curve to daily returns
  const eqCurve = (res.equity_curve || equityCurve).slice().sort((a,b)=>a.time - b.time);
  // convert timestamps to Date objects and build map of date->equity last of day
  const dayMap = new Map();
  for (const p of eqCurve) {
    const d = new Date(p.time * 1000);
    const key = d.toISOString().slice(0,10);
    dayMap.set(key, p.equity);
  }
  const dailyEquities = Array.from(dayMap.entries()).sort((a,b)=>a[0].localeCompare(b[0])).map(x=>x[1]);
  const dailyReturns = [];
  for (let i=1;i<dailyEquities.length;i++) dailyReturns.push((dailyEquities[i] - dailyEquities[i-1]) / dailyEquities[i-1]);
  const mean = arr => arr.reduce((s,v)=>s+v,0)/(arr.length||1);
  const std = arr => {
    const m = mean(arr); return Math.sqrt(arr.reduce((s,v)=>s+(v-m)*(v-m),0)/(arr.length-1 || 1));
  };
  const sharpe = dailyReturns.length ? (mean(dailyReturns)/ (std(dailyReturns)||1) * Math.sqrt(365)) : 0;
  const downside = dailyReturns.filter(r=>r<0);
  const sortino = downside.length ? (mean(dailyReturns)/(std(downside)||1) * Math.sqrt(365)) : 0;

  // max drawdown percent
  let peak = -Infinity; let maxDdPct = 0;
  for (const p of eqCurve) {
    if (p.equity > peak) peak = p.equity;
    const dd = (p.equity - peak) / (peak || 1);
    if (dd < maxDdPct) maxDdPct = dd;
  }
  const maxDrawdown = Math.abs(maxDdPct) * 100;

  // CAGR
  let cagr = 0;
  if (eqCurve.length >= 2) {
    const start = new Date(eqCurve[0].time * 1000);
    const end = new Date(eqCurve[eqCurve.length-1].time * 1000);
    const days = Math.max(1, Math.floor((end - start) / (1000*60*60*24)));
    const years = days / 365.25;
    const finalEquity = eqCurve[eqCurve.length-1].equity;
    cagr = years > 0 && finalEquity > 0 ? (Math.pow(finalEquity/initialEquity, 1/years)-1)*100 : 0;
  }

  const stats = {
    totalTrades,
    wins: wins.length,
    losses: losses.length,
    winRate: Number(winRate.toFixed(2)),
    totalPnl: Number(totalPnl.toFixed(2)),
    avgPnl: Number(avgPnl.toFixed(2)),
    avgWin: Number(avgWin.toFixed(2)),
    avgLoss: Number(avgLoss.toFixed(2)),
    profitFactor: Number((profitFactor === Infinity ? Infinity : Number(profitFactor.toFixed(2)))),
    maxDrawdown: Number(maxDrawdown.toFixed(2)),
    sharpe: Number(sharpe.toFixed(2)),
    sortino: Number(sortino.toFixed(2)),
    cagr: Number(cagr.toFixed(2)),
  };

  const totalReturnPct = Number((((equity - initialEquity) / initialEquity) * 100).toFixed(2));
  const netProfit = Number((equity - initialEquity).toFixed(2));

  console.log();
  console.log(`  +==============================================================+`);
  console.log(`  |  ANNUAL BACKTEST OVERVIEW -- YEAR ${year}                           |`);
  console.log(`  +==============================================================+`);
  console.log(`  TOTAL RETURN FOR ${year}:     ${totalReturnPct.toFixed(1)}%  (${netProfit.toFixed(2)} USD)`);
  console.log(`  OVERALL WIN RATE:          ${stats.winRate.toFixed(1)}%  (${stats.totalTrades} total trades)`);
  console.log(`  PROFIT FACTOR:             ${Number.isFinite(stats.profitFactor) ? stats.profitFactor.toFixed(2) : 'Infinity'}`);
  console.log(`  MAX DRAWDOWN:              ${stats.maxDrawdown.toFixed(1)}%`);
  console.log(`  FINAL EQUITY:              $${equity.toFixed(2)}  (from $${initialEquity.toFixed(2)})`);

  if (tradeRows.length) {
    console.log();
    console.log(`  TRADE LOG (${tradeRows.length} trades)`);
    console.log(`  #   Dir   Type       Entry Date        Entry$     Exit Date         Exit$        PnL`);
    tradeRows.forEach((t, i) => {
      const dir = (t.direction || '').toUpperCase();
      console.log(
        `  ${String(i + 1).padStart(3)} ${dir.padStart(5)}  ${String(t.size || '').padStart(4)}  ${fmtDate(t.entry_time).padEnd(16)}  ${String(Number(t.entry_price || 0).toFixed(2)).padStart(10)}  ${fmtDate(t.exit_time).padEnd(16)}  ${String(Number(t.exit_price || 0).toFixed(2)).padStart(10)}  ${String(Number(t.pnl || 0).toFixed(2)).padStart(10)}`
      );
    });
  }

  console.log();
  console.log('Backtest stats:', stats);

  // append stats to JSON output
  try {
    const outFile = path.join(CACHE_DIR, `backtest_${symbol}_${year}.json`);
    const cur = JSON.parse(fs.readFileSync(outFile, 'utf8'));
    cur.stats = stats;
    fs.writeFileSync(outFile, JSON.stringify(cur, null, 2), 'utf8');
  } catch (e) {
    // ignore
  }
}

if (require.main === module) {
  const sym = process.env.BACKTEST_SYMBOL || process.argv[2] || 'BTCUSDT';
  const year = process.env.BACKTEST_YEAR || process.argv[3] || new Date().getUTCFullYear();
  run(sym, year).catch(e=>{ console.error(e); process.exit(1); });
}

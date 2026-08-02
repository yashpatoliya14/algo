/**
 * Delta Exchange Live & Paper Trading Bot — Node.js
 * ====================================================
 * Full port of Python delta_trader.py with:
 * - Delta Exchange REST API integration (orders, positions, leverage)
 * - Signal scanning on 4H candles
 * - Entry execution (dry run + live)
 * - Active position management with dynamic trailing stop
 * - Auto exit on trailing stop hit
 * - Signal deduplication (one notification per candle per signal)
 * - Multi-symbol support
 * - Telegram notifications (entry + exit + started)
 *
 * Requirements:
 *     npm install axios dotenv
 *
 * Setup:
 *     1. Copy `.env.example` to `.env`
 *     2. Fill in DELTA_API_KEY, DELTA_API_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
 *     3. Run: `node delta_trader.js`
 */

require('dotenv').config();
const DeltaClient = require('./delta_client');
const TelegramNotifier = require('./telegram_notifier');
const { toCanonical, toDelta } = require('./symbol_utils');
const { compute_indicators: computeIndicators } = require('./trend_rider_engine');

// ============================================================================
// HELPER UTILITIES
// ============================================================================

function stripQuotes(s) {
  if (!s) return '';
  s = s.trim();
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
    return s.slice(1, -1);
  }
  return s;
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

// ============================================================================
// STRATEGY PARAMETERS (matching Python TrendRiderParams defaults)
// ============================================================================

const DEFAULT_PARAMS = {
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
  trail_pct_activation: 1.0,
  trail_pct_distance: 0.4,
  risk_pct: 1.5,
};

// ============================================================================
// DELTA TRADER CLASS
// ============================================================================

class DeltaTrader {
  constructor() {
    // Load config from environment
    this.apiKey = process.env.DELTA_API_KEY || '';
    this.apiSecret = process.env.DELTA_API_SECRET || '';
    this.baseUrl = process.env.DELTA_BASE_URL || 'https://api.india.delta.exchange';

    // Symbol parsing
    const envSymbol = stripQuotes(process.env.SYMBOL || 'BTCUSD');
    this.timeframe = process.env.TIMEFRAME || '4h';
    try {
      this.symbolCanonical = toCanonical(envSymbol);
      this.symbol = toDelta(this.symbolCanonical);
    } catch (_) {
      this.symbolCanonical = envSymbol;
      this.symbol = envSymbol;
    }

    this.riskPct = parseFloat(process.env.RISK_PCT || '1.5');
    this.leverage = parseInt(process.env.LEVERAGE || '5', 10);
    this.dryRun = (process.env.DRY_RUN || 'true').toLowerCase() === 'true';
    this.pollInterval = parseInt(process.env.POLL_INTERVAL_SEC || '60', 10);

    // Strategy parameters
    this.params = {
      ...DEFAULT_PARAMS,
      risk_pct: this.riskPct,
      trail_pct_activation: parseFloat(process.env.TRAIL_PCT_ACTIVATION || '1.0'),
      trail_pct_distance: parseFloat(process.env.TRAIL_PCT_DISTANCE || '0.4'),
    };

    // Initialize API client and notifier
    this.client = new DeltaClient(this.apiKey, this.apiSecret, this.baseUrl);
    this.notifier = new TelegramNotifier();

    // State tracking
    this.activePosition = null;   // { direction, entryPrice, stopPrice, trailStop, peakPrice, size, type }
    this.symbols = [];

    // Track already-notified signals so we don't spam Telegram
    this._notifiedSignals = new Set();
  }

  printBanner() {
    const modeStr = this.dryRun
      ? '\x1b[93m[DRY RUN / PAPER TRADING]\x1b[0m'
      : '\x1b[91m[LIVE REAL TRADING]\x1b[0m';
    console.log();
    console.log('='.repeat(65));
    console.log(`   DELTA EXCHANGE LIVE TRADER -- 4H TREND RIDER ${modeStr}`);
    console.log('='.repeat(65));
    console.log(`  Symbol:                ${this.symbolCanonical}`);
    console.log(`  Timeframe:             ${this.timeframe}`);
    console.log(`  Risk Per Trade:        ${this.riskPct}%`);
    console.log(`  Leverage:              ${this.leverage}x`);
    console.log(`  Trailing Trigger:      ${this.params.trail_pct_activation}% move -> ${this.params.trail_pct_distance}% trail`);
    console.log(`  API Base URL:          ${this.baseUrl}`);
    console.log('='.repeat(65));
    console.log();
  }

  /**
   * Fetch 4H candles from Delta Exchange API.
   * @param {number} limit
   * @returns {Promise<Array<object>>}
   */
  async fetchRecentCandles(limit = 150) {
    const nowTs = Math.floor(Date.now() / 1000);
    const startTs = nowTs - (limit * 4 * 3600);

    const rawCandles = await this.client.getCandles(this.symbol, this.timeframe, startTs, nowTs);
    if (!rawCandles || rawCandles.length === 0) {
      throw new Error(`No candles returned for ${this.symbol} (${this.timeframe})`);
    }

    // Convert to sorted array of { ts, open, high, low, close, volume }
    const candles = rawCandles
      .map(c => ({
        ts: Number(c.time),
        open: parseFloat(c.open),
        high: parseFloat(c.high),
        low: parseFloat(c.low),
        close: parseFloat(c.close),
        volume: parseFloat(c.volume),
      }))
      .sort((a, b) => a.ts - b.ts);

    // Remove duplicates by ts
    const seen = new Set();
    const unique = candles.filter(c => {
      if (seen.has(c.ts)) return false;
      seen.add(c.ts);
      return true;
    });

    return unique;
  }

  /**
   * Evaluate Trend Rider signals on the latest completed candle.
   * @param {Array<object>} candles
   * @returns {{ signal: string|null, signalType: string, currBar: object|null }}
   */
  evaluateSignals(candles) {
    const d = computeIndicators(candles, this.params);
    const rows = d.filter(r =>
      r.ema_fast && r.ema_slow && r.atr && r.st_dir !== undefined && !isNaN(r.donchian_high)
    );

    if (rows.length < 5) {
      return { signal: null, signalType: '', currBar: null };
    }

    const curr = rows[rows.length - 2]; // latest COMPLETED candle
    const prev = rows[rows.length - 3]; // previous completed candle

    const emaVal = curr.ema_fast;
    let signal = null;
    let signalType = '';

    // Long entry check
    if (curr.trend_bull && curr.ema_fast_slope) {
      const isPullback = (prev.low <= emaVal * 1.003) && (curr.close > emaVal) && (curr.close > curr.open);
      const isBreakout = (curr.close > curr.donchian_high) && (curr.rsi < this.params.rsi_ob);
      const isStFlip = curr.st_recent_bull && (curr.close > emaVal);

      if (isPullback) { signal = 'long'; signalType = 'pullback'; }
      else if (isBreakout) { signal = 'long'; signalType = 'breakout'; }
      else if (isStFlip) { signal = 'long'; signalType = 'fresh_trend'; }
    }
    // Short entry check
    else if (curr.trend_bear && curr.ema_fast_slope_short) {
      const isPullback = (prev.high >= emaVal * 0.997) && (curr.close < emaVal) && (curr.close < curr.open);
      const isBreakout = (curr.close < curr.donchian_low) && (curr.rsi > this.params.rsi_os);
      const isStFlip = curr.st_recent_bear && (curr.close < emaVal);

      if (isPullback) { signal = 'short'; signalType = 'pullback'; }
      else if (isBreakout) { signal = 'short'; signalType = 'breakout'; }
      else if (isStFlip) { signal = 'short'; signalType = 'fresh_trend'; }
    }

    return { signal, signalType, currBar: curr };
  }

  /**
   * Generate a unique key for signal deduplication based on candle timestamp.
   * @param {string} signal
   * @param {string} signalType
   * @param {object} currBar
   * @returns {string}
   */
  _signalKey(signal, signalType, currBar) {
    const candleTs = currBar && currBar.ts ? currBar.ts : Math.floor(Date.now() / 1000);
    return `${this.symbolCanonical}|${signal}|${signalType}|${candleTs}`;
  }

  /**
   * Single poll & trading check cycle.
   */
  async runTradingCycle() {
    const timestampStr = new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
    console.log(`[${timestampStr}] Checking market & signals...`);

    let candles, currPrice;
    try {
      candles = await this.fetchRecentCandles(100);
      const ticker = await this.client.getTicker(this.symbol);
      currPrice = parseFloat(ticker.mark_price || candles[candles.length - 1].close);
    } catch (e) {
      console.log(`  [ERROR] Failed to fetch market data: ${e.message}`);
      return;
    }

    const { signal, signalType, currBar } = this.evaluateSignals(candles);

    if (currBar) {
      console.log(`  Current Price: $${round2(currPrice).toLocaleString()} | 4H Bar Close: $${round2(currBar.close).toLocaleString()}`);
      console.log(`  EMA21: $${round2(currBar.ema_fast).toLocaleString()} | Supertrend: ${currBar.st_dir} (${currBar.st_dir === 1 ? 'BULL' : 'BEAR'})`);
    }

    if (!signal) {
      console.log('  No new signal on current closed 4H candle.');
    }

    // Check existing active position
    let posSize = 0;
    if (!this.dryRun) {
      try {
        const positions = await this.client.getPositions(this.symbol);
        const pos = positions && positions.length > 0 ? positions[0] : null;
        posSize = pos ? parseFloat(pos.size || 0) : 0;
      } catch (e) {
        console.log(`  [WARN] Failed to fetch positions: ${e.message}`);
        posSize = 0;
      }
    } else {
      posSize = this.activePosition ? this.activePosition.size : 0;
    }

    // Position Management & Dynamic Trailing Stop
    if (posSize !== 0 || this.activePosition !== null) {
      await this._manageActivePosition(currPrice, currBar);
    } else if (signal !== null) {
      // Duplicate signal guard: same candle + same signal = skip repeat
      const sigKey = this._signalKey(signal, signalType, currBar);
      if (this._notifiedSignals.has(sigKey)) {
        console.log(`  Signal already processed for this candle, skipping. (key=${sigKey})`);
      } else {
        this._notifiedSignals.add(sigKey);
        // Prune old keys to prevent memory leak (keep last 50)
        if (this._notifiedSignals.size > 50) {
          const arr = Array.from(this._notifiedSignals);
          this._notifiedSignals = new Set(arr.slice(-50));
        }
        await this._executeEntry(signal, signalType, currBar, currPrice);
      }
    }
  }

  /**
   * Calculate size, place market order and initial stop loss.
   * @param {string} direction - 'long' or 'short'
   * @param {string} signalType
   * @param {object} currBar
   * @param {number} currentPrice
   */
  async _executeEntry(direction, signalType, currBar, currentPrice) {
    const atrVal = currBar.atr;
    const stopDist = this.params.stop_atr_mult * atrVal;

    let stopPrice, side;
    if (direction === 'long') {
      stopPrice = currentPrice - stopDist;
      side = 'buy';
    } else {
      stopPrice = currentPrice + stopDist;
      side = 'sell';
    }

    // Position sizing
    let equity = 10000.0; // default paper capital
    if (!this.dryRun) {
      try {
        const balances = await this.client.getBalances();
        if (balances && balances.length > 0) {
          equity = parseFloat(balances[0].balance || 10000.0);
        }
      } catch (e) {
        console.log(`  [WARN] Could not fetch balance, using default: ${e.message}`);
      }
    }

    const riskAmount = equity * (this.riskPct / 100.0);
    const contracts = Math.max(1, Math.floor(riskAmount / stopDist));

    console.log(`\n  \x1b[96m>>> EXECUTING ENTRY <<<\x1b[0m`);
    console.log(`  Direction:   ${direction.toUpperCase()}`);
    console.log(`  Side:        ${side.toUpperCase()}`);
    console.log(`  Contracts:   ${contracts}`);
    console.log(`  Entry Price: $${round2(currentPrice).toLocaleString()}`);
    console.log(`  Stop Loss:   $${round2(stopPrice).toLocaleString()} (Dist: $${round2(stopDist).toLocaleString()})`);

    const candleTime = fmtTime(currBar.ts);

    if (this.dryRun) {
      console.log('  \x1b[93m[DRY RUN] Order simulated successfully!\x1b[0m');
      this.activePosition = {
        direction,
        entryPrice: currentPrice,
        stopPrice,
        trailStop: stopPrice,
        peakPrice: currentPrice,
        size: contracts,
        type: signalType,
      };
      try {
        await this.notifier.signalDetailed(
          this.symbolCanonical, direction, signalType,
          currentPrice, currentPrice, contracts, stopPrice,
          this.riskPct, candleTime,
          this.params.trail_pct_activation, this.params.trail_pct_distance,
          'No fixed TP; exit on trailing stop or trend reversal'
        );
      } catch (_) {
        try {
          await this.notifier.execution(this.symbolCanonical, direction, contracts, currentPrice, stopPrice);
        } catch (__) { /* ignore */ }
      }
    } else {
      try {
        // Set leverage
        await this.client.setLeverage(this.symbol, this.leverage);
        // Place market entry order
        const entryRes = await this.client.placeOrder(this.symbol, contracts, side, 'market_order');
        console.log(`  [LIVE ORDER] Entry Order Placed: ${(entryRes.result || {}).id || 'OK'}`);

        // Place stop loss order
        const exitSide = direction === 'long' ? 'sell' : 'buy';
        const stopRes = await this.client.placeOrder(this.symbol, contracts, exitSide, 'stop_market_order', stopPrice);
        console.log(`  [LIVE ORDER] Stop Loss Placed: ${(stopRes.result || {}).id || 'OK'}`);

        this.activePosition = {
          direction,
          entryPrice: currentPrice,
          stopPrice,
          trailStop: stopPrice,
          peakPrice: currentPrice,
          size: contracts,
          type: signalType,
        };

        try {
          await this.notifier.signalDetailed(
            this.symbolCanonical, direction, signalType,
            currentPrice, currentPrice, contracts, stopPrice,
            this.riskPct, candleTime,
            this.params.trail_pct_activation, this.params.trail_pct_distance,
            'No fixed TP; exit on trailing stop or trend reversal'
          );
        } catch (_) {
          try {
            await this.notifier.execution(this.symbolCanonical, direction, contracts, currentPrice, stopPrice);
          } catch (__) { /* ignore */ }
        }
      } catch (e) {
        console.log(`  \x1b[91m[ORDER FAILED]\x1b[0m ${e.message}`);
      }
    }
  }

  /**
   * Update trailing stop when price moves 1% in profit -> trail 0.4%.
   * Auto exit when trailing stop hit.
   * @param {number} currentPrice
   * @param {object} currBar
   */
  async _manageActivePosition(currentPrice, currBar) {
    const pos = this.activePosition;
    if (!pos) return;

    const direction = pos.direction;
    const entryPx = pos.entryPrice;

    if (direction === 'long') {
      pos.peakPrice = Math.max(pos.peakPrice, currentPrice);
      const pctMove = (pos.peakPrice - entryPx) / entryPx * 100.0;

      // 1% activation -> 0.4% trailing stop
      if (pctMove >= this.params.trail_pct_activation) {
        const newTrail = pos.peakPrice * (1.0 - this.params.trail_pct_distance / 100.0);
        if (newTrail > pos.trailStop) {
          console.log(`  \x1b[92m[TRAILING STOP TIGHTENED]\x1b[0m Peak: $${round2(pos.peakPrice).toLocaleString()} (+${pctMove.toFixed(2)}%) | Trail Stop: $${round2(newTrail).toLocaleString()}`);
          pos.trailStop = newTrail;
        }
      }

      // Exit check
      if (currentPrice <= pos.trailStop) {
        const pnl = (pos.trailStop - entryPx) * pos.size;
        console.log(`  \x1b[91m[POSITION CLOSED]\x1b[0m Trailing stop hit at $${round2(currentPrice).toLocaleString()} | PnL: $${pnl >= 0 ? '+' : ''}${round2(pnl).toLocaleString()}`);
        if (!this.dryRun) {
          try {
            await this.client.cancelAllOrders(this.symbol);
          } catch (_) { /* ignore */ }
          try {
            await this.client.placeOrder(this.symbol, pos.size, 'sell', 'market_order');
          } catch (_) { /* ignore */ }
        }
        this.activePosition = null;
        try {
          await this.notifier.exit(this.symbolCanonical, direction, currentPrice, pnl);
        } catch (_) { /* ignore */ }
      }

    } else {
      // Short position
      pos.peakPrice = Math.min(pos.peakPrice, currentPrice);
      const pctMove = (entryPx - pos.peakPrice) / entryPx * 100.0;

      if (pctMove >= this.params.trail_pct_activation) {
        const newTrail = pos.peakPrice * (1.0 + this.params.trail_pct_distance / 100.0);
        if (newTrail < pos.trailStop) {
          console.log(`  \x1b[92m[TRAILING STOP TIGHTENED]\x1b[0m Peak: $${round2(pos.peakPrice).toLocaleString()} (+${pctMove.toFixed(2)}%) | Trail Stop: $${round2(newTrail).toLocaleString()}`);
          pos.trailStop = newTrail;
        }
      }

      if (currentPrice >= pos.trailStop) {
        const pnl = (entryPx - pos.trailStop) * pos.size;
        console.log(`  \x1b[91m[POSITION CLOSED]\x1b[0m Trailing stop hit at $${round2(currentPrice).toLocaleString()} | PnL: $${pnl >= 0 ? '+' : ''}${round2(pnl).toLocaleString()}`);
        if (!this.dryRun) {
          try {
            await this.client.cancelAllOrders(this.symbol);
          } catch (_) { /* ignore */ }
          try {
            await this.client.placeOrder(this.symbol, pos.size, 'buy', 'market_order');
          } catch (_) { /* ignore */ }
        }
        this.activePosition = null;
        try {
          await this.notifier.exit(this.symbolCanonical, direction, currentPrice, pnl);
        } catch (_) { /* ignore */ }
      }
    }
  }

  /**
   * Parse symbols from environment.
   * @returns {Array<{delta: string, canon: string}>}
   */
  parseSymbols() {
    const symbolsEnv = stripQuotes(process.env.SYMBOLS || '');
    const selected = [];

    if (symbolsEnv) {
      for (const part of symbolsEnv.split(',')) {
        const s = part.trim();
        if (!s) continue;
        try {
          const canon = toCanonical(s);
          const delta = toDelta(canon);
          selected.push({ delta, canon });
        } catch (e) {
          console.log(`  Invalid SYMBOLS entry ignored: ${s} (${e.message})`);
        }
      }
    } else {
      // Fallback to single SYMBOL env var
      const envSymbol = stripQuotes(process.env.SYMBOL || '').trim();
      if (envSymbol) {
        try {
          const canon = toCanonical(envSymbol);
          const delta = toDelta(canon);
          selected.push({ delta, canon });
        } catch (e) {
          console.log(`  Invalid SYMBOL env ignored: ${envSymbol} (${e.message})`);
        }
      } else {
        // Final fallback to pre-initialized single symbol
        selected.push({ delta: this.symbol, canon: this.symbolCanonical });
      }
    }

    // Ensure at least one symbol
    if (selected.length === 0) {
      console.log('No valid symbols parsed from environment — using default symbol.');
      selected.push({ delta: this.symbol, canon: this.symbolCanonical });
    }

    return selected;
  }

  /**
   * Continuous polling loop — fully automated, no terminal input needed.
   */
  async startLoop() {
    console.log();
    console.log('Starting trader using SYMBOLS from environment only.');

    this.symbols = this.parseSymbols();

    // Sync time offset
    await this.client.syncTimeOffset();

    // Notify selected symbols
    try {
      const symbolsList = this.symbols.map(s => s.canon);
      await this.notifier.started(symbolsList, this.timeframe, this.dryRun, this.riskPct, this.leverage);
    } catch (_) { /* ignore */ }

    this.printBanner();
    console.log(`Starting continuous polling loop for ${this.symbols.length} symbols (every ${this.pollInterval}s)... Press Ctrl+C to stop.`);

    const sleep = (ms) => new Promise(r => setTimeout(r, ms));

    try {
      while (true) {
        for (const sym of this.symbols) {
          try {
            // Set current symbol and run a single check
            this.symbol = sym.delta;
            this.symbolCanonical = sym.canon;
            await this.runTradingCycle();
          } catch (e) {
            console.log(`Unexpected error for ${sym.canon}: ${e.message}`);
          }
          // Small pause between symbols
          await sleep(500);
        }

        // Wait until next full polling cycle
        await sleep(this.pollInterval * 1000);
      }
    } catch (e) {
      if (e.message && e.message.includes('SIGINT')) {
        console.log('\nStopping trader bot. Goodbye!');
      } else {
        throw e;
      }
    }
  }
}

// ============================================================================
// MAIN
// ============================================================================

// Handle Ctrl+C gracefully
process.on('SIGINT', () => {
  console.log('\nStopping trader bot. Goodbye!');
  process.exit(0);
});

const trader = new DeltaTrader();
trader.startLoop().catch(e => {
  console.error('Fatal error:', e);
  process.exit(1);
});

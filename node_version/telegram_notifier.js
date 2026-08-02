const axios = require('axios');
const chatId = process.env.TELEGRAM_CHAT_ID || '';
const token = process.env.TELEGRAM_BOT_TOKEN || '';

async function post(method, payload) {
  if (!token || !chatId) return null;
  const url = `https://api.telegram.org/bot${token}/${method}`;
  try {
    const res = await axios.post(url, payload, { timeout: 10000 });
    return res.data;
  } catch (e) {
    return null;
  }
}

class TelegramNotifier {
  constructor() {
    this.chatId = chatId;
    this.onSignal = (process.env.TELEGRAM_ON_SIGNAL || 'true').toLowerCase() === 'true';
    this.onExec = (process.env.TELEGRAM_ON_EXECUTION || 'true').toLowerCase() === 'true';
    this.onExit = (process.env.TELEGRAM_ON_EXIT || 'true').toLowerCase() === 'true';
  }

  async send(text) {
    if (!this.chatId || !token) return null;
    const payload = { chat_id: this.chatId, text, disable_notification: false };
    return await post('sendMessage', payload);
  }

  async started(symbols, timeframe, dryRun, riskPct, leverage) {
    const mode = dryRun ? 'DRY RUN / PAPER' : 'LIVE';
    const txt = `Trader Started\nMode: ${mode}\nTimeframe: ${timeframe}\nSymbols: ${symbols.join(', ')}\nRisk %: ${riskPct}%\nLeverage: ${leverage}x`;
    return await this.send(txt);
  }

  async signalDetailed(symbol, direction, signalType, signalPrice, entryPrice, size, stopPrice, riskPct, candleTime = '', trailActivation = null, trailDistance = null, tpNote = '') {
    if (!this.onSignal) return null;
    const lines = [
      'Signal',
      `Symbol: ${symbol}`,
      `Direction: ${direction.toUpperCase()}`,
      `Type: ${signalType}`,
    ];
    if (candleTime) lines.push(`Candle Time: ${candleTime}`);
    lines.push(
      `Signal Price: ${Number(signalPrice).toFixed(2)}`,
      `Suggested Entry: ${Number(entryPrice).toFixed(2)}`,
      `Size: ${size}`,
      `Stop Loss: ${Number(stopPrice).toFixed(2)}`,
      `Risk %: ${riskPct}%`
    );
    if (trailActivation !== null && trailDistance !== null) {
      lines.push(`Trail: activate after +${Number(trailActivation).toFixed(2)}% move, then trail ${Number(trailDistance).toFixed(2)}% behind peak`);
    }
    lines.push(`TP / Exit Plan: ${tpNote || 'No fixed TP; exit on trailing stop or trend reversal'}`);
    const txt = lines.join('\n');
    return await this.send(txt);
  }

  async execution(symbol, direction, size, entryPrice, stopPrice) {
    if (!this.onExec) return null;
    const txt = `Execution\nSymbol: ${symbol}\nDirection: ${direction.toUpperCase()}\nSize: ${size}\nEntry: ${entryPrice.toFixed(2)}\nStop: ${stopPrice.toFixed(2)}`;
    return await this.send(txt);
  }

  async exit(symbol, direction, exitPrice, pnl) {
    if (!this.onExit) return null;
    const txt = `Exit\nSymbol: ${symbol}\nDirection: ${direction.toUpperCase()}\nExit Price: ${exitPrice.toFixed(2)}\nPnL: ${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}`;
    return await this.send(txt);
  }
}

module.exports = TelegramNotifier;

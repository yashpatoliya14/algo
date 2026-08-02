/**
 * Delta Exchange REST API v2 Client for Node.js
 * ================================================
 * Full port of Python DeltaClient with HMAC auth, time sync, and retry logic.
 */

const crypto = require('crypto');
const axios = require('axios');

class DeltaClient {
  /**
   * @param {string} apiKey
   * @param {string} apiSecret
   * @param {string} baseUrl
   */
  constructor(apiKey, apiSecret, baseUrl = 'https://api.india.delta.exchange') {
    this.apiKey = apiKey;
    this.apiSecret = apiSecret;
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.timeOffset = 0;
    this._retrying = false;
  }

  /**
   * Sync local clock with Delta Exchange server time.
   */
  async syncTimeOffset() {
    try {
      const resp = await axios.get(`${this.baseUrl}/v2/products`, { timeout: 5000 });
      const dateHeader = resp.headers['date'];
      if (dateHeader) {
        const serverTime = Math.floor(new Date(dateHeader).getTime() / 1000);
        this.timeOffset = serverTime - Math.floor(Date.now() / 1000);
      }
    } catch (_) {
      // ignore
    }
  }

  /**
   * Generate HMAC SHA256 signature for Delta REST API v2.
   * @param {string} method
   * @param {string} path
   * @param {string} queryString
   * @param {string} payload
   * @returns {{timestamp: string, signature: string}}
   */
  _generateSignature(method, path, queryString = '', payload = '') {
    const timestamp = String(Math.floor(Date.now() / 1000) + this.timeOffset);
    const signatureData = method + timestamp + path + queryString + payload;
    const signature = crypto
      .createHmac('sha256', this.apiSecret)
      .update(signatureData)
      .digest('hex');
    return { timestamp, signature };
  }

  /**
   * Internal request method with auth, error handling, and retry.
   * @param {string} method - HTTP method (GET, POST, DELETE, PUT)
   * @param {string} path - API path (e.g. /v2/orders)
   * @param {object} [params] - Query params
   * @param {object} [payload] - JSON body
   * @param {boolean} [auth=true] - Whether to include auth headers
   * @returns {Promise<object>}
   */
  async _request(method, path, { params = null, payload = null, auth = true } = {}) {
    let url = this.baseUrl + path;
    let queryString = '';
    let payloadStr = '';

    if (params) {
      const sorted = Object.keys(params).sort().map(k => `${k}=${params[k]}`).join('&');
      queryString = '?' + sorted;
      url += queryString;
    }

    if (payload) {
      payloadStr = JSON.stringify(payload);
    }

    const headers = { 'Content-Type': 'application/json' };

    if (auth && this.apiKey && this.apiSecret) {
      const { timestamp, signature } = this._generateSignature(
        method.toUpperCase(), path, queryString, payloadStr
      );
      headers['api-key'] = this.apiKey;
      headers['timestamp'] = timestamp;
      headers['signature'] = signature;
    }

    try {
      const config = {
        method: method.toUpperCase(),
        url,
        headers,
        timeout: 15000,
      };
      if (payload) {
        config.data = payloadStr;
      }

      const resp = await axios(config);
      return resp.data;
    } catch (e) {
      if (e.response) {
        try {
          const errJson = e.response.data;
          const errInfo = errJson.error || {};
          const errCode = errInfo.code;

          // Handle clock skew (expired_signature) by adjusting offset and retrying once
          if (errCode === 'expired_signature') {
            const serverTime = (errInfo.context || {}).server_time;
            if (serverTime && !this._retrying) {
              this.timeOffset = parseInt(serverTime) - Math.floor(Date.now() / 1000);
              this._retrying = true;
              try {
                return await this._request(method, path, { params, payload, auth });
              } finally {
                this._retrying = false;
              }
            }
          }

          // Handle IP Whitelist Restriction
          if (errCode === 'ip_not_whitelisted_for_api_key') {
            const clientIp = (errInfo.context || {}).client_ip || 'Unknown';
            console.log(`\n\x1b[93m[DELTA API ERROR] IP Whitelist Restriction!\x1b[0m`);
            console.log(`  Your current public IP: \x1b[1m\x1b[96m${clientIp}\x1b[0m`);
            console.log(`  \x1b[97mAction Required: Add IP '${clientIp}' to your Delta Exchange API Key whitelist, or remove IP restrictions in your Delta API Key settings.\x1b[0m\n`);
          }
        } catch (_) {
          // ignore parse errors
        }

        console.log(`[DELTA API ERROR] ${method} ${path}: ${e.message}`);
        console.log(`  Response Body: ${JSON.stringify(e.response.data)}`);
      } else {
        console.log(`[DELTA API ERROR] ${method} ${path}: ${e.message}`);
      }
      throw e;
    }
  }

  // ======================== Public Endpoints ========================

  /**
   * Fetch historical candle OHLCV data.
   * @param {string} symbol
   * @param {string} resolution - e.g. '4h'
   * @param {number} [startTime]
   * @param {number} [endTime]
   * @returns {Promise<Array>}
   */
  async getCandles(symbol, resolution = '4h', startTime = null, endTime = null) {
    const params = { symbol, resolution };
    if (startTime) params.start = startTime;
    if (endTime) params.end = endTime;

    const res = await this._request('GET', '/v2/history/candles', { params, auth: false });
    return res.result || [];
  }

  /**
   * Fetch current ticker price.
   * @param {string} symbol
   * @returns {Promise<object>}
   */
  async getTicker(symbol) {
    const res = await this._request('GET', `/v2/tickers/${symbol}`, { auth: false });
    return res.result || {};
  }

  // ======================== Private Endpoints ========================

  /**
   * Fetch wallet balances.
   * @returns {Promise<Array>}
   */
  async getBalances() {
    const res = await this._request('GET', '/v2/wallet/balances', { auth: true });
    return res.result || [];
  }

  /**
   * Fetch open positions.
   * @param {string} [symbol]
   * @returns {Promise<Array>}
   */
  async getPositions(symbol = null) {
    const params = symbol ? { symbol } : null;
    const res = await this._request('GET', '/v2/positions/margined', { params, auth: true });
    return res.result || [];
  }

  /**
   * Set position leverage.
   * @param {string} symbol
   * @param {number} leverage
   * @returns {Promise<object>}
   */
  async setLeverage(symbol, leverage) {
    const payload = { product_symbol: symbol, leverage: String(leverage) };
    return this._request('POST', '/v2/products/leverage', { payload, auth: true });
  }

  /**
   * Place an order on Delta Exchange.
   * @param {string} symbol
   * @param {number} size - Number of contracts
   * @param {string} side - 'buy' or 'sell'
   * @param {string} [orderType='market_order'] - 'market_order' or 'stop_market_order'
   * @param {number} [stopPrice] - Required for stop_market_order
   * @returns {Promise<object>}
   */
  async placeOrder(symbol, size, side, orderType = 'market_order', stopPrice = null) {
    const payload = {
      product_symbol: symbol,
      size: Math.floor(size),
      side: side.toLowerCase(),
      order_type: orderType,
    };
    if (stopPrice !== null) {
      payload.stop_price = String(Math.round(stopPrice * 100) / 100);
    }
    return this._request('POST', '/v2/orders', { payload, auth: true });
  }

  /**
   * Cancel all pending open orders for a symbol.
   * @param {string} symbol
   * @returns {Promise<object>}
   */
  async cancelAllOrders(symbol) {
    const payload = { product_symbol: symbol };
    return this._request('DELETE', '/v2/orders/all', { payload, auth: true });
  }
}

module.exports = DeltaClient;

"""
Delta Exchange Live & Paper Trading Bot — BTCUSD 4H Trend Rider
================================================================
Connects directly to Delta Exchange REST API v2 to execute trades based on 
the Trend Rider 4H strategy.

Requirements:
    pip install requests pandas numpy python-dotenv ccxt

Setup:
    1. Copy `.env.example` to `.env`
    2. Fill in your DELTA_API_KEY and DELTA_API_SECRET from Delta Exchange.
    3. Run in paper trading mode first (`DRY_RUN=true`).
    4. Run live trading: `python delta_trader.py`
"""

import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from trend_rider_engine import (
    TrendRiderParams,
    compute_indicators,
    supertrend_full,
)

# Load .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ============================================================================
# DELTA EXCHANGE REST API CLIENT
# ============================================================================

class DeltaClient:
    """REST API v2 wrapper for Delta Exchange (India & Global)."""

    def __init__(self, api_key: str, api_secret: str, base_url: str = "https://api.india.delta.exchange"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def _generate_signature(self, method: str, path: str, query_string: str = "", payload: str = "") -> tuple[str, str]:
        """Generate HMAC SHA256 signature for Delta REST API v2."""
        timestamp = str(int(time.time()))
        signature_data = method + timestamp + path + query_string + payload
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_data.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return timestamp, signature

    def _request(self, method: str, path: str, params: dict = None, payload: dict = None, auth: bool = True) -> dict:
        url = self.base_url + path
        query_string = ""
        payload_str = ""

        if params:
            query_string = "?" + "&".join([f"{k}={v}" for k, v in sorted(params.items())])
            url += query_string

        if payload:
            payload_str = json.dumps(payload)

        headers = {"Content-Type": "application/json"}

        if auth and self.api_key and self.api_secret:
            timestamp, signature = self._generate_signature(method.upper(), path, query_string, payload_str)
            headers["api-key"] = self.api_key
            headers["timestamp"] = timestamp
            headers["signature"] = signature

        try:
            resp = self.session.request(
                method=method.upper(),
                url=url,
                headers=headers,
                data=payload_str if payload else None,
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[DELTA API ERROR] {method} {path}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"  Response Body: {e.response.text}")
            raise

    # Public Endpoints
    def get_candles(self, symbol: str, resolution: str = "4h", start_time: int = None, end_time: int = None) -> list:
        """Fetch historical candle OHLCV data."""
        params = {"symbol": symbol, "resolution": resolution}
        if start_time:
            params["start"] = start_time
        if end_time:
            params["end"] = end_time

        res = self._request("GET", "/v2/history/candles", params=params, auth=False)
        return res.get("result", [])

    def get_ticker(self, symbol: str) -> dict:
        """Fetch current ticker price."""
        res = self._request("GET", f"/v2/tickers/{symbol}", auth=False)
        return res.get("result", {})

    # Private Endpoints
    def get_balances(self) -> list:
        """Fetch wallet balances."""
        res = self._request("GET", "/v2/wallet/balances", auth=True)
        return res.get("result", [])

    def get_positions(self, symbol: str = None) -> list:
        """Fetch open positions."""
        params = {"symbol": symbol} if symbol else None
        res = self._request("GET", "/v2/positions/margined", params=params, auth=True)
        return res.get("result", [])

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        """Set position leverage."""
        payload = {"product_symbol": symbol, "leverage": str(leverage)}
        return self._request("POST", "/v2/products/leverage", payload=payload, auth=True)

    def place_order(self, symbol: str, size: int, side: str, order_type: str = "market_order", stop_price: float = None) -> dict:
        """
        Place an order on Delta Exchange.
        side: 'buy' or 'sell'
        order_type: 'market_order' or 'stop_market_order'
        """
        payload = {
            "product_symbol": symbol,
            "size": int(size),
            "side": side.lower(),
            "order_type": order_type,
        }
        if stop_price is not None:
            payload["stop_price"] = str(round(stop_price, 2))

        return self._request("POST", "/v2/orders", payload=payload, auth=True)

    def cancel_all_orders(self, symbol: str) -> dict:
        """Cancel all pending open orders for a symbol."""
        payload = {"product_symbol": symbol}
        return self._request("DELETE", "/v2/orders/all", payload=payload, auth=True)


# ============================================================================
# TRADER ENGINE
# ============================================================================

class DeltaTrader:
    def __init__(self):
        # Load config from environment variables or defaults
        self.api_key = os.getenv("DELTA_API_KEY", "")
        self.api_secret = os.getenv("DELTA_API_SECRET", "")
        self.base_url = os.getenv("DELTA_BASE_URL", "https://api.india.delta.exchange")
        self.symbol = os.getenv("SYMBOL", "BTCUSD")
        self.timeframe = os.getenv("TIMEFRAME", "4h")
        self.risk_pct = float(os.getenv("RISK_PCT", "1.5"))
        self.leverage = int(os.getenv("LEVERAGE", "5"))
        self.dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
        self.poll_interval = int(os.getenv("POLL_INTERVAL_SEC", "60"))

        # Strategy parameters
        self.params = TrendRiderParams(
            risk_pct=self.risk_pct,
            trail_pct_activation=float(os.getenv("TRAIL_PCT_ACTIVATION", "1.0")),
            trail_pct_distance=float(os.getenv("TRAIL_PCT_DISTANCE", "0.4")),
        )

        self.client = DeltaClient(self.api_key, self.api_secret, self.base_url)

        # State tracking
        self.active_position = None
        self.peak_price = None
        self.trail_stop_price = None

    def print_banner(self):
        mode_str = "\033[93m[DRY RUN / PAPER TRADING]\033[0m" if self.dry_run else "\033[91m[LIVE REAL TRADING]\033[0m"
        print()
        print("=" * 65)
        print(f"   DELTA EXCHANGE LIVE TRADER -- 4H TREND RIDER {mode_str}")
        print("=" * 65)
        print(f"  Symbol:                {self.symbol}")
        print(f"  Timeframe:             {self.timeframe}")
        print(f"  Risk Per Trade:        {self.risk_pct}%")
        print(f"  Leverage:              {self.leverage}x")
        print(f"  Trailing Trigger:      {self.params.trail_pct_activation}% move -> {self.params.trail_pct_distance}% trail")
        print(f"  API Base URL:          {self.base_url}")
        print("=" * 65)
        print()

    def fetch_recent_candles(self, limit: int = 150) -> pd.DataFrame:
        """Fetch 4H candles from Delta Exchange API."""
        now_ts = int(time.time())
        start_ts = now_ts - (limit * 4 * 3600)

        raw_candles = self.client.get_candles(self.symbol, self.timeframe, start_ts, now_ts)
        if not raw_candles:
            raise ValueError(f"No candles returned for {self.symbol} ({self.timeframe})")

        # Delta candles format: [{"time": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}, ...]
        df = pd.DataFrame(raw_candles)
        df["ts"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.rename(columns={"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"})
        df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
        df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")
        return df

    def evaluate_signals(self, df: pd.DataFrame):
        """Evaluate Trend Rider signals on the latest completed candle."""
        d = compute_indicators(df, self.params)
        d = d.dropna(subset=["ema_fast", "ema_slow", "atr", "st_dir", "donchian_high"])

        if len(d) < 5:
            return None, None, None

        curr = d.iloc[-2]  # latest COMPLETED candle
        prev = d.iloc[-3]  # previous completed candle

        ema_val = curr["ema_fast"]
        atr_val = curr["atr"]

        signal = None
        signal_type = ""

        # Long entry check
        if curr["trend_bull"] and curr["ema_fast_slope"]:
            is_pullback = (prev["low"] <= ema_val * 1.003) and (curr["close"] > ema_val) and (curr["close"] > curr["open"])
            is_breakout = (curr["close"] > curr["donchian_high"]) and (curr["rsi"] < self.params.rsi_ob)
            is_st_flip = curr["st_recent_bull"] and (curr["close"] > ema_val)

            if is_pullback:
                signal, signal_type = "long", "pullback"
            elif is_breakout:
                signal, signal_type = "long", "breakout"
            elif is_st_flip:
                signal, signal_type = "long", "fresh_trend"

        # Short entry check
        elif curr["trend_bear"] and curr["ema_fast_slope_short"]:
            is_pullback = (prev["high"] >= ema_val * 0.997) and (curr["close"] < ema_val) and (curr["close"] < curr["open"])
            is_breakout = (curr["close"] < curr["donchian_low"]) and (curr["rsi"] > self.params.rsi_os)
            is_st_flip = curr["st_recent_bear"] and (curr["close"] < ema_val)

            if is_pullback:
                signal, signal_type = "short", "pullback"
            elif is_breakout:
                signal, signal_type = "short", "breakout"
            elif is_st_flip:
                signal, signal_type = "short", "fresh_trend"

        return signal, signal_type, curr

    def run_trading_cycle(self):
        """Single poll & trading check cycle."""
        timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"[{timestamp_str}] Checking market & signals...")

        try:
            df = self.fetch_recent_candles(limit=100)
            ticker = self.client.get_ticker(self.symbol)
            curr_price = float(ticker.get("mark_price", df["close"].iloc[-1]))
        except Exception as e:
            print(f"  [ERROR] Failed to fetch market data: {e}")
            return

        signal, signal_type, curr_bar = self.evaluate_signals(df)

        print(f"  Current Price: ${curr_price:,.2f} | 4H Bar Close: ${curr_bar['close']:,.2f}")
        print(f"  EMA21: ${curr_bar['ema_fast']:,.2f} | Supertrend: {curr_bar['st_dir']} ({'BULL' if curr_bar['st_dir'] == 1 else 'BEAR'})")

        if signal:
            print(f"  \033[92m[SIGNAL DETECTED]\033[0m Direction: {signal.upper()} | Type: {signal_type.upper()}")
        else:
            print("  No new signal on current closed 4H candle.")

        # Check existing active position
        if not self.dry_run:
            try:
                positions = self.client.get_positions(self.symbol)
                pos = positions[0] if positions else None
                pos_size = float(pos.get("size", 0)) if pos else 0
            except Exception as e:
                print(f"  [WARN] Failed to fetch positions: {e}")
                pos_size = 0
        else:
            pos_size = self.active_position["size"] if self.active_position else 0

        # Position Management & Dynamic Trailing Stop
        if pos_size != 0 or self.active_position is not None:
            self._manage_active_position(curr_price, curr_bar)
        elif signal is not None:
            self._execute_entry(signal, signal_type, curr_bar, curr_price)

    def _execute_entry(self, direction: str, signal_type: str, curr_bar, current_price: float):
        """Calculate size, place market order and initial stop loss."""
        atr_val = curr_bar["atr"]
        stop_dist = self.params.stop_atr_mult * atr_val

        if direction == "long":
            stop_price = current_price - stop_dist
            side = "buy"
        else:
            stop_price = current_price + stop_dist
            side = "sell"

        # Position sizing
        equity = 10000.0  # default paper capital if dry run
        if not self.dry_run:
            try:
                balances = self.client.get_balances()
                if balances:
                    equity = float(balances[0].get("balance", 10000.0))
            except Exception as e:
                print(f"  [WARN] Could not fetch balance, using default: {e}")

        risk_amount = equity * (self.risk_pct / 100.0)
        contracts = max(1, int(risk_amount / stop_dist))

        print(f"\n  \033[96m>>> EXECUTING ENTRY <<<\033[0m")
        print(f"  Direction:   {direction.toUpperCase()}")
        print(f"  Side:        {side.upper()}")
        print(f"  Contracts:   {contracts}")
        print(f"  Entry Price: ${current_price:,.2f}")
        print(f"  Stop Loss:   ${stop_price:,.2f} (Dist: ${stop_dist:,.2f})")

        if self.dry_run:
            print("  \033[93m[DRY RUN] Order simulated successfully!\033[0m")
            self.active_position = {
                "direction": direction,
                "entry_price": current_price,
                "stop_price": stop_price,
                "trail_stop": stop_price,
                "peak_price": current_price,
                "size": contracts,
                "type": signal_type,
            }
        else:
            try:
                # Set leverage
                self.client.set_leverage(self.symbol, self.leverage)
                # Place market entry order
                entry_res = self.client.place_order(self.symbol, contracts, side, "market_order")
                print(f"  [LIVE ORDER] Entry Order Placed: {entry_res.get('id')}")

                # Place stop loss order
                exit_side = "sell" if direction == "long" else "buy"
                stop_res = self.client.place_order(self.symbol, contracts, exit_side, "stop_market_order", stop_price=stop_price)
                print(f"  [LIVE ORDER] Stop Loss Placed: {stop_res.get('id')}")

                self.active_position = {
                    "direction": direction,
                    "entry_price": current_price,
                    "stop_price": stop_price,
                    "trail_stop": stop_price,
                    "peak_price": current_price,
                    "size": contracts,
                    "type": signal_type,
                }
            except Exception as e:
                print(f"  \033[91m[ORDER FAILED]\033[0m {e}")

    def _manage_active_position(self, current_price: float, curr_bar):
        """Update trailing stop when price moves 1% in profit -> trail 0.4%."""
        pos = self.active_position
        if not pos:
            return

        direction = pos["direction"]
        entry_px = pos["entry_price"]

        if direction == "long":
            pos["peak_price"] = max(pos["peak_price"], current_price)
            pct_move = (pos["peak_price"] - entry_px) / entry_px * 100.0

            # 1% activation -> 0.4% trailing stop
            if pct_move >= self.params.trail_pct_activation:
                new_trail = pos["peak_price"] * (1.0 - self.params.trail_pct_distance / 100.0)
                if new_trail > pos["trail_stop"]:
                    print(f"  \033[92m[TRAILING STOP TIGHTENED]\033[0m Peak: ${pos['peak_price']:,.2f} (+{pct_move:.2f}%) | Trail Stop: ${new_trail:,.2f}")
                    pos["trail_stop"] = new_trail

            # Exit check
            if current_price <= pos["trail_stop"]:
                pnl = (pos["trail_stop"] - entry_px) * pos["size"]
                print(f"  \033[91m[POSITION CLOSED]\033[0m Trailing stop hit at ${current_price:,.2f} | PnL: ${pnl:+,.2f}")
                if not self.dry_run:
                    self.client.cancel_all_orders(self.symbol)
                    self.client.place_order(self.symbol, pos["size"], "sell", "market_order")
                self.active_position = None

        else:  # Short position
            pos["peak_price"] = min(pos["peak_price"], current_price)
            pct_move = (entry_px - pos["peak_price"]) / entry_px * 100.0

            if pct_move >= self.params.trail_pct_activation:
                new_trail = pos["peak_price"] * (1.0 + self.params.trail_pct_distance / 100.0)
                if new_trail < pos["trail_stop"]:
                    print(f"  \033[92m[TRAILING STOP TIGHTENED]\033[0m Peak: ${pos['peak_price']:,.2f} (+{pct_move:.2f}%) | Trail Stop: ${new_trail:,.2f}")
                    pos["trail_stop"] = new_trail

            if current_price >= pos["trail_stop"]:
                pnl = (entry_px - pos["trail_stop"]) * pos["size"]
                print(f"  \033[91m[POSITION CLOSED]\033[0m Trailing stop hit at ${current_price:,.2f} | PnL: ${pnl:+,.2f}")
                if not self.dry_run:
                    self.client.cancel_all_orders(self.symbol)
                    self.client.place_order(self.symbol, pos["size"], "buy", "market_order")
                self.active_position = None

    def start_loop(self):
        """Continuous polling loop."""
        self.print_banner()
        print(f"Starting continuous polling loop (every {self.poll_interval}s)... Press Ctrl+C to stop.")

        while True:
            try:
                self.run_trading_cycle()
            except KeyboardInterrupt:
                print("\nStopping trader bot. Goodbye!")
                break
            except Exception as e:
                print(f"Unexpected error in trading loop: {e}")

            time.sleep(self.poll_interval)


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    trader = DeltaTrader()
    trader.start_loop()

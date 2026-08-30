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

import email.utils
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import numpy as np
import pandas as pd
import requests

from trend_rider_engine import (
    TrendRiderParams,
    compute_indicators,
    supertrend_full,
)
from telegram_notifier import TelegramNotifier
from symbol_utils import to_ccxt, to_delta, to_binance


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
        self.time_offset = 0
        self._retrying = False
        self.sync_time_offset()

    def sync_time_offset(self):
        """Synchronize local system clock with Delta Exchange server time."""
        try:
            resp = self.session.get(f"{self.base_url}/v2/products", timeout=5)
            if "Date" in resp.headers:
                server_dt = email.utils.parsedate_to_datetime(resp.headers["Date"])
                server_time = int(server_dt.timestamp())
                self.time_offset = server_time - int(time.time())
        except Exception:
            pass

    def _generate_signature(self, method: str, path: str, query_string: str = "", payload: str = "") -> tuple[str, str]:
        """Generate HMAC SHA256 signature for Delta REST API v2."""
        timestamp = str(int(time.time() + self.time_offset))
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
            if hasattr(e, 'response') and e.response is not None:
                try:
                    err_json = e.response.json()
                    err_info = err_json.get("error", {})
                    err_code = err_info.get("code")

                    # Handle clock skew (expired_signature) by setting offset and retrying
                    if err_code == "expired_signature":
                        server_time = err_info.get("context", {}).get("server_time")
                        if server_time and not self._retrying:
                            self.time_offset = int(server_time) - int(time.time())
                            self._retrying = True
                            try:
                                return self._request(method, path, params=params, payload=payload, auth=auth)
                            finally:
                                self._retrying = False

                    # Handle IP Whitelist Restriction
                    if err_code == "ip_not_whitelisted_for_api_key":
                        client_ip = err_info.get("context", {}).get("client_ip", "Unknown")
                        print(f"\n\033[93m[DELTA API ERROR] IP Whitelist Restriction!\033[0m")
                        print(f"  Your current public IP: \033[1m\033[96m{client_ip}\033[0m")
                        print(f"  \033[97mAction Required: Add IP '{client_ip}' to your Delta Exchange API Key whitelist, or remove IP restrictions in your Delta API Key settings.\033[0m\n")
                except Exception:
                    pass

                print(f"[DELTA API ERROR] {method} {path}: {e}")
                print(f"  Response Body: {e.response.text}")
            else:
                print(f"[DELTA API ERROR] {method} {path}: {e}")
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

    def get_products(self) -> list:
        """Fetch all product configurations (contract sizes, tick sizes, etc.)."""
        res = self._request("GET", "/v2/products", auth=False)
        return res.get("result", [])

    def get_product_symbols(self) -> set:
        """Return set of all valid product symbols on the exchange."""
        try:
            products = self.get_products()
            return {p["symbol"] for p in products if "symbol" in p}
        except Exception:
            return set()

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
        if not hasattr(self, '_product_map'):
            self._product_map = {}
            try:
                for p in self.get_products():
                    self._product_map[p.get("symbol")] = p.get("id")
            except Exception:
                pass
                
        product_id = self._product_map.get(symbol)
        if not product_id:
            raise ValueError(f"Product ID not found for symbol: {symbol}")
            
        payload = {"leverage": str(leverage)}
        return self._request("POST", f"/v2/products/{product_id}/orders/leverage", payload=payload, auth=True)

    def place_order(self, symbol: str, size: int, side: str, order_type: str = "market_order", stop_price: float = None, reduce_only: bool = False) -> dict:
        """
        Place an order on Delta Exchange.
        side: 'buy' or 'sell'
        order_type: 'market_order' or 'stop_market_order'
        """
        actual_order_type = order_type
        stop_order_type = None

        if order_type == "stop_market_order":
            actual_order_type = "market_order"
            stop_order_type = "stop_loss_order"

        payload = {
            "product_symbol": symbol,
            "size": int(size),
            "side": side.lower(),
            "order_type": actual_order_type,
        }
        
        if stop_order_type:
            payload["stop_order_type"] = stop_order_type
            
        if stop_price is not None:
            payload["stop_price"] = str(round(stop_price, 2))
            
        if reduce_only:
            payload["reduce_only"] = True

        return self._request("POST", "/v2/orders", payload=payload, auth=True)

    def cancel_order_by_id(self, order_id: int | str) -> dict:
        """Cancel a single order by its ID."""
        return self._request("DELETE", f"/v2/orders/{order_id}", auth=True)

    def cancel_all_orders(self, symbol: str) -> dict:
        """Cancel ALL pending open orders for a symbol (use sparingly — prefer cancel_order_by_id)."""
        if not hasattr(self, '_product_map'):
            self._product_map = {}
            try:
                for p in self.get_products():
                    self._product_map[p.get("symbol")] = p.get("id")
            except Exception:
                pass
                
        product_id = self._product_map.get(symbol)
        
        if product_id:
            # Delta API expects product_id in the request body only (not as a query param).
            # Passing it as params would add ?product_id=X to the URL and break the signature.
            payload = {"product_id": product_id}
            return self._request("DELETE", "/v2/orders/all", payload=payload, auth=True)
        else:
            payload = {"product_symbol": symbol}
            return self._request("DELETE", "/v2/orders/all", payload=payload, auth=True)


# ============================================================================
# TRADER ENGINE
# ============================================================================

class DeltaTrader:
    def __init__(self):
        def get_env_stripped(key: str, default: str = "") -> str:
            val = os.getenv(key, default).strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1].strip()
            return val

        # Load config from environment variables or defaults
        self.api_key = get_env_stripped("DELTA_API_KEY", "")
        self.api_secret = get_env_stripped("DELTA_API_SECRET", "")
        self.base_url = get_env_stripped("DELTA_BASE_URL", "https://api.india.delta.exchange")
        # Accept SYMBOL in env as either 'BTC/USD' or 'BTCUSD'
        env_symbol = get_env_stripped("SYMBOL", "BTCUSD")
        self.timeframe = get_env_stripped("TIMEFRAME", "4h")
        try:
            self.symbol_canonical = to_ccxt(env_symbol)
            self.symbol = to_delta(self.symbol_canonical)
        except Exception:
            self.symbol_canonical = env_symbol
            self.symbol = env_symbol
        self.risk_pct = float(get_env_stripped("RISK_PCT", "1.5"))
        self.leverage = int(get_env_stripped("LEVERAGE", "5"))
        self.fixed_margin_usd = float(get_env_stripped("FIXED_MARGIN_USD", "0"))
        self.dry_run = get_env_stripped("DRY_RUN", "true").lower() == "true"
        self.poll_interval = int(get_env_stripped("POLL_INTERVAL_SEC", "60"))

        self.params = TrendRiderParams(
            risk_pct=self.risk_pct,
            trail_pct_activation=float(get_env_stripped("TRAIL_PCT_ACTIVATION", "0.5")),
            trail_pct_distance=float(get_env_stripped("TRAIL_PCT_DISTANCE", "0.3")),
        )

        self.client = DeltaClient(self.api_key, self.api_secret, self.base_url)
        self.notifier = TelegramNotifier()
        
        # Load contract specs for precise sizing
        self.contract_values = {}
        try:
            products = self.client.get_products()
            for p in products:
                if "symbol" in p and "contract_value" in p:
                    self.contract_values[p["symbol"]] = float(p["contract_value"])
        except Exception as e:
            print(f"[WARN] Failed to load contract specs from Delta API: {e}")

        # State tracking
        self.positions: dict[str, dict] = {}          # keyed by symbol_canonical
        self._notified_signals_by_symbol: dict[str, set[str]] = {}  # keyed by symbol_canonical
        # symbols list will hold dicts: {"delta": <DELTA_SYM>, "canon": <BASE/QUOTE>}
        self.symbols = []
        # Cooldown: track the candle timestamp of last exit per symbol
        # to enforce cooldown_bars gap before re-entry (matches backtest)
        self._last_exit_candle_ts: dict[str, int] = {}
        
        # Telegram manual control flags
        self._force_open: dict[str, str] = {}
        self._force_close: dict[str, bool] = {}

        # State persistence file
        self.state_file = Path(os.path.dirname(os.path.abspath(__file__))) / "trader_state.json"
        self.load_state()

    def save_state(self):
        try:
            # Convert notified signals set to list for JSON serialization
            serializable_signals = {
                sym: list(signals) for sym, signals in self._notified_signals_by_symbol.items()
            }
            state = {
                "positions": self.positions,
                "notified_signals": serializable_signals,
                "last_exit_candle_ts": self._last_exit_candle_ts
            }
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=4)
        except Exception as e:
            print(f"  [WARN] Failed to save state to disk: {e}")

    def load_state(self):
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
            
            self.positions = state.get("positions", {})
            
            # Restore notified signals set
            raw_signals = state.get("notified_signals", {})
            for sym, signals in raw_signals.items():
                self._notified_signals_by_symbol[sym] = set(signals)
                
            self._last_exit_candle_ts = state.get("last_exit_candle_ts", {})
            print(f"  [STATE] Successfully loaded state from {self.state_file}")
        except Exception as e:
            print(f"  [WARN] Failed to load state from disk: {e}")

    def reconcile_positions(self):
        """Reconcile local state with open positions on Delta Exchange."""
        if self.dry_run:
            return

        print("\n  [STATE] Reconciling positions with Delta Exchange...")
        try:
            # Fetch all open positions
            positions = self.client.get_positions()
            
            # Map positions by symbol
            exchange_positions = {}
            for p in positions:
                p_symbol = p.get("product_symbol", p.get("symbol", ""))
                if p_symbol:
                    exchange_positions[p_symbol] = p
            
            state_changed = False
            
            for sym_info in self.symbols:
                delta_sym = sym_info["delta"]
                canon_sym = sym_info["canon"]
                
                # Check if position exists on exchange
                pos = exchange_positions.get(delta_sym)
                exchange_size = float(pos.get("size", 0)) if pos else 0
                
                local_pos = self.positions.get(canon_sym)
                
                if exchange_size != 0:
                    exchange_direction = "long" if exchange_size > 0 else "short"
                    exchange_entry_px = float(pos.get("entry_price", 0))
                    
                    if local_pos:
                        # Local state exists, verify matches
                        local_direction = local_pos.get("direction")
                        local_size = local_pos.get("size", 0)
                        
                        if local_direction != exchange_direction or abs(local_size - abs(exchange_size)) > 0.0001:
                            print(f"  [{canon_sym}] [WARN] Local position mismatch (Local: {local_direction} {local_size}, Exchange: {exchange_direction} {abs(exchange_size)}). Reconstructing state...")
                            self.positions[canon_sym] = {
                                "direction": exchange_direction,
                                "entry_price": exchange_entry_px,
                                "stop_price": exchange_entry_px * 0.95 if exchange_direction == "long" else exchange_entry_px * 1.05,
                                "trail_stop": exchange_entry_px * 0.95 if exchange_direction == "long" else exchange_entry_px * 1.05,
                                "peak_price": exchange_entry_px,
                                "size": abs(exchange_size),
                                "type": "recovered",
                                "init_risk": exchange_entry_px * 0.05
                            }
                            state_changed = True
                    else:
                        # Position exists on exchange but no local state. Reconstruct!
                        print(f"  [{canon_sym}] [WARN] Active position of {abs(exchange_size)} found on exchange but not in local state. Reconstructing...")
                        self.positions[canon_sym] = {
                            "direction": exchange_direction,
                            "entry_price": exchange_entry_px,
                            "stop_price": exchange_entry_px * 0.95 if exchange_direction == "long" else exchange_entry_px * 1.05,
                            "trail_stop": exchange_entry_px * 0.95 if exchange_direction == "long" else exchange_entry_px * 1.05,
                            "peak_price": exchange_entry_px,
                            "size": abs(exchange_size),
                            "type": "recovered",
                            "init_risk": exchange_entry_px * 0.05
                        }
                        state_changed = True
                else:
                    # No position on exchange
                    if local_pos:
                        print(f"  [{canon_sym}] [WARN] Local state has active position but none found on exchange. Clearing local position.")
                        # Cancel any lingering stop-loss / limit orders for this symbol
                        try:
                            self.client.cancel_all_orders(delta_sym)
                            print(f"  [{canon_sym}] [STATE] Cancelled all pending orders for {delta_sym}.")
                        except Exception as e:
                            print(f"  [{canon_sym}] [WARN] Failed to cancel orders during reconciliation: {e}")
                        self.positions.pop(canon_sym, None)
                        state_changed = True
            
            if state_changed:
                self.save_state()
            print("  [STATE] Position reconciliation complete.\n")
            
        except Exception as e:
            print(f"  [WARN] Failed to reconcile positions: {e}")

    @property
    def active_position(self):
        """Active position for the symbol currently being processed."""
        return self.positions.get(self.symbol_canonical)

    @active_position.setter
    def active_position(self, value):
        if value is None:
            self.positions.pop(self.symbol_canonical, None)
        else:
            self.positions[self.symbol_canonical] = value
        self.save_state()

    @property
    def _notified_signals(self):
        return self._notified_signals_by_symbol.setdefault(self.symbol_canonical, set())

    @_notified_signals.setter
    def _notified_signals(self, value):
        self._notified_signals_by_symbol[self.symbol_canonical] = value

    def print_banner(self):
        mode_str = "\033[93m[DRY RUN / PAPER TRADING]\033[0m" if self.dry_run else "\033[91m[LIVE REAL TRADING]\033[0m"
        print()
        print("=" * 65)
        print(f"   DELTA EXCHANGE LIVE TRADER -- 4H TREND RIDER {mode_str}")
        print("=" * 65)
        print(f"  Symbol:                {self.symbol_canonical}")
        print(f"  Timeframe:             {self.timeframe}")
        print(f"  Risk Per Trade:        {self.risk_pct}%")
        print(f"  Leverage:              {self.leverage}x")
        print(f"  Trailing Trigger:      {self.params.trail_pct_activation}% move -> {self.params.trail_pct_distance}% trail")
        print(f"  API Base URL:          {self.base_url}")
        print("=" * 65)
        print()

    def _fetch_candles_delta(self, limit: int, now_ts: int, start_ts: int) -> pd.DataFrame | None:
        """Try fetching candles from Delta Exchange (priority 1)."""
        try:
            raw_candles = self.client.get_candles(self.symbol, self.timeframe, start_ts, now_ts)
            if not raw_candles:
                return None

            df = pd.DataFrame(raw_candles)
            df["ts"] = pd.to_datetime(df["time"], unit="s", utc=True)
            df = df.rename(columns={"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"})
            df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
            df = df.sort_values("ts").drop_duplicates("ts").set_index("ts")

            if len(df) < 5:
                return None
            return df
        except Exception as e:
            print(f"  [WARN] Delta candle fetch failed: {e}")
            return None

    def _fetch_candles_binance(self, limit: int, now_ts: int, start_ts: int) -> pd.DataFrame | None:
        """Fallback: fetch candles from Binance via ccxt."""
        try:
            import ccxt

            # Map the symbol to Binance format (e.g. BTCUSD -> BTC/USDT, AVAXUSD -> AVAX/USDT)
            binance_symbol = to_binance(self.symbol_canonical)

            exchange = ccxt.binance({"enableRateLimit": True})
            since_ms = start_ts * 1000

            all_rows = []
            cursor = since_ms
            until_ms = now_ts * 1000

            while cursor < until_ms:
                batch = exchange.fetch_ohlcv(binance_symbol, timeframe=self.timeframe, since=cursor, limit=1000)
                if not batch:
                    break
                all_rows.extend(batch)
                cursor = batch[-1][0] + 1
                if len(batch) < 2:
                    break
                import time as _time
                _time.sleep(exchange.rateLimit / 1000)

            if not all_rows:
                return None

            df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close", "volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
            df = df.drop_duplicates("ts").set_index("ts")
            df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})

            if len(df) < 5:
                return None
            return df
        except Exception as e:
            print(f"  [WARN] Binance candle fetch failed: {e}")
            return None

    def fetch_recent_candles(self, limit: int = 150) -> pd.DataFrame:
        """Fetch candles with priority: Delta Exchange first, Binance fallback."""
        now_ts = int(time.time())
        start_ts = now_ts - (limit * 4 * 3600)

        # Priority 1: Delta Exchange
        df = self._fetch_candles_delta(limit, now_ts, start_ts)
        if df is not None:
            print(f"  [DATA] Candles from Delta Exchange ({len(df)} bars)")
            return df

        # Fallback: Binance
        print(f"  [DATA] Delta returned no data for {self.symbol}, trying Binance...")
        df = self._fetch_candles_binance(limit, now_ts, start_ts)
        if df is not None:
            print(f"  [DATA] Candles from Binance fallback ({len(df)} bars)")
            return df

        raise ValueError(f"No candles from Delta or Binance for {self.symbol} ({self.timeframe})")

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

    def _signal_key(self, signal: str, signal_type: str, curr_bar) -> str:
        candle_time = getattr(curr_bar, "name", None)
        if hasattr(candle_time, "to_pydatetime"):
            candle_time = candle_time.to_pydatetime()
        if hasattr(candle_time, "timestamp"):
            candle_ts = int(candle_time.timestamp())
        else:
            candle_ts = int(time.time())
        return f"{self.symbol_canonical}|{signal}|{signal_type}|{candle_ts}"

    def _format_candle_time(self, curr_bar) -> str:
        candle_time = getattr(curr_bar, "name", None)
        if candle_time is None:
            return ""
        try:
            return candle_time.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            return str(candle_time)

    def run_trading_cycle(self):
        """Single poll & trading check cycle."""
        timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"[{timestamp_str}] [{self.symbol_canonical}] Checking market & signals...")

        try:
            df = self.fetch_recent_candles(limit=100)
        except Exception as e:
            print(f"  [{self.symbol_canonical}] [ERROR] Failed to fetch candle data: {e}")
            print(f"  [{self.symbol_canonical}] Skipping this symbol for this cycle.")
            return

        try:
            ticker = self.client.get_ticker(self.symbol)
            curr_price = float(ticker.get("mark_price", df["close"].iloc[-1]))
        except Exception as e:
            print(f"  [{self.symbol_canonical}] [WARN] Ticker fetch failed, using last candle close: {e}")
            curr_price = float(df["close"].iloc[-1])

        signal, signal_type, curr_bar = self.evaluate_signals(df)

        if curr_bar is None:
            print(f"  [{self.symbol_canonical}] [WARN] Not enough data for indicator computation, skipping.")
            return

        print(f"  [{self.symbol_canonical}] Price: ${curr_price:,.2f} | 4H Close: ${curr_bar['close']:,.2f} | EMA21: ${curr_bar['ema_fast']:,.2f} | ST: {'BULL' if curr_bar['st_dir'] == 1 else 'BEAR'}")

        # Check for forced open/close commands
        if self._force_close.pop(self.symbol_canonical, False):
            print(f"  [{self.symbol_canonical}] \033[96m>>> MANUAL CLOSE COMMAND RECEIVED <<<\033[0m")
            if self.active_position:
                direction = self.active_position["direction"]
                exit_price = curr_price
                pnl = (exit_price - self.active_position["entry_price"]) * self.active_position["size"] if direction == "long" else (self.active_position["entry_price"] - exit_price) * self.active_position["size"]
                if not self.dry_run:
                    self.cancel_algo_orders(self.active_position)
                    self.client.place_order(self.symbol, self.active_position["size"], "sell" if direction == "long" else "buy", "market_order", reduce_only=True)
                self.active_position = None
                try:
                    self.notifier.exit(self.symbol_canonical, direction, exit_price, pnl)
                    self.notifier.send(f"✅ Manual Close Executed\nSymbol: {self.symbol_canonical}\nPnL: {pnl:+.2f}")
                except Exception:
                    pass
            else:
                try:
                    self.notifier.send(f"❌ Failed to Close: No active position for {self.symbol_canonical}")
                except Exception:
                    pass

        forced_open_dir = self._force_open.pop(self.symbol_canonical, None)
        if forced_open_dir:
            signal = forced_open_dir
            signal_type = "manual"
            print(f"  [{self.symbol_canonical}] \033[96m>>> MANUAL OPEN COMMAND RECEIVED: {signal.upper()} <<<\033[0m")
        elif signal:
            print(f"  [{self.symbol_canonical}] \033[96m>>> SIGNAL DETECTED: {signal.upper()} {signal_type} <<<\033[0m")
        else:
            print(f"  [{self.symbol_canonical}] No signal on current closed 4H candle.")

        # Check existing active position — FILTER BY CURRENT SYMBOL
        if not self.dry_run:
            try:
                positions = self.client.get_positions(self.symbol)
                # Filter to only the position matching our current symbol
                pos = None
                for p in positions:
                    p_symbol = p.get("product_symbol", p.get("symbol", ""))
                    if p_symbol == self.symbol:
                        pos = p
                        break
                pos_size = float(pos.get("size", 0)) if pos else 0
            except Exception as e:
                print(f"  [{self.symbol_canonical}] [WARN] Failed to fetch positions: {e}")
                pos_size = 0
        else:
            pos_size = self.active_position["size"] if self.active_position else 0

        # Position Management & Dynamic Trailing Stop
        if pos_size != 0 or self.active_position is not None:
            if not self.dry_run and pos_size == 0:
                print(f"  [{self.symbol_canonical}] [STATE] Position was closed externally on the exchange. Clearing local state.")
                # Cancel only the algo's stop-loss order — not all user orders
                self.cancel_algo_orders(self.active_position)
                print(f"  [{self.symbol_canonical}] [STATE] Cancelled algo stop-loss order for {self.symbol}.")
                try:
                    self.notifier.send(f"⚠️ Manual Exit Detected\nSymbol: {self.symbol_canonical}\nPosition was closed externally on the exchange.")
                except Exception as e:
                    print(f"  [{self.symbol_canonical}] [WARN] Failed to send manual exit notification: {e}")
                self.active_position = None
            else:
                if not self.dry_run:
                    if self.active_position is None:
                        # Reconstruct position state (self-healing recovery on startup/mismatch)
                        direction = "long" if pos_size > 0 else "short"
                        print(f"  [{self.symbol_canonical}] [STATE] Active position detected on exchange but missing locally. Reconstructing...")
                        
                        exchange_entry_px = curr_price # fallback
                        try:
                            positions = self.client.get_positions(self.symbol)
                            for p in positions:
                                if p.get("product_symbol", p.get("symbol", "")) == self.symbol:
                                    exchange_entry_px = float(p.get("entry_price", curr_price))
                                    break
                        except Exception:
                            pass
                        
                        stop_dist = self.params.stop_atr_mult * curr_bar["atr"]
                        stop_price = exchange_entry_px - stop_dist if direction == "long" else exchange_entry_px + stop_dist
                        
                        self.active_position = {
                            "direction": direction,
                            "entry_price": exchange_entry_px,
                            "stop_price": stop_price,
                            "trail_stop": stop_price,
                            "peak_price": exchange_entry_px,
                            "size": abs(pos_size),
                            "type": "recovered",
                            "init_risk": stop_dist
                        }
                    elif self.active_position["size"] != abs(pos_size):
                        print(f"  [{self.symbol_canonical}] [STATE] Position size mismatch. Syncing size: {self.active_position['size']} -> {abs(pos_size)}")
                        self.active_position["size"] = abs(pos_size)
                        
                self._manage_active_position(curr_price, curr_bar)
        elif signal is not None:
            # Cooldown check: skip entry if we exited too recently (matches backtest)
            curr_candle_ts = self._get_candle_ts(curr_bar)
            last_exit_ts = self._last_exit_candle_ts.get(self.symbol, 0)
            tf_seconds = self._timeframe_seconds()
            bars_since_exit = (curr_candle_ts - last_exit_ts) // tf_seconds if tf_seconds > 0 and last_exit_ts > 0 else 999
            if bars_since_exit < self.params.cooldown_bars:
                print(f"  [{self.symbol_canonical}] Cooldown active: {bars_since_exit} bars since last exit (need {self.params.cooldown_bars}), skipping.")
            else:
                # Duplicate signal guard: same candle + same signal = skip repeat
                sig_key = self._signal_key(signal, signal_type, curr_bar)
                if sig_key in self._notified_signals:
                    print(f"  [{self.symbol_canonical}] Signal already processed for this candle, skipping.")
                else:
                    # Attempt entry — only mark as processed if successful
                    try:
                        self._execute_entry(signal, signal_type, curr_bar, curr_price)
                        # Mark signal as processed ONLY after successful execution
                        self._notified_signals.add(sig_key)
                        # Prune old keys to prevent memory leak (keep last 50 per symbol)
                        if len(self._notified_signals) > 50:
                            self._notified_signals = set(list(self._notified_signals)[-50:])
                    except Exception as e:
                        print(f"  [{self.symbol_canonical}] \033[91m[ENTRY FAILED]\033[0m {e} — will retry on next poll.")

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
                    # Look for USDT or USD balance first
                    quote_bal = next((b for b in balances if b.get("asset_symbol") in ["USDT", "USD"]), None)
                    if quote_bal:
                        equity = float(quote_bal.get("balance", 10000.0))
                    else:
                        equity = float(balances[0].get("balance", 10000.0))
            except Exception as e:
                print(f"  [WARN] Could not fetch balance, using default: {e}")

        split_balance_margin = os.getenv("SPLIT_BALANCE_MARGIN", "true").lower() == "true"

        if split_balance_margin:
            num_coins = max(1, len(self.symbols))
            margin_per_coin = equity / num_coins
            notional = margin_per_coin * self.leverage
            # Get actual contract multiplier from delta API (default to 0.001 if missing)
            contract_val = self.contract_values.get(self.symbol, 0.001)
            contracts = max(1, int(notional / (current_price * contract_val)))
        elif self.fixed_margin_usd > 0:
            notional = self.fixed_margin_usd * self.leverage
            contract_val = self.contract_values.get(self.symbol, 0.001)
            contracts = max(1, int(notional / (current_price * contract_val)))
        else:
            risk_amount = equity * (self.risk_pct / 100.0)
            # Legacy simple logic
            contracts = max(1, int(risk_amount / stop_dist))

        print(f"\n  \033[96m>>> EXECUTING ENTRY <<<\033[0m")
        print(f"  Direction:   {direction.upper()}")
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
                "init_risk": stop_dist,  # needed for R-multiple trailing (matches backtest)
            }
            try:
                self.notifier.signal_detailed(
                    self.symbol_canonical,
                    direction,
                    signal_type,
                    current_price,
                    current_price,
                    contracts,
                    stop_price,
                    self.risk_pct,
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                    float(self.params.trail_pct_activation),
                    float(self.params.trail_pct_distance),
                    "No fixed TP; exit on trailing stop or trend reversal",
                )
            except Exception:
                try:
                    self.notifier.execution(self.symbol_canonical, direction, contracts, current_price, stop_price)
                except Exception:
                    pass
        else:
            try:
                # Set leverage
                self.client.set_leverage(self.symbol, self.leverage)
                # Place market entry order
                entry_res = self.client.place_order(self.symbol, contracts, side, "market_order")
                print(f"  [LIVE ORDER] Entry Order Placed: {entry_res.get('result', {}).get('id', entry_res.get('id'))}")

                # Place stop loss order
                exit_side = "sell" if direction == "long" else "buy"
                stop_res = self.client.place_order(self.symbol, contracts, exit_side, "stop_market_order", stop_price=stop_price, reduce_only=True)
                stop_order_id = stop_res.get('result', {}).get('id') or stop_res.get('id')
                print(f"  [LIVE ORDER] Stop Loss Placed: {stop_order_id}")

                self.active_position = {
                    "direction": direction,
                    "entry_price": current_price,
                    "stop_price": stop_price,
                    "trail_stop": stop_price,
                    "peak_price": current_price,
                    "size": contracts,
                    "type": signal_type,
                    "init_risk": stop_dist,  # needed for R-multiple trailing (matches backtest)
                    "stop_order_id": stop_order_id,  # track for targeted cancellation on exit
                }
                try:
                    self.notifier.signal_detailed(
                        self.symbol_canonical,
                        direction,
                        signal_type,
                        current_price,
                        current_price,
                        contracts,
                        stop_price,
                        self.risk_pct,
                        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                        float(self.params.trail_pct_activation),
                        float(self.params.trail_pct_distance),
                        "No fixed TP; exit on trailing stop or trend reversal",
                    )
                except Exception:
                    try:
                        self.notifier.execution(self.symbol_canonical, direction, contracts, current_price, stop_price)
                    except Exception:
                        pass
            except Exception as e:
                print(f"  \033[91m[ORDER FAILED]\033[0m {e}")
                raise  # Re-raise so run_trading_cycle knows the entry failed

    def cancel_algo_orders(self, pos: dict | None = None):
        """Cancel only the stop-loss order this algo placed — NOT all orders on the symbol.
        
        Uses the tracked stop_order_id from active_position for surgical cancellation.
        Falls back to cancel-all only for recovered positions with no tracked order ID.
        """
        pos = pos or self.active_position
        stop_order_id = pos.get("stop_order_id") if pos else None

        if stop_order_id:
            try:
                self.client.cancel_order_by_id(stop_order_id)
                print(f"  [ORDER] Cancelled algo stop-loss order #{stop_order_id}")
            except Exception as e:
                # Order may have already been filled/cancelled — log and continue
                print(f"  [WARN] Could not cancel stop-loss order #{stop_order_id}: {e}")
        else:
            # No order ID tracked (e.g. recovered position) — fall back to cancel-all
            print(f"  [ORDER] No stop_order_id tracked for {self.symbol_canonical}, falling back to cancel-all.")
            try:
                self.client.cancel_all_orders(self.symbol)
            except Exception as e:
                print(f"  [WARN] cancel_all_orders fallback failed: {e}")

    def _get_candle_ts(self, curr_bar) -> int:
        """Extract integer timestamp from a candle bar (used for cooldown tracking)."""
        candle_time = getattr(curr_bar, "name", None)
        if hasattr(candle_time, "timestamp"):
            return int(candle_time.timestamp())
        return int(time.time())

    def _timeframe_seconds(self) -> int:
        """Convert self.timeframe string (e.g. '4h', '1h', '15m') to seconds."""
        tf = self.timeframe.strip().lower()
        if tf.endswith("h"):
            return int(tf[:-1]) * 3600
        elif tf.endswith("m"):
            return int(tf[:-1]) * 60
        elif tf.endswith("d"):
            return int(tf[:-1]) * 86400
        return 14400  # default 4h

    def _manage_active_position(self, current_price: float, curr_bar):
        """Full exit management matching backtest engine exactly:
        - Percentage trailing: 1% activation → 0.4% trail
        - R-multiple phases: 1R→BE, 2R→chandelier 2.5×ATR, 4R→chandelier 1.8×ATR
        - Supertrend value as trail floor/ceiling
        - Supertrend reversal exit
        """
        pos = self.active_position
        if not pos:
            return

        direction = pos["direction"]
        entry_px = pos["entry_price"]
        init_risk = pos.get("init_risk", pos["stop_price"] and abs(entry_px - pos["stop_price"]) or 1.0)
        atr_val = curr_bar["atr"]

        if direction == "long":
            pos["peak_price"] = max(pos["peak_price"], curr_bar["high"])
            r_now = (curr_bar["close"] - entry_px) / init_risk if init_risk > 0 else 0

            # --- Percentage trailing stop (1% → 0.4%) ---
            pct_move = (pos["peak_price"] - entry_px) / entry_px * 100.0
            if pct_move >= self.params.trail_pct_activation:
                pct_stop = pos["peak_price"] * (1.0 - self.params.trail_pct_distance / 100.0)
                if pct_stop > pos["trail_stop"]:
                    pos["trail_stop"] = pct_stop

            # --- R-multiple phased trailing (matches backtest) ---
            if r_now >= 1.0 and r_now < 2.0:
                be = entry_px + self.params.trail_be_buffer * atr_val
                if be > pos["trail_stop"]:
                    pos["trail_stop"] = be
            elif r_now >= 2.0 and r_now < 4.0:
                chand = pos["peak_price"] - self.params.trail_phase2_mult * atr_val
                if chand > pos["trail_stop"]:
                    pos["trail_stop"] = chand
            elif r_now >= 4.0:
                chand = pos["peak_price"] - self.params.trail_phase3_mult * atr_val
                if chand > pos["trail_stop"]:
                    pos["trail_stop"] = chand

            # --- Supertrend value as trail floor ---
            st_val = curr_bar.get("st_val", None)
            if st_val is not None and not (isinstance(st_val, float) and np.isnan(st_val)):
                if st_val > pos["trail_stop"]:
                    pos["trail_stop"] = st_val

            old_trail = pos.get("_prev_trail", pos["stop_price"])
            if pos["trail_stop"] != old_trail:
                print(f"  \033[92m[TRAILING STOP UPDATED]\033[0m R={r_now:.1f} | Peak: ${pos['peak_price']:,.2f} | Trail: ${pos['trail_stop']:,.2f}")
            pos["_prev_trail"] = pos["trail_stop"]

            # --- Exit checks ---
            stop_hit = current_price <= pos["trail_stop"]
            st_reversed = curr_bar.get("st_dir", 1) == -1

            if stop_hit or st_reversed:
                exit_price = pos["trail_stop"] if stop_hit else current_price
                reason = "trail_stop" if stop_hit else "st_reversed"
                pnl = (exit_price - entry_px) * pos["size"]
                print(f"  \033[91m[POSITION CLOSED]\033[0m {reason} at ${current_price:,.2f} | Exit: ${exit_price:,.2f} | PnL: ${pnl:+,.2f}")
                if not self.dry_run:
                    self.cancel_algo_orders(pos)
                    self.client.place_order(self.symbol, pos["size"], "sell", "market_order", reduce_only=True)
                self._last_exit_candle_ts[self.symbol] = self._get_candle_ts(curr_bar)
                self.active_position = None
                try:
                    self.notifier.exit(self.symbol_canonical, direction, current_price, pnl)
                except Exception:
                    pass

        else:  # Short position
            pos["peak_price"] = min(pos["peak_price"], curr_bar["low"])
            r_now = (entry_px - curr_bar["close"]) / init_risk if init_risk > 0 else 0

            # --- Percentage trailing stop (1% → 0.4%) ---
            pct_move = (entry_px - pos["peak_price"]) / entry_px * 100.0
            if pct_move >= self.params.trail_pct_activation:
                pct_stop = pos["peak_price"] * (1.0 + self.params.trail_pct_distance / 100.0)
                if pct_stop < pos["trail_stop"]:
                    pos["trail_stop"] = pct_stop

            # --- R-multiple phased trailing (matches backtest) ---
            if r_now >= 1.0 and r_now < 2.0:
                be = entry_px - self.params.trail_be_buffer * atr_val
                if be < pos["trail_stop"]:
                    pos["trail_stop"] = be
            elif r_now >= 2.0 and r_now < 4.0:
                chand = pos["peak_price"] + self.params.trail_phase2_mult * atr_val
                if chand < pos["trail_stop"]:
                    pos["trail_stop"] = chand
            elif r_now >= 4.0:
                chand = pos["peak_price"] + self.params.trail_phase3_mult * atr_val
                if chand < pos["trail_stop"]:
                    pos["trail_stop"] = chand

            # --- Supertrend value as trail ceiling ---
            st_val = curr_bar.get("st_val", None)
            if st_val is not None and not (isinstance(st_val, float) and np.isnan(st_val)):
                if st_val < pos["trail_stop"]:
                    pos["trail_stop"] = st_val

            old_trail = pos.get("_prev_trail", pos["stop_price"])
            if pos["trail_stop"] != old_trail:
                print(f"  \033[92m[TRAILING STOP UPDATED]\033[0m R={r_now:.1f} | Peak: ${pos['peak_price']:,.2f} | Trail: ${pos['trail_stop']:,.2f}")
            pos["_prev_trail"] = pos["trail_stop"]

            # --- Exit checks ---
            stop_hit = current_price >= pos["trail_stop"]
            st_reversed = curr_bar.get("st_dir", -1) == 1

            if stop_hit or st_reversed:
                exit_price = pos["trail_stop"] if stop_hit else current_price
                reason = "trail_stop" if stop_hit else "st_reversed"
                pnl = (entry_px - exit_price) * pos["size"]
                print(f"  \033[91m[POSITION CLOSED]\033[0m {reason} at ${current_price:,.2f} | Exit: ${exit_price:,.2f} | PnL: ${pnl:+,.2f}")
                if not self.dry_run:
                    self.cancel_algo_orders(pos)
                    self.client.place_order(self.symbol, pos["size"], "buy", "market_order", reduce_only=True)
                self._last_exit_candle_ts[self.symbol] = self._get_candle_ts(curr_bar)
                self.active_position = None
                try:
                    self.notifier.exit(self.symbol_canonical, direction, current_price, pnl)
                except Exception:
                    pass

    def _validate_symbols(self, selected: list) -> list:
        """Validate that each symbol exists on Delta Exchange. Remove invalid ones."""
        valid = []
        try:
            available = self.client.get_product_symbols()
        except Exception:
            print("  [WARN] Could not fetch product list for validation, using all symbols.")
            return selected

        for sym in selected:
            if sym["delta"] in available:
                valid.append(sym)
            else:
                print(f"  \033[93m[SKIP]\033[0m {sym['canon']} ({sym['delta']}) — NOT FOUND on Delta Exchange. Removing from watchlist.")

        return valid

    def start_loop(self):
        """Continuous polling loop using only environment `SYMBOLS` or `SYMBOL` (no terminal input)."""
        print()
        print("Starting trader using SYMBOLS from environment only.")

        # Read and sanitize env vars. Support quoted values from .env files.
        def _strip_quotes(s: str) -> str:
            s = s.strip()
            if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
                return s[1:-1]
            return s

        symbols_env = _strip_quotes(os.getenv("SYMBOLS", ""))
        selected = []
        if symbols_env:
            for part in symbols_env.split(","):
                s = part.strip()
                if not s:
                    continue
                try:
                    canon = to_ccxt(s)
                    delta = to_delta(canon)
                    selected.append({"delta": delta, "canon": canon})
                except Exception as e:
                    print(f"  Invalid SYMBOLS entry ignored: {s} ({e})")
        else:
            # Fallback to single SYMBOL env var or default set at init
            env_symbol = _strip_quotes(os.getenv("SYMBOL", "")).strip()
            if env_symbol:
                try:
                    canon = to_ccxt(env_symbol)
                    delta = to_delta(canon)
                    selected.append({"delta": delta, "canon": canon})
                except Exception as e:
                    print(f"  Invalid SYMBOL env ignored: {env_symbol} ({e})")
            else:
                # final fallback to the pre-initialized single symbol
                selected = [{"delta": self.symbol, "canon": self.symbol_canonical}]

        # Ensure we always have at least one symbol
        if not selected:
            print("No valid symbols parsed from environment — using default symbol.")
            selected = [{"delta": self.symbol, "canon": self.symbol_canonical}]

        # Validate symbols exist on exchange at startup
        selected = self._validate_symbols(selected)
        if not selected:
            print("\033[91m[FATAL] No valid symbols found on Delta Exchange! Check your SYMBOLS in .env.\033[0m")
            sys.exit(1)

        self.symbols = selected
        self.reconcile_positions()

        # Notify selected symbols (use canonical forms)
        try:
            symbols_list = [s["canon"] for s in self.symbols]
            self.notifier.started(symbols_list, self.timeframe, self.dry_run, self.risk_pct, self.leverage)
        except Exception:
            pass
            
        last_status_sent = time.time()
        last_6h_status_sent = time.time() - (6 * 3600) + 60 # trigger 1 minute after start
        last_processed_update_id = 0
        
        # Flush old updates
        try:
            flush_updates = self.notifier.get_updates(offset=-1)
            if flush_updates:
                last_processed_update_id = flush_updates[0]["update_id"]
        except Exception:
            pass

        self.print_banner()
        print(f"Starting continuous polling loop for {len(self.symbols)} symbols (every {self.poll_interval}s)... Press Ctrl+C to stop.")
        print(f"Tracking: {', '.join(s['canon'] for s in self.symbols)}")
        cycle_count = 0

        try:
            while True:
                # Poll Telegram Updates
                req_offset = last_processed_update_id + 1 if last_processed_update_id > 0 else None
                updates = self.notifier.get_updates(offset=req_offset)
                for update in updates:
                    update_id = update.get("update_id", 0)
                    if update_id > last_processed_update_id:
                        last_processed_update_id = update_id
                        msg_text = update.get("message", {}).get("text", "").lower().strip()
                        callback_query = update.get("callback_query")
                        
                        parts = []
                        if callback_query:
                            cb_data = callback_query.get("data", "").lower()
                            cb_id = callback_query.get("id")
                            self.notifier.answer_callback(cb_id)
                            # Normalize callback data format to match msg format
                            if cb_data.startswith("close_"):
                                parts = ["close", cb_data.split("_")[1]]
                            elif cb_data.startswith("open_"):
                                _, cid, direction = cb_data.split("_")
                                parts = ["open", cid, direction]
                            elif cb_data.startswith("clear_"):
                                parts = ["clear", cb_data.split("_")[1]]
                            elif cb_data.startswith("sl_"):
                                _, cid = cb_data.split("_")
                                self.notifier.send(f"To update SL for {cid.upper()}, please send the command:\n`/sl {cid.upper()} <price>`", parse_mode="Markdown")
                        elif msg_text:
                            if msg_text in ["/logs", "logs"]:
                                last_6h_status_sent = 0
                            parts = msg_text.split()
                            
                        if len(parts) >= 3 and parts[0] == "/sl" and parts[1].startswith("c"):
                            try:
                                idx = int(parts[1][1:]) - 1
                                new_sl = float(parts[2])
                                if 0 <= idx < len(self.symbols):
                                    sym_canon = self.symbols[idx]["canon"]
                                    pos = self.positions.get(sym_canon)
                                    if pos:
                                        pos["trail_stop"] = new_sl
                                        pos["stop_price"] = new_sl
                                        self.notifier.send(f"✅ SL for {sym_canon} manually updated to {new_sl:,.2f}")
                                    else:
                                        self.notifier.send(f"❌ No active position for {sym_canon}")
                            except Exception:
                                self.notifier.send("❌ Invalid format. Use: `/sl c1 65000`", parse_mode="Markdown")
                                
                        elif len(parts) >= 2 and parts[0] == "close" and parts[1].startswith("c"):
                            try:
                                idx = int(parts[1][1:]) - 1
                                if 0 <= idx < len(self.symbols):
                                    sym_canon = self.symbols[idx]["canon"]
                                    self._force_close[sym_canon] = True
                                    self.notifier.send(f"⏳ Command received: Queued CLOSE for {sym_canon} (will execute on next poll).")
                            except Exception:
                                pass
                        elif len(parts) >= 3 and parts[0] == "open" and parts[1].startswith("c"):
                            try:
                                idx = int(parts[1][1:]) - 1
                                direction = parts[2]
                                if 0 <= idx < len(self.symbols) and direction in ["long", "short"]:
                                    sym_canon = self.symbols[idx]["canon"]
                                    self._force_open[sym_canon] = direction
                                    self.notifier.send(f"⏳ Command received: Queued OPEN {direction.upper()} for {sym_canon} (will execute on next poll).")
                            except Exception:
                                pass
                        elif len(parts) >= 2 and parts[0] == "clear" and parts[1].startswith("c"):
                            try:
                                idx = int(parts[1][1:]) - 1
                                if 0 <= idx < len(self.symbols):
                                    sym_canon = self.symbols[idx]["canon"]
                                    if sym_canon in self.positions:
                                        del self.positions[sym_canon]
                                        self.notifier.send(f"✅ Local state cleared. Bot now thinks position for {sym_canon} is closed.")
                                    else:
                                        self.notifier.send(f"❌ Already clear for {sym_canon}.")
                            except Exception:
                                pass

                # Send 12-hour startup log update
                if time.time() - last_status_sent >= 12 * 3600:
                    try:
                        symbols_list = [s["canon"] for s in self.symbols]
                        self.notifier.started(symbols_list, self.timeframe, self.dry_run, self.risk_pct, self.leverage)
                    except Exception:
                        pass
                    last_status_sent = time.time()

                # Send 6-hour professional open positions status
                if time.time() - last_6h_status_sent >= 6 * 3600:
                    lines = ["🌟 *CRYPTO ALGO STATUS* 🌟\n_Open Positions:_"]
                    keyboard = []
                    
                    for idx, sym in enumerate(self.symbols):
                        canon = sym["canon"]
                        pos = self.positions.get(canon)
                        if pos:
                            direction = pos["direction"].upper()
                            pnl_str = f"PnL: Unknown"
                            try:
                                ticker = self.client.get_ticker(sym["delta"])
                                curr_px = float(ticker.get("mark_price", pos["entry_price"]))
                                if pos["direction"] == "long":
                                    pnl = (curr_px - pos["entry_price"]) * pos["size"]
                                else:
                                    pnl = (pos["entry_price"] - curr_px) * pos["size"]
                                pnl_str = f"PnL: {pnl:+.2f} USDT"
                            except Exception:
                                pass
                            lines.append(f"🔹 `[C{idx+1}]` *{canon}* {direction} | Size: {pos['size']} | {pnl_str} | SL: {pos.get('trail_stop', 0):.2f}")
                            
                            # Add buttons for active position
                            keyboard.append([
                                {"text": f"Close C{idx+1}", "callback_data": f"close_c{idx+1}"},
                                {"text": f"Update SL C{idx+1}", "callback_data": f"sl_c{idx+1}"}
                            ])
                            keyboard.append([
                                {"text": f"Clear C{idx+1}", "callback_data": f"clear_c{idx+1}"},
                                {"text": f"Force Long", "callback_data": f"open_c{idx+1}_long"},
                                {"text": f"Force Short", "callback_data": f"open_c{idx+1}_short"}
                            ])
                        else:
                            lines.append(f"🔸 `[C{idx+1}]` *{canon}* None")
                            
                            # Add buttons to open new position
                            keyboard.append([
                                {"text": f"Long C{idx+1}", "callback_data": f"open_c{idx+1}_long"},
                                {"text": f"Short C{idx+1}", "callback_data": f"open_c{idx+1}_short"}
                            ])
                            
                    reply_markup = {"inline_keyboard": keyboard}
                    
                    try:
                        self.notifier.send("\n".join(lines), parse_mode="Markdown", reply_markup=reply_markup)
                    except Exception:
                        pass
                    last_6h_status_sent = time.time()

                cycle_count += 1
                cycle_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                print(f"\n{'─'*65}")
                print(f"  Cycle #{cycle_count} | {cycle_ts} | {len(self.symbols)} symbols")
                print(f"{'─'*65}")

                for sym in self.symbols:
                    try:
                        # set current symbol and run a single check
                        self.symbol = sym["delta"]
                        self.symbol_canonical = sym["canon"]
                        self.run_trading_cycle()
                    except Exception as e:
                        print(f"  [{sym['canon']}] \033[91mUnexpected error:\033[0m {e}")
                        import traceback
                        traceback.print_exc()
                    # small pause between symbols to reduce burst volume
                    time.sleep(0.5)

                # wait until next full polling cycle
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            print("\nStopping trader bot. Goodbye!")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    trader = DeltaTrader()
    trader.start_loop()

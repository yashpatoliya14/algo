"""
Delta Exchange Live & Paper Trader — XAUTUSD SuperTrend + PAXGUSD Hedge Grid
============================================================================
Live/paper executor for the project's single strategy. All trade LOGIC lives
in `gold_hedge_engine.GoldHedgeStrategy`; this module only:
  - fetches XAUT 4H candles + SuperTrend (signal) and XAUT/PAXG mark prices,
  - feeds them to the shared decision core once per poll,
  - translates the returned Actions into Delta orders,
  - persists state, reconciles with the exchange, logs orders, and drives
    Telegram control.

Because the backtest (`gold_hedge_backtest.py`) and this trader call the SAME
`GoldHedgeStrategy.step()`, their logic can never diverge — they differ only
in sampling rate (backtest = 4H close; live = mark price each poll).

Strategy: SuperTrend(10,3) on XAUTUSD 4H.
  Bull flip -> LONG `main_lots` XAUT (stop = trailing SuperTrend line, +10% TP);
  each +1% step SHORTS 1 lot PAXG (max 5); a 1% retrace closes the top lot; a
  re-cross re-adds it; +10% or bear flip flattens everything. Bear flip mirrors.
Sizing: 1 lot = 1 contract (both symbols have contract_value = 0.001 oz).

Setup:
    1. Copy `.env.example` to `.env`, fill DELTA_API_KEY / DELTA_API_SECRET.
    2. Paper-run first:  DRY_RUN=true  python delta_trader.py
    3. Go live only when ready:  DRY_RUN=false  python delta_trader.py
"""

import email.utils
import hashlib
import hmac
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import requests

try:
    import websocket  # provided by the `websocket-client` package
except ImportError:
    websocket = None

from gold_hedge_engine import GoldHedgeParams, GoldHedgeStrategy, compute_signals, Action
from telegram_notifier import TelegramNotifier


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

                    if err_code == "expired_signature":
                        server_time = err_info.get("context", {}).get("server_time")
                        if server_time and not self._retrying:
                            self.time_offset = int(server_time) - int(time.time())
                            self._retrying = True
                            try:
                                return self._request(method, path, params=params, payload=payload, auth=auth)
                            finally:
                                self._retrying = False

                    if err_code == "ip_not_whitelisted_for_api_key":
                        client_ip = err_info.get("context", {}).get("client_ip", "Unknown")
                        print(f"\n\033[93m[DELTA API ERROR] IP Whitelist Restriction!\033[0m")
                        print(f"  Your current public IP: \033[1m\033[96m{client_ip}\033[0m")
                        print(f"  \033[97mAction Required: Add IP '{client_ip}' to your Delta Exchange API Key whitelist.\033[0m\n")
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

    def _ensure_product_map(self):
        if not hasattr(self, '_product_map'):
            self._product_map = {}
            try:
                for p in self.get_products():
                    self._product_map[p.get("symbol")] = p.get("id")
            except Exception:
                pass

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        """Set position leverage."""
        self._ensure_product_map()
        product_id = self._product_map.get(symbol)
        if not product_id:
            raise ValueError(f"Product ID not found for symbol: {symbol}")
        payload = {"leverage": str(leverage)}
        return self._request("POST", f"/v2/products/{product_id}/orders/leverage", payload=payload, auth=True)
    def place_order(self, symbol: str, size: int, side: str, order_type: str = "market_order",
                    stop_price: float = None, limit_price: float = None, reduce_only: bool = False) -> dict:
        """Place an order. side: 'buy'|'sell'; order_type: market_order|limit_order|stop_market_order."""
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
        if limit_price is not None:
            payload["limit_price"] = str(round(limit_price, 2))
        if reduce_only:
            payload["reduce_only"] = True
        return self._request("POST", "/v2/orders", payload=payload, auth=True)

    def cancel_order_by_id(self, order_id: int | str, product_id: int = None, symbol: str = None) -> dict:
        """Cancel a single order by its ID."""
        payload = {"id": int(order_id) if str(order_id).isdigit() else order_id}
        if not product_id and symbol:
            self._ensure_product_map()
            product_id = self._product_map.get(symbol)
        if product_id:
            payload["product_id"] = product_id
        return self._request("DELETE", "/v2/orders", payload=payload, auth=True)

    def cancel_all_orders(self, symbol: str) -> dict:
        """Cancel ALL pending open orders for a symbol (use sparingly)."""
        self._ensure_product_map()
        product_id = self._product_map.get(symbol)
        if product_id:
            return self._request("DELETE", "/v2/orders/all", payload={"product_id": product_id}, auth=True)
        return self._request("DELETE", "/v2/orders/all", payload={"product_symbol": symbol}, auth=True)


# ============================================================================
# MARKET FEED — Delta Exchange WebSocket (public market-data channels only)
# ============================================================================
class MarketFeed:
    """Push-based market data for the strategy: a rolling candle buffer for the
    main symbol (SuperTrend history) + latest mark prices for main & hedge.

    Uses only PUBLIC channels (candlestick + v2/ticker), so no WS auth is
    needed. Orders/positions/reconciliation stay on REST. Runs in a daemon
    thread with auto-reconnect and an app-level ping; a staleness age lets the
    caller refuse to trade on a dead socket.
    """

    def __init__(self, client: "DeltaClient", main_symbol: str, hedge_symbol: str,
                 timeframe: str, max_bars: int = 300):
        self.client = client
        self.main_symbol = main_symbol
        self.hedge_symbol = hedge_symbol
        self.timeframe = timeframe.strip().lower()
        self.max_bars = max_bars
        self.ws_url = self._derive_ws_url(client.base_url)

        self._lock = threading.Lock()
        self.event = threading.Event()      # set on each ticker update (wakes the main loop)
        self._candles: dict = {}             # candle_start_time(sec) -> {o,h,l,c,v}
        self._marks: dict = {}               # symbol -> (price, monotonic_ts)
        self._stop = False
        self._ws = None

    @staticmethod
    def _derive_ws_url(base_url: str) -> str:
        host = base_url.split("://", 1)[-1].strip("/")
        if "testnet" in host:
            return "wss://socket-ind.testnet.deltaex.org"
        if host.startswith("api."):
            host = "socket." + host[len("api."):]
        else:
            host = "socket." + host
        return f"wss://{host}"

    def _candle_channel(self) -> str:
        return f"candlestick_{self.timeframe}"

    def _tf_seconds(self) -> int:
        tf = self.timeframe
        if tf.endswith("h"):
            return int(tf[:-1]) * 3600
        if tf.endswith("m"):
            return int(tf[:-1]) * 60
        if tf.endswith("d"):
            return int(tf[:-1]) * 86400
        return 14400

    def _trim(self):
        if len(self._candles) > self.max_bars:
            for k in sorted(self._candles)[:-self.max_bars]:
                del self._candles[k]

    # -- lifecycle ------------------------------------------------------------
    def start(self):
        if websocket is None:
            raise RuntimeError("websocket-client not installed. Run: pip install -r requirements.txt")
        self._bootstrap()
        threading.Thread(target=self._run_forever, daemon=True).start()
        threading.Thread(target=self._ping_loop, daemon=True).start()

    def stop(self):
        self._stop = True
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass
    # __FEED_APPEND__

    # -- REST bootstrap so SuperTrend has warmup before WS candles arrive -----
    def _bootstrap(self):
        try:
            now = int(time.time())
            start = now - self.max_bars * self._tf_seconds()
            raw = self.client.get_candles(self.main_symbol, self.timeframe, start, now)
            with self._lock:
                for c in raw:
                    st = int(c["time"])   # REST candle time is in seconds
                    self._candles[st] = {"open": float(c["open"]), "high": float(c["high"]),
                                         "low": float(c["low"]), "close": float(c["close"]),
                                         "volume": float(c.get("volume", 0) or 0)}
                self._trim()
            print(f"  [WS] bootstrapped {len(raw)} {self.timeframe} candles via REST")
        except Exception as e:
            print(f"  [WS] candle bootstrap failed: {e}")

    # -- socket loop ----------------------------------------------------------
    def _run_forever(self):
        while not self._stop:
            try:
                self._ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=0)   # app-level ping handled below
            except Exception as e:
                print(f"  [WS] run_forever error: {e}")
            if self._stop:
                break
            time.sleep(3)
            print("  [WS] reconnecting ...")

    def _ping_loop(self):
        while not self._stop:
            time.sleep(25)
            try:
                if self._ws:
                    self._ws.send(json.dumps({"type": "ping"}))
            except Exception:
                pass

    def _on_open(self, ws):
        sub = {"type": "subscribe", "payload": {"channels": [
            {"name": self._candle_channel(), "symbols": [self.main_symbol]},
            {"name": "v2/ticker", "symbols": [self.main_symbol, self.hedge_symbol]},
        ]}}
        try:
            ws.send(json.dumps({"type": "enable_heartbeat"}))
            ws.send(json.dumps(sub))
            print(f"  [WS] connected {self.ws_url} — subscribed {self._candle_channel()} + v2/ticker")
        except Exception as e:
            print(f"  [WS] subscribe failed: {e}")

    def _on_error(self, ws, error):
        print(f"  [WS] error: {error}")

    def _on_close(self, ws, code, msg):
        print(f"  [WS] closed ({code})")

    def _on_message(self, ws, message):
        try:
            m = json.loads(message)
        except Exception:
            return
        mtype = m.get("type", "")
        now = time.monotonic()
        if mtype == "v2/ticker":
            sym = m.get("symbol")
            price = m.get("mark_price") or m.get("close") or m.get("last_price")
            if sym and price is not None:
                try:
                    with self._lock:
                        self._marks[sym] = (float(price), now)
                    self.event.set()
                except (TypeError, ValueError):
                    pass
        elif mtype.startswith("candlestick"):
            try:
                st = int(m["candle_start_time"]) // 1_000_000   # µs -> s
                with self._lock:
                    self._candles[st] = {"open": float(m["open"]), "high": float(m["high"]),
                                         "low": float(m["low"]), "close": float(m["close"]),
                                         "volume": float(m.get("volume", 0) or 0)}
                    self._trim()
            except Exception:
                pass

    # -- thread-safe reads ----------------------------------------------------
    def candle_df(self):
        """Rolling OHLCV DataFrame indexed by UTC timestamp (or None if empty)."""
        with self._lock:
            candles = dict(self._candles)
        if not candles:
            return None
        rows = [{"ts": pd.to_datetime(st, unit="s", utc=True), **candles[st]}
                for st in sorted(candles)]
        return pd.DataFrame(rows).set_index("ts")

    def marks(self):
        """Return (main_mark, hedge_mark, age_seconds_of_main_mark)."""
        with self._lock:
            xaut = self._marks.get(self.main_symbol)
            pax = self._marks.get(self.hedge_symbol)
        xaut_p = xaut[0] if xaut else None
        pax_p = pax[0] if pax else None
        age = (time.monotonic() - xaut[1]) if xaut else float("inf")
        return xaut_p, pax_p, age

# ============================================================================
# GOLD HEDGE TRADER — thin executor around GoldHedgeStrategy
# ============================================================================

class GoldHedgeTrader:
    def __init__(self):
        def env(key: str, default: str = "") -> str:
            v = os.getenv(key, default).strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1].strip()
            return v

        self.api_key = env("DELTA_API_KEY")
        self.api_secret = env("DELTA_API_SECRET")
        self.base_url = env("DELTA_BASE_URL", "https://api.india.delta.exchange")

        self.main_symbol = env("MAIN_SYMBOL", "XAUTUSD")
        self.hedge_symbol = env("HEDGE_SYMBOL", "PAXGUSD")
        self.timeframe = env("TIMEFRAME", "4h")
        self.leverage = int(env("LEVERAGE", "5"))
        self.dry_run = env("DRY_RUN", "true").lower() == "true"
        self.poll_interval = int(env("POLL_INTERVAL_SEC", "60"))
        self.usd_inr = float(env("USD_INR_RATE", "86.5"))

        # WebSocket-feed tuning
        self.stale_after = float(env("STALE_AFTER_SEC", "90"))   # refuse to trade if feed older
        self.ws_min_cycle = float(env("WS_MIN_CYCLE_SEC", "1"))  # throttle floor between cycles
        self.safety_tick = float(env("SAFETY_TICK_SEC", "5"))    # wake even if the market is quiet
        self.log_interval = float(env("LOG_INTERVAL_SEC", "30")) # throttle the routine status line

        self.params = GoldHedgeParams(
            st_period=int(env("ST_PERIOD", "10")),
            st_mult=float(env("ST_MULT", "3.0")),
            main_lots=int(env("MAIN_LOTS", "10")),
            hedge_lots_per_step=int(env("HEDGE_LOTS_PER_STEP", "1")),
            max_hedge_lots=int(env("HEDGE_MAX_LOTS", "5")),
            step_pct=float(env("STEP_PCT", "1.0")),
            tp_pct=float(env("TP_PCT", "10.0")),
            main_symbol=self.main_symbol,
            hedge_symbol=self.hedge_symbol,
        )

        self.client = DeltaClient(self.api_key, self.api_secret, self.base_url)
        self.notifier = TelegramNotifier()
        self.strat = GoldHedgeStrategy(self.params)
        self.feed = MarketFeed(self.client, self.main_symbol, self.hedge_symbol, self.timeframe)

        # contract specs for USD PnL (both gold symbols are 0.001 oz/contract)
        self.contract_values = {}
        try:
            for p in self.client.get_products():
                if "symbol" in p and "contract_value" in p:
                    self.contract_values[p["symbol"]] = float(p["contract_value"])
        except Exception as e:
            print(f"[WARN] Failed to load contract specs: {e}")

        # execution bookkeeping (money/orders live here; strat holds decisions)
        self.main = None        # {dir, entry_price, size, entry_time, stop_price, stop_order_id}
        self.hedge_lots = {}    # step(int) -> {side, entry_price, size, entry_time}
        self._entered_flip_ts = None   # closed-bar ts we last opened on (re-entry guard)
        self._last_pax = None          # last good PAXG mark (fallback)

        # telegram manual control
        self._force_close = False
        self._force_open = None        # "long" | "short"
        self._want_status = False
        self._force_clear = False      # queued 'clear' (processed on the main thread)
        self._stop_threads = False     # signals the telegram thread to exit
        self._last_log = 0.0           # monotonic ts of last routine status line

        self.state_file = Path(os.path.dirname(os.path.abspath(__file__))) / "trader_state.json"
        self.load_state()
    # -- state persistence ----------------------------------------------------
    def save_state(self):
        try:
            state = {
                "strat": {
                    "pos": self.strat.pos,
                    "entry_price": self.strat.entry_price,
                    "top": self.strat.top,
                    "hedges": self.strat.hedges,
                },
                "main": self.main,
                "hedge_lots": {str(k): v for k, v in self.hedge_lots.items()},
                "entered_flip_ts": self._entered_flip_ts,
                "last_pax": self._last_pax,
            }
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            print(f"  [WARN] Failed to save state: {e}")

    def load_state(self):
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file) as f:
                s = json.load(f)
            st = s.get("strat", {})
            self.strat.pos = st.get("pos")
            self.strat.entry_price = st.get("entry_price")
            self.strat.top = st.get("top", 0) or 0
            self.strat.hedges = st.get("hedges", []) or []
            self.main = s.get("main")
            self.hedge_lots = {int(k): v for k, v in s.get("hedge_lots", {}).items()}
            self._entered_flip_ts = s.get("entered_flip_ts")
            self._last_pax = s.get("last_pax")
            print(f"  [STATE] Loaded from {self.state_file} (pos={self.strat.pos}, hedges={len(self.hedge_lots)})")
        except Exception as e:
            print(f"  [WARN] Failed to load state: {e}")

    def record_order(self, order_type: str, symbol: str, order_id: str, details: dict):
        """Append every real order to cache/orders.log (rotates at 1 MB)."""
        try:
            os.makedirs("cache", exist_ok=True)
            log = "cache/orders.log"
            if os.path.exists(log) and os.path.getsize(log) > 1 * 1024 * 1024:
                old = "cache/orders.old.log"
                if os.path.exists(old):
                    os.remove(old)
                os.rename(log, old)
            entry = json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
                                "type": order_type, "symbol": symbol, "order_id": order_id, **details})
            with open(log, "a") as f:
                f.write(entry + "\n")
        except Exception as e:
            print(f"  [WARN] Failed to record order: {e}")

    # -- data helpers ---------------------------------------------------------
    def _cval(self, symbol: str) -> float:
        return self.contract_values.get(symbol, self.params.contract_oz)

    def _tf_seconds(self) -> int:
        tf = self.timeframe.strip().lower()
        if tf.endswith("h"):
            return int(tf[:-1]) * 3600
        if tf.endswith("m"):
            return int(tf[:-1]) * 60
        if tf.endswith("d"):
            return int(tf[:-1]) * 86400
        return 14400

    def _mark_price(self, symbol: str, fallback=None):
        # Prefer the pushed WS mark; fall back to REST only if the cache is empty.
        xaut, pax, _ = self.feed.marks()
        cached = xaut if symbol == self.main_symbol else pax if symbol == self.hedge_symbol else None
        if cached is not None:
            return float(cached)
        try:
            t = self.client.get_ticker(symbol)
            mp = t.get("mark_price") or t.get("close")
            if mp is not None:
                return float(mp)
        except Exception as e:
            print(f"  [WARN] Ticker fetch failed for {symbol}: {e}")
        return fallback

    def fetch_signals(self) -> pd.DataFrame:
        """XAUT candles + SuperTrend from the WS buffer. Last row is the forming
        bar; iloc[-2] is the last closed bar (same contract as the old REST path)."""
        df = self.feed.candle_df()
        if df is None or len(df) < 3:
            raise RuntimeError(f"No candles for {self.main_symbol} (feed warming up)")
        df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
        df = df.sort_index()
        sig = compute_signals(df, self.params).dropna(subset=["st_dir", "st_val"])
        if len(sig) < 3:
            raise RuntimeError("Not enough candles for SuperTrend")
        return sig
    # -- reconciliation -------------------------------------------------------
    def _flatten_local(self):
        self.strat.reset()
        self.main = None
        self.hedge_lots = {}

    def reconcile(self):
        """Light reconciliation of the MAIN leg with the exchange (live only).

        NOTE: a netted exchange position cannot reveal per-lot grid entries, so
        the hedge grid is NOT auto-reconstructed. On a detected desync, prefer
        `clear` (reset local) or `close` (flatten) via Telegram.
        """
        if self.dry_run:
            return
        try:
            positions = self.client.get_positions()
        except Exception as e:
            print(f"  [WARN] Reconcile fetch failed: {e}")
            return
        by_sym = {}
        for p in positions:
            s = p.get("product_symbol", p.get("symbol", ""))
            if s:
                by_sym[s] = p
        main_size = float(by_sym.get(self.main_symbol, {}).get("size", 0) or 0)

        if self.strat.pos is not None and main_size == 0:
            print(f"  [STATE] Local shows {self.strat.pos} but exchange flat on {self.main_symbol}. Clearing.")
            if self.main and self.main.get("stop_order_id"):
                try:
                    self.client.cancel_order_by_id(self.main["stop_order_id"], symbol=self.main_symbol)
                except Exception:
                    pass
            self._flatten_local()
        elif self.strat.pos is None and main_size != 0:
            direction = "long" if main_size > 0 else "short"
            entry = float(by_sym[self.main_symbol].get("entry_price", 0) or 0)
            print(f"  [STATE] [WARN] Exchange has {direction} {abs(main_size)} on {self.main_symbol} but local is flat. "
                  f"Adopting main leg (hedge grid NOT reconstructed).")
            mark = self._mark_price(self.main_symbol, fallback=entry) or entry
            step_size = entry * self.params.step_pct / 100.0
            travelled = int(abs(mark - entry) / step_size) if step_size else 0
            self.strat.pos = direction
            self.strat.entry_price = entry
            self.strat.top = min(travelled, self.params.max_hedge_lots)  # avoid re-adding phantom lots
            self.strat.hedges = []
            self.main = {"dir": direction, "entry_price": entry, "size": abs(main_size),
                         "entry_time": datetime.now(timezone.utc).isoformat(),
                         "stop_price": None, "stop_order_id": None}
        self.save_state()

    # -- order execution ------------------------------------------------------
    def _apply_action(self, a, st_val: float, xaut_price: float, pax_price: float):
        if a.kind == "open_main":
            self._open_main(a, st_val)
        elif a.kind == "close_main":
            self._close_main(a)
        elif a.kind == "open_hedge":
            self._open_hedge(a, pax_price)
        elif a.kind == "close_hedge":
            self._close_hedge(a, pax_price)

    def _place_main_stop(self, direction: str, size: int, stop_price: float):
        if self.dry_run:
            return None
        exit_side = "sell" if direction == "long" else "buy"
        try:
            res = self.client.place_order(self.main_symbol, size, exit_side, "stop_market_order",
                                          stop_price=stop_price, reduce_only=True)
            oid = res.get("result", {}).get("id") or res.get("id")
            self.record_order("stop_market_order", self.main_symbol, str(oid),
                              {"direction": direction, "side": exit_side, "size": size,
                               "stop_price": stop_price, "reduce_only": True})
            print(f"  [LIVE ORDER] Main stop @ ${stop_price:,.2f} (#{oid})")
            return oid
        except Exception as e:
            print(f"  [WARN] Failed to place main stop @ ${stop_price:,.2f}: {e}")
            return None
    def _open_main(self, a, st_val: float):
        direction = a.direction
        size = self.params.main_lots
        side = "buy" if direction == "long" else "sell"
        entry_px = a.price
        stop_oid = None
        if not self.dry_run:
            try:
                self.client.set_leverage(self.main_symbol, self.leverage)
            except Exception as e:
                print(f"  [WARN] set_leverage failed: {e}")
            res = self.client.place_order(self.main_symbol, size, side, "market_order")
            oid = res.get("result", {}).get("id", res.get("id"))
            self.record_order("market_order", self.main_symbol, str(oid),
                              {"direction": direction, "side": side, "size": size})
            time.sleep(1.0)
            try:
                for p in self.client.get_positions(self.main_symbol):
                    if p.get("product_symbol", p.get("symbol", "")) == self.main_symbol:
                        entry_px = float(p.get("entry_price", entry_px))
                        size = int(abs(float(p.get("size", size))))
                        break
            except Exception:
                pass
            stop_oid = self._place_main_stop(direction, size, st_val)
        self.main = {"dir": direction, "entry_price": entry_px, "size": size,
                     "entry_time": datetime.now(timezone.utc).isoformat(),
                     "stop_price": st_val, "stop_order_id": stop_oid}
        print(f"  \033[96m[OPEN MAIN]\033[0m {direction.upper()} {size} {self.main_symbol} "
              f"@ ${entry_px:,.2f} | stop(ST)=${st_val:,.2f}")
        try:
            self.notifier.trade_opened(self.main_symbol, direction, entry_px, size, st_val, self.leverage)
        except Exception:
            pass

    def _close_main(self, a):
        if not self.main:
            return
        direction = self.main["dir"]
        entry = self.main["entry_price"]
        size = self.main["size"]
        exit_px = a.price
        if not self.dry_run:
            side = "sell" if direction == "long" else "buy"
            # Close FIRST; only tear down the protective stop + local state once
            # the reduce-only close is confirmed. If it fails we must NOT cancel
            # the stop or clear self.main — otherwise the position is left open
            # on the exchange, unprotected, and untracked locally.
            try:
                res = self.client.place_order(self.main_symbol, size, side, "market_order", reduce_only=True)
                oid = res.get("result", {}).get("id", res.get("id"))
                self.record_order("market_order", self.main_symbol, str(oid),
                                  {"direction": direction, "side": side, "size": size,
                                   "reduce_only": True, "reason": a.reason})
            except Exception as e:
                print(f"  \033[91m[CLOSE MAIN FAILED]\033[0m {e} — position kept, stop left in place.")
                try:
                    self.notifier.send(f"⚠️ CLOSE MAIN FAILED on {self.main_symbol}: {e}\n"
                                       f"Position still OPEN with protective stop. Manual check advised.")
                except Exception:
                    pass
                return  # keep self.main and its stop_order_id intact for retry/reconcile
            if self.main.get("stop_order_id"):
                try:
                    self.client.cancel_order_by_id(self.main["stop_order_id"], symbol=self.main_symbol)
                except Exception as e:
                    print(f"  [WARN] cancel main stop failed (position already closed): {e}")
        cv = self._cval(self.main_symbol)
        pnl = (exit_px - entry) * size * cv if direction == "long" else (entry - exit_px) * size * cv
        pnl_inr = pnl * self.usd_inr
        print(f"  \033[91m[CLOSE MAIN]\033[0m {direction.upper()} @ ${exit_px:,.2f} | {a.reason} | PnL ${pnl:+,.2f}")
        try:
            self.notifier.exit(self.main_symbol, direction, exit_px, pnl, pnl_inr)
        except Exception:
            pass
        self.main = None
    def _open_hedge(self, a, pax_price: float):
        side = "sell" if a.side == "short" else "buy"
        size = self.params.hedge_lots_per_step
        if not self.dry_run:
            try:
                res = self.client.place_order(self.hedge_symbol, size, side, "market_order")
                oid = res.get("result", {}).get("id", res.get("id"))
                self.record_order("market_order", self.hedge_symbol, str(oid),
                                  {"side": side, "size": size, "step": a.step, "hedge": True})
            except Exception as e:
                print(f"  \033[91m[OPEN HEDGE FAILED]\033[0m step {a.step}: {e}")
                return
        self.hedge_lots[a.step] = {"side": a.side, "entry_price": pax_price, "size": size,
                                   "entry_time": datetime.now(timezone.utc).isoformat()}
        print(f"  \033[95m[OPEN HEDGE]\033[0m {a.side.upper()} lot #{a.step} {self.hedge_symbol} @ ${pax_price:,.2f}")
        try:
            self.notifier.send(f"➕ Hedge {a.side.upper()} lot #{a.step} {self.hedge_symbol} @ ${pax_price:,.2f}")
        except Exception:
            pass

    def _close_hedge(self, a, pax_price: float):
        h = self.hedge_lots.pop(a.step, None)
        size = h["size"] if h else self.params.hedge_lots_per_step
        entry = h["entry_price"] if h else a.hedge_entry
        close_side = "buy" if a.side == "short" else "sell"
        if not self.dry_run:
            try:
                res = self.client.place_order(self.hedge_symbol, size, close_side, "market_order", reduce_only=True)
                oid = res.get("result", {}).get("id", res.get("id"))
                self.record_order("market_order", self.hedge_symbol, str(oid),
                                  {"side": close_side, "size": size, "step": a.step,
                                   "reduce_only": True, "reason": a.reason, "hedge": True})
            except Exception as e:
                print(f"  \033[91m[CLOSE HEDGE FAILED]\033[0m step {a.step}: {e}")
        cv = self._cval(self.hedge_symbol)
        pnl = (entry - pax_price) * size * cv if a.side == "short" else (pax_price - entry) * size * cv
        print(f"  \033[95m[CLOSE HEDGE]\033[0m {a.side.upper()} lot #{a.step} @ ${pax_price:,.2f} | {a.reason} | PnL ${pnl:+,.2f}")
        try:
            self.notifier.send(f"➖ Closed hedge lot #{a.step} {self.hedge_symbol} @ ${pax_price:,.2f} | {a.reason} | PnL ${pnl:+,.2f}")
        except Exception:
            pass

    def _trail_main_stop(self, st_val: float):
        """Keep the on-exchange main stop tracking the SuperTrend line."""
        if not self.main:
            return
        if self.dry_run:
            self.main["stop_price"] = st_val
            return
        direction = self.main["dir"]
        cur = self.main.get("stop_price")
        if cur is None:
            self.main["stop_order_id"] = self._place_main_stop(direction, self.main["size"], st_val)
            self.main["stop_price"] = st_val
            return
        improved = st_val > cur if direction == "long" else st_val < cur
        if improved:
            old = self.main.get("stop_order_id")
            if old:
                try:
                    self.client.cancel_order_by_id(old, symbol=self.main_symbol)
                except Exception as e:
                    print(f"  [WARN] cancel old stop failed: {e}")
            self.main["stop_order_id"] = self._place_main_stop(direction, self.main["size"], st_val)
            self.main["stop_price"] = st_val
            print(f"  \033[92m[TRAIL] Main stop -> ${st_val:,.2f}\033[0m")
    # -- manual controls ------------------------------------------------------
    def _manual_flatten(self, xaut_price: float, pax_price: float, closed_ts: int):
        if self.strat.pos is None and not self.hedge_lots and not self.main:
            try:
                self.notifier.send("❌ Nothing to close — already flat.")
            except Exception:
                pass
            return
        print("  \033[96m>>> MANUAL CLOSE - flattening all legs <<<\033[0m")
        for step in sorted(self.hedge_lots.keys(), reverse=True):
            side = self.hedge_lots[step]["side"]
            entry = self.hedge_lots[step]["entry_price"]
            self._close_hedge(Action("close_hedge", side=side, step=step, hedge_entry=entry,
                                     reason="manual_close"), pax_price)
        if self.main:
            self._close_main(Action("close_main", direction=self.main["dir"], price=xaut_price,
                                    reason="manual_close"))
        self.strat.reset()
        self._entered_flip_ts = closed_ts  # don't re-open on the same flip bar
        try:
            self.notifier.send("✅ Manual close executed — all legs flat.")
        except Exception:
            pass

    def _send_status(self, xaut_price: float, st_dir: int, st_val: float):
        lines = [f"📊 Status — {self.main_symbol} / {self.hedge_symbol}",
                 f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}",
                 f"Position: {self.strat.pos or 'flat'}"]
        if self.main:
            lines.append(f"Main: {self.main['dir']} {self.main['size']} @ ${self.main['entry_price']:,.2f} "
                         f"| stop ${self.main.get('stop_price') or 0:,.2f}")
        lines.append(f"Hedge lots: {len(self.hedge_lots)} open (steps {sorted(self.hedge_lots)})")
        lines.append(f"ST: {'BULL' if st_dir == 1 else 'BEAR'} @ ${st_val:,.2f} | mark ${xaut_price:,.2f}")
        msg = "\n".join(lines)
        try:
            self.notifier.send(msg)
        except Exception:
            pass
        # console-safe (strip any non-ascii so a cp1252 terminal can't crash)
        print("  " + msg.replace("\n", " | ").encode("ascii", "ignore").decode())

    def print_banner(self):
        mode = "\033[93m[DRY RUN / PAPER]\033[0m" if self.dry_run else "\033[91m[LIVE REAL TRADING]\033[0m"
        p = self.params
        print("\n" + "=" * 68)
        print(f"   GOLD HEDGE TRADER - {p.main_symbol} SuperTrend + {p.hedge_symbol} grid {mode}")
        print("=" * 68)
        print(f"  Timeframe        : {self.timeframe}")
        print(f"  SuperTrend       : ({p.st_period}, {p.st_mult:g})")
        print(f"  Main lots        : {p.main_lots}    Leverage: {self.leverage}x")
        print(f"  Grid             : +{p.step_pct:g}% step, max {p.max_hedge_lots} lots, TP {p.tp_pct:g}%")
        print(f"  Poll interval    : {self.poll_interval}s")
        print(f"  API base         : {self.base_url}")
        print("=" * 68 + "\n")

    # -- main cycle -----------------------------------------------------------
    def run_cycle(self):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        try:
            sig = self.fetch_signals()
        except Exception as e:
            print(f"[{ts}] [ERROR] signal fetch failed: {e}")
            return

        closed = sig.iloc[-2]                 # last CLOSED bar drives SuperTrend
        st_dir = int(closed["st_dir"])
        st_val = float(closed["st_val"])
        flip_bull = bool(closed["flip_bull"])
        flip_bear = bool(closed["flip_bear"])
        closed_ts = int(closed.name.timestamp())

        xaut_price = self._mark_price(self.main_symbol, fallback=float(closed["close"]))
        pax_price = self._mark_price(self.hedge_symbol, fallback=self._last_pax)
        if pax_price is None:
            pax_price = xaut_price             # last resort; grid levels are XAUT-based
        else:
            self._last_pax = pax_price

        _, _, age = self.feed.marks()
        stale = age > self.stale_after

        # Throttle the routine status line (cycles now fire on every WS tick).
        now_m = time.monotonic()
        due = (now_m - self._last_log) >= self.log_interval
        if due:
            self._last_log = now_m
            print(f"[{ts}] {self.main_symbol} ${xaut_price:,.2f} | ST {'BULL' if st_dir == 1 else 'BEAR'} "
                  f"@ ${st_val:,.2f} | {self.hedge_symbol} ${pax_price:,.2f} | "
                  f"pos={self.strat.pos or 'flat'} hedges={len(self.hedge_lots)} | feed {age:.0f}s")

        if self._want_status:
            self._want_status = False
            self._send_status(xaut_price, st_dir, st_val)
        if self._force_clear:
            self._force_clear = False
            self._flatten_local()
            self.save_state()
            try:
                self.notifier.send("✅ Local state cleared (no orders sent).")
            except Exception:
                pass
            return
        if self._force_close:
            self._force_close = False
            self._manual_flatten(xaut_price, pax_price, closed_ts)
            self.save_state()
            return

        # Never act on a dead/stale socket — the position stays protected by its
        # exchange stop; queued force-open is preserved for when the feed recovers.
        if stale:
            if due:
                print(f"  \033[93m[WS] feed stale ({age:.0f}s > {self.stale_after:.0f}s) — "
                      f"skipping trading actions.\033[0m")
            return

        forced = self._force_open
        self._force_open = None

        # re-entry guard: don't re-open on a flip bar we already acted on
        fb, fr = flip_bull, flip_bear
        if self.strat.pos is None and closed_ts == self._entered_flip_ts:
            fb = fr = False
        if forced == "long":
            fb, fr = True, False
        elif forced == "short":
            fb, fr = False, True

        opened = False
        for a in self.strat.step(xaut_price, pax_price, st_dir, fb, fr):
            self._apply_action(a, st_val, xaut_price, pax_price)
            if a.kind == "open_main":
                opened = True
        if opened:
            self._entered_flip_ts = closed_ts

        if self.main:
            self._trail_main_stop(st_val)

        self.save_state()
    # -- run loop -------------------------------------------------------------
    def _handle_telegram(self, last_update_id: int) -> int:
        offset = last_update_id + 1 if last_update_id > 0 else None
        for update in self.notifier.get_updates(offset=offset):
            uid = update.get("update_id", 0)
            if uid <= last_update_id:
                continue
            last_update_id = uid
            msg = update.get("message", {})
            text = msg.get("text", "").lower().strip()
            chat_id = msg.get("chat", {}).get("id")
            parts = text.split()
            if not parts:
                continue
            cmd = parts[0]
            if cmd == "/start" and chat_id and self.notifier.subscribe(chat_id):
                requests.post(f"https://api.telegram.org/bot{self.notifier.token}/sendMessage",
                              json={"chat_id": chat_id, "text": "✅ Subscribed to Gold Hedge signals."})
            elif cmd == "/stop" and chat_id and self.notifier.unsubscribe(chat_id):
                requests.post(f"https://api.telegram.org/bot{self.notifier.token}/sendMessage",
                              json={"chat_id": chat_id, "text": "❌ Unsubscribed."})
            elif cmd in ("close", "/close"):
                self._force_close = True
                self.notifier.send("⏳ Queued CLOSE — flatten all legs on next cycle.")
            elif cmd in ("status", "/status"):
                self._want_status = True
            elif cmd in ("open", "/open") and len(parts) >= 2 and parts[1] in ("long", "short"):
                self._force_open = parts[1]
                self.notifier.send(f"⏳ Queued OPEN {parts[1].upper()} on next cycle.")
            elif cmd in ("clear", "/clear"):
                # Defer the state mutation to the main thread (avoids races).
                self._force_clear = True
                self.notifier.send("⏳ Queued CLEAR — resetting local state on next cycle.")
        return last_update_id

    def _telegram_loop(self):
        """Poll Telegram commands in a daemon thread so market data never blocks."""
        last_update_id = 0
        try:
            flush = self.notifier.get_updates(offset=-1)
            if flush:
                last_update_id = flush[0]["update_id"]
        except Exception:
            pass
        while not self._stop_threads:
            try:
                last_update_id = self._handle_telegram(last_update_id)
            except Exception as e:
                print(f"  [WARN] Telegram poll failed: {e}")
            time.sleep(2)

    def start_loop(self):
        if not self.dry_run and (not self.api_key or not self.api_secret):
            print("\033[91m[FATAL] LIVE mode but DELTA_API_KEY / DELTA_API_SECRET missing.\033[0m")
            sys.exit(1)
        if websocket is None:
            print("\033[91m[FATAL] websocket-client not installed. Run: pip install -r requirements.txt\033[0m")
            sys.exit(1)

        self.reconcile()
        self.print_banner()
        try:
            self.notifier.started([f"{self.main_symbol}/{self.hedge_symbol}"], self.timeframe,
                                  self.dry_run, 0.0, self.leverage)
        except Exception:
            pass

        # Start the WebSocket market feed + a Telegram command thread.
        self.feed.start()
        threading.Thread(target=self._telegram_loop, daemon=True).start()

        print(f"WebSocket feed live ({self.feed.ws_url}). Cycles are push-driven "
              f"(safety tick {self.safety_tick:g}s, min {self.ws_min_cycle:g}s). "
              f"Commands: open long|short, close, status, clear. Ctrl+C to stop.")
        cycle = 0
        last_cycle = 0.0
        try:
            while True:
                # Block until a market update is pushed, or wake on the safety tick
                # so TP re-checks and queued commands still run in a quiet market.
                self.feed.event.wait(timeout=self.safety_tick)
                self.feed.event.clear()

                # Throttle floor: a burst of ticks must not hammer the order path.
                gap = time.monotonic() - last_cycle
                if gap < self.ws_min_cycle:
                    time.sleep(self.ws_min_cycle - gap)
                last_cycle = time.monotonic()

                cycle += 1
                try:
                    self.run_cycle()
                except Exception as e:
                    print(f"  \033[91mCycle error:\033[0m {e}")
                    import traceback
                    traceback.print_exc()
        except KeyboardInterrupt:
            self._stop_threads = True
            self.feed.stop()
            print("\nStopping trader. Goodbye!")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    GoldHedgeTrader().start_loop()

import os
import requests
from typing import Optional

API_URL = "https://api.telegram.org/bot{token}/{method}"


def _post(method: str, data: dict) -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return {}
    url = API_URL.format(token=token, method=method)
    try:
        r = requests.post(url, json=data, timeout=10)
        return r.json()
    except Exception:
        return {}

def _get(method: str, params: dict = None) -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return {}
    url = API_URL.format(token=token, method=method)
    try:
        r = requests.get(url, params=params, timeout=10)
        return r.json()
    except Exception:
        return {}


class TelegramNotifier:
    def __init__(self, chat_id: Optional[str] = None):
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.on_signal = os.getenv("TELEGRAM_ON_SIGNAL", "true").lower() == "true"
        self.on_exec = os.getenv("TELEGRAM_ON_EXECUTION", "true").lower() == "true"
        self.on_exit = os.getenv("TELEGRAM_ON_EXIT", "true").lower() == "true"

    def send(self, text: str, parse_mode: Optional[str] = None, reply_markup: dict = None):
        if not self.chat_id or not self.token:
            return None
        payload = {"chat_id": self.chat_id, "text": text, "disable_notification": False}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return _post("sendMessage", payload)
        
    def answer_callback(self, callback_query_id: str, text: str = ""):
        if not self.token:
            return None
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return _post("answerCallbackQuery", payload)

    def signal(self, symbol: str, direction: str, signal_type: str, price: float):
        if not self.on_signal:
            return
        txt = f"Signal\nSymbol: {symbol}\nDirection: {direction.upper()}\nType: {signal_type}\nPrice: {price:.2f}"
        self.send(txt)

    def exit(self, symbol: str, direction: str, exit_price: float, pnl_usd: float, pnl_inr: float = 0.0):
        if not self.on_exit:
            return
        emoji = "🟢" if pnl_usd > 0 else "🔴"
        txt = (
            f"{emoji} <b>TRADE CLOSED</b>\n"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Direction:</b> {direction.upper()}\n"
            f"<b>Exit Price:</b> ${exit_price:,.2f}\n"
            f"<b>Final PnL:</b> ${pnl_usd:+,.2f}  (₹{pnl_inr:+,.2f})"
        )
        self.send(txt, parse_mode="HTML")

    def trade_opened(self, symbol: str, direction: str, entry_price: float, size: int, stop_price: float, leverage: int):
        if not self.on_exec:
            return
        txt = (
            f"🚀 <b>TRADE OPENED (EXACT)</b>\n"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Direction:</b> {direction.upper()}\n"
            f"<b>Avg Entry Price:</b> ${entry_price:,.2f}\n"
            f"<b>Contracts:</b> {size}\n"
            f"<b>Stop Loss:</b> ${stop_price:,.2f}\n"
            f"<b>Leverage:</b> {leverage}x"
        )
        self.send(txt, parse_mode="HTML")

    def started(self, symbols: list[str], timeframe: str, dry_run: bool, risk_pct: float, leverage: int):
        """Send a start/confirmation message with runtime settings."""
        mode = "DRY RUN / PAPER" if dry_run else "LIVE"
        txt = (
            f"Trader Started\nMode: {mode}\nTimeframe: {timeframe}\n"
            f"Symbols: {', '.join(symbols)}\nRisk %: {risk_pct}%\nLeverage: {leverage}x"
        )
        try:
            self.send(txt)
        except Exception:
            pass

    def signal_detailed(
        self,
        symbol: str,
        direction: str,
        signal_type: str,
        price: float,
        entry_price: float,
        size: int,
        stop_price: float,
        risk_pct: float,
        candle_time: str | None = None,
        trail_activation: float | None = None,
        trail_distance: float | None = None,
        tp_note: str | None = None,
    ):
        if not self.on_signal:
            return
        lines = [
            "Signal",
            f"Symbol: {symbol}",
            f"Direction: {direction.upper()}",
            f"Type: {signal_type}",
        ]
        if candle_time:
            lines.append(f"Candle Time: {candle_time}")
        lines.extend([
            f"Signal Price: {price:.2f}",
            f"Suggested Entry: {entry_price:.2f}",
            f"Size: {size}",
            f"Stop Loss: {stop_price:.2f}",
            f"Risk %: {risk_pct}%",
        ])
        if trail_activation is not None and trail_distance is not None:
            lines.append(f"Trail: activate after +{trail_activation:.2f}% move, then trail {trail_distance:.2f}% behind peak")
        lines.append(f"TP / Exit Plan: {tp_note or 'No fixed TP; exit on trailing stop or trend reversal'}")
        txt = "\n".join(lines)
        self.send(txt)

    def get_updates(self, offset: int = None) -> list:
        """Fetch latest telegram messages."""
        if not self.token:
            return []
        params = {"allowed_updates": '["message", "callback_query"]'}
        if offset is not None:
            params["offset"] = offset
        res = _get("getUpdates", params)
        if res and res.get("ok"):
            return res.get("result", [])
        return []

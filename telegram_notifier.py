import os
import requests
from typing import Optional

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ON_SIGNAL = os.getenv("TELEGRAM_ON_SIGNAL", "true").lower() == "true"
ON_EXEC = os.getenv("TELEGRAM_ON_EXECUTION", "true").lower() == "true"
ON_EXIT = os.getenv("TELEGRAM_ON_EXIT", "true").lower() == "true"

API_URL = "https://api.telegram.org/bot{token}/{method}"


def _post(method: str, data: dict) -> dict:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return {}
    url = API_URL.format(token=TELEGRAM_TOKEN, method=method)
    try:
        r = requests.post(url, json=data, timeout=10)
        return r.json()
    except Exception:
        return {}


class TelegramNotifier:
    def __init__(self, chat_id: Optional[str] = None):
        self.chat_id = chat_id or TELEGRAM_CHAT_ID

    def send(self, text: str, parse_mode: Optional[str] = None):
        if not self.chat_id or not TELEGRAM_TOKEN:
            return None
        payload = {"chat_id": self.chat_id, "text": text, "disable_notification": False}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return _post("sendMessage", payload)

    def signal(self, symbol: str, direction: str, signal_type: str, price: float):
        if not ON_SIGNAL:
            return
        txt = f"Signal\nSymbol: {symbol}\nDirection: {direction.upper()}\nType: {signal_type}\nPrice: {price:.2f}"
        self.send(txt)

    def execution(self, symbol: str, direction: str, size: int, entry_price: float, stop_price: float):
        if not ON_EXEC:
            return
        txt = (
            f"Execution\nSymbol: {symbol}\nDirection: {direction.upper()}\nSize: {size}\n"
            f"Entry: {entry_price:.2f}\nStop: {stop_price:.2f}"
        )
        self.send(txt)

    def exit(self, symbol: str, direction: str, exit_price: float, pnl: float):
        if not ON_EXIT:
            return
        txt = (
            f"Exit\nSymbol: {symbol}\nDirection: {direction.upper()}\nExit Price: {exit_price:.2f}\nPnL: {pnl:+.2f}"
        )
        self.send(txt)

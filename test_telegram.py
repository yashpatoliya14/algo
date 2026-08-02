from dotenv import load_dotenv
import os

load_dotenv()

from telegram_notifier import TelegramNotifier

n = TelegramNotifier()
print("TELEGRAM_BOT_TOKEN set?", bool(os.getenv("TELEGRAM_BOT_TOKEN")))
print("TELEGRAM_CHAT_ID set?", bool(os.getenv("TELEGRAM_CHAT_ID")))
res = n.send("Test message from Trend Rider bot (test_telegram.py). If you see this, Telegram is working.")
print("Response:", res)

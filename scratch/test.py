from dotenv import load_dotenv
load_dotenv()
from telegram_notifier import TelegramNotifier
notifier = TelegramNotifier()
res = notifier.send('🚀 <b>TRADE OPENED (EXACT)</b>\n<b>Symbol:</b> BTC/USD\n<b>Direction:</b> LONG\n<b>Avg Entry Price:</b> $50,000.50\n<b>Contracts:</b> 1\n<b>Stop Loss:</b> $49,000.00\n<b>Leverage:</b> 50x', parse_mode='HTML')
print(f"OK: {res.get('ok')}, Error: {res.get('description')}")

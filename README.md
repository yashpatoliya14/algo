# 4H Trend Rider — Delta Exchange Algo Trading

Short overview
- A 4-hour timeframe trend-following strategy (Trend Rider) implemented for Delta Exchange.
- Supports backtesting, per-symbol caching, and a live/paper trading loop with Telegram notifications.

Quick start
1. Create a Python 3.10+ venv and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill API keys + Telegram credentials.
3. Run backtests:
   ```bash
   python backtest_cli.py
   ```
4. Start live/paper trader (uses `SYMBOLS` env only):
   ```bash
   python delta_trader.py
   ```

Environment
- Use `.env` to configure: `DELTA_API_KEY`, `DELTA_API_SECRET`, `SYMBOLS`, `DRY_RUN`, `POLL_INTERVAL_SEC`, Telegram settings, and cache limits.

Telegram notifications
- The trader will send a startup confirmation and detailed signal/execution/exit messages when enabled in `.env`.

Repository layout
- See `soc/FILES.md` for per-file documentation and quick descriptions.

Contributing
- Open a PR with a clear description and tests for non-trivial logic changes.

Contact
- For implementation questions, refer to [ARCHITECTURE.md](ARCHITECTURE.md) and the `soc/FILES.md` file.

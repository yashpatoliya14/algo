# Source of Code (SOC) — File Reference

This file summarizes the purpose of each top-level file for sharing with developers.

- `ARCHITECTURE.md`: High-level architecture and algorithm explanation for the 4H Trend Rider.
- `README.md`: Project quick-start and overview (this file).
- `backtest_cli.py`: Command-line backtesting entrypoint; supports per-symbol/year caching and cache pruning.
- `crypto_trend_backtest.py`: Helpers for fetching historical data (ccxt) and list exchange products.
- `crypto_trend_algo.md`: Notes and ideas about the trend algorithm (documentation).
- `delta_trader.py`: Live/paper trading loop implementation; reads `SYMBOLS` from `.env`, fetches candles, evaluates signals, and places orders via Delta API.
- `delta_client.py` (integrated in `delta_trader.py`): Delta REST API v2 wrapper used by the trader.
- `telegram_notifier.py`: Wrapper around Telegram Bot API; sends start/signal/execution/exit messages.
- `trend_rider_engine.py`: Strategy indicator computations and backtest engine (`compute_indicators`, `run_trend_rider_backtest`).
- `symbol_utils.py`: Utilities to convert between canonical `BASE/QUOTE` and Delta/CCXT formats.
- `test_delta_order.py` / `test_telegram.py`: Small test scripts to validate order sending and Telegram connectivity.
- `requirements.txt`: Python dependencies list.
- `cache/`: Directory storing per-symbol/year JSON caches produced by backtests and data fetchers.

Notes for developers
- Environment is loaded from `.env` (see `.env.example`) — `delta_trader.py` now loads `.env` early so modules that read env vars receive correct values.
- Telegram credentials and toggles are read at runtime; ensure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are valid and that the bot can message the target chat.
- Symbol format: canonical `BASE/QUOTE` (e.g., `BTC/USDT`) — `symbol_utils` will normalize inputs.

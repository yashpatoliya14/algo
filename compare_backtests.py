"""Compare Python and Node Trend Rider backtest outputs trade by trade.

The script looks for persisted cache outputs from both implementations,
normalizes symbol naming and timestamps, and reports numeric mismatches at the
trade and summary level.

Usage:
    python compare_backtests.py BTCUSD 2024
    python compare_backtests.py BTC/USDT 2024

Optional overrides:
    python compare_backtests.py BTCUSD 2024 --python-cache cache/rider_2024.json
    python compare_backtests.py BTCUSD 2024 --node-cache node_version/cache/backtest_BTCUSD_2024.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from symbol_utils import normalize_canonical, to_delta


ROOT = Path(__file__).resolve().parent
PY_CACHE_DIR = ROOT / "cache"
NODE_CACHE_DIR = ROOT / "node_version" / "cache"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def fmt_ts(value: Any) -> str:
    if value in (None, "", "-"):
        return "-"
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return "-"
        try:
            return datetime.fromtimestamp(float(stripped), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return stripped
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    return str(value)


def round2(value: Any) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def parse_ts(value: Any) -> float:
    if value in (None, "", "-"):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped == "-":
            return 0.0
        try:
            return datetime.strptime(stripped, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            try:
                return float(stripped)
            except ValueError:
                return 0.0
    return 0.0


def normalize_python_trade(trade: dict[str, Any]) -> dict[str, Any]:
    entry_ts = parse_ts(trade.get("entry"))
    exit_ts = parse_ts(trade.get("exit"))
    return {
        "entry_ts": min(entry_ts, exit_ts) if entry_ts and exit_ts else entry_ts,
        "exit_ts": max(entry_ts, exit_ts) if entry_ts and exit_ts else exit_ts,
        "entry": trade.get("entry", "-"),
        "exit": trade.get("exit", "-"),
        "dir": trade.get("dir"),
        "entry_px": round2(trade.get("entry_px")),
        "exit_px": round2(trade.get("exit_px")),
        "pnl": round2(trade.get("pnl")),
    }


def normalize_node_trade(trade: dict[str, Any]) -> dict[str, Any]:
    entry_ts_raw = parse_ts(trade.get("entry_time"))
    exit_ts_raw = parse_ts(trade.get("exit_time"))
    entry_ts = min(entry_ts_raw, exit_ts_raw) if entry_ts_raw and exit_ts_raw else entry_ts_raw
    exit_ts = max(entry_ts_raw, exit_ts_raw) if entry_ts_raw and exit_ts_raw else exit_ts_raw
    return {
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "entry_time_raw": trade.get("entry_time"),
        "exit_time_raw": trade.get("exit_time"),
        "time_order_reversed": bool(entry_ts_raw and exit_ts_raw and entry_ts_raw > exit_ts_raw),
        "direction": trade.get("direction"),
        "entry_price": round2(trade.get("entry_price")),
        "exit_price": round2(trade.get("exit_price")),
        "pnl": round2(trade.get("pnl")),
    }


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def resolve_cache_file(base_dir: Path, prefixes: list[str], year: int, symbol: str | None) -> Path:
    symbol = (symbol or "").strip()
    canon = normalize_canonical(symbol) if symbol else ""
    safe_symbol = symbol.replace("/", "_") if symbol else ""
    canon_safe = canon.replace("/", "_") if canon else ""
    delta_symbol = to_delta(symbol) if symbol else ""

    candidates: list[Path] = []
    for prefix in prefixes:
        if symbol:
            candidates.extend([
                base_dir / f"{prefix}_{safe_symbol}_{year}.json",
                base_dir / f"{prefix}_{canon_safe}_{year}.json",
                base_dir / f"{prefix}_{delta_symbol}_{year}.json",
            ])
        candidates.append(base_dir / f"{prefix}_{year}.json")

    candidates = unique_paths(candidates)
    for candidate in candidates:
        if candidate.exists():
            return candidate

    year_matches = sorted(base_dir.glob(f"{prefixes[0]}*{year}.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if year_matches:
        if symbol:
            fragments = [frag for frag in {safe_symbol, canon_safe, delta_symbol} if frag]
            for fragment in fragments:
                for candidate in year_matches:
                    if fragment in candidate.name:
                        return candidate
        return year_matches[0]

    raise FileNotFoundError(f"No cache file found in {base_dir} for symbol={symbol!r}, year={year}")


def compare_value(label: str, left: float, right: float, tolerance: float) -> str | None:
    delta = right - left
    if abs(delta) <= tolerance:
        return None
    return f"{label}: python={left:.2f} node={right:.2f} delta={delta:+.4f}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-trade diff between Python and Node Trend Rider outputs")
    parser.add_argument("symbol", help="Symbol to compare, for example BTCUSD or BTC/USDT")
    parser.add_argument("year", type=int, help="Backtest year")
    parser.add_argument("--python-cache", dest="python_cache", help="Explicit Python cache JSON path")
    parser.add_argument("--node-cache", dest="node_cache", help="Explicit Node cache JSON path")
    parser.add_argument("--tolerance", type=float, default=0.01, help="Numeric tolerance for trade fields")
    args = parser.parse_args()

    python_path = Path(args.python_cache) if args.python_cache else resolve_cache_file(PY_CACHE_DIR, ["rider"], args.year, args.symbol)
    node_path = Path(args.node_cache) if args.node_cache else resolve_cache_file(NODE_CACHE_DIR, ["backtest"], args.year, args.symbol)

    python_data = load_json(python_path)
    node_data = load_json(node_path)

    python_trades = sorted(
        (normalize_python_trade(trade) for trade in python_data.get("trades", [])),
        key=lambda row: (row["entry_ts"], row["exit_ts"], row["dir"] or ""),
    )
    node_trades = sorted(
        (normalize_node_trade(trade) for trade in node_data.get("trades", [])),
        key=lambda row: (row["entry_ts"], row["exit_ts"], row["direction"] or ""),
    )

    print(f"Python cache: {python_path}")
    print(f"Node cache:   {node_path}")
    print(f"Trades: python={len(python_trades)} node={len(node_trades)}")

    summary_mismatches: list[str] = []
    python_metrics = python_data.get("metrics", {})
    node_stats = node_data.get("stats", {})

    summary_pairs = [
        ("total_trades", float(python_metrics.get("total_trades", 0)), float(node_stats.get("totalTrades", len(node_trades)))),
        ("win_rate", float(python_metrics.get("win_rate", 0)), float(node_stats.get("winRate", 0))),
        ("profit_factor", float(python_metrics.get("profit_factor", 0)), float(node_stats.get("profitFactor", 0))),
        ("max_drawdown", float(python_metrics.get("max_drawdown", 0)), float(node_stats.get("maxDrawdown", 0))),
        ("cagr", float(python_metrics.get("cagr", 0)), float(node_stats.get("cagr", 0))),
        ("final_equity", float(python_metrics.get("final_equity", 0)), float(node_data.get("equity", 0))),
        ("net_profit", float(python_metrics.get("net_profit", 0)), float(node_stats.get("totalPnl", 0))),
    ]
    for label, left, right in summary_pairs:
        message = compare_value(label, left, right, args.tolerance)
        if message:
            summary_mismatches.append(message)

    trade_mismatches: list[str] = []
    paired = min(len(python_trades), len(node_trades))
    for index in range(paired):
        py_trade = python_trades[index]
        node_trade = node_trades[index]

        py_entry = fmt_ts(py_trade.get("entry_ts"))
        py_exit = fmt_ts(py_trade.get("exit_ts"))
        node_entry = fmt_ts(node_trade.get("entry_ts"))
        node_exit = fmt_ts(node_trade.get("exit_ts"))

        field_mismatches: list[str] = []
        if py_trade.get("dir") != node_trade.get("direction"):
            field_mismatches.append(f"direction python={py_trade.get('dir')} node={node_trade.get('direction')}")
        if py_entry != node_entry:
            field_mismatches.append(f"entry_time python={py_entry} node={node_entry}")
        if py_exit != node_exit:
            field_mismatches.append(f"exit_time python={py_exit} node={node_exit}")
        if node_trade.get("time_order_reversed"):
            field_mismatches.append("node_time_order=reversed")

        entry_px = compare_value("entry_px", py_trade.get("entry_px", 0.0), node_trade.get("entry_price", 0.0), args.tolerance)
        exit_px = compare_value("exit_px", py_trade.get("exit_px", 0.0), node_trade.get("exit_price", 0.0), args.tolerance)
        pnl = compare_value("pnl", py_trade.get("pnl", 0.0), node_trade.get("pnl", 0.0), args.tolerance)

        for message in (entry_px, exit_px, pnl):
            if message:
                field_mismatches.append(message)

        if field_mismatches:
            trade_mismatches.append(
                f"#{index + 1} {py_entry} -> {py_exit}: " + " | ".join(field_mismatches)
            )

    if len(python_trades) != len(node_trades):
        trade_mismatches.append(
            f"trade count differs: python={len(python_trades)} node={len(node_trades)}"
        )

    if summary_mismatches:
        print("Summary mismatches:")
        for message in summary_mismatches:
            print(f"  - {message}")
    else:
        print("Summary mismatches: none")

    if trade_mismatches:
        print("Per-trade mismatches:")
        for message in trade_mismatches:
            print(f"  - {message}")
    else:
        print("Per-trade mismatches: none")

    return 1 if summary_mismatches or trade_mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
import re
from typing import Tuple

# Map common quote differences (adjust for your Delta listings)
DELTA_QUOTE_MAP = {"USDT": "USD"}


def normalize_canonical(sym: str) -> str:
    """Return canonical form 'BASE/QUOTE' uppercase."""
    if not sym or not isinstance(sym, str):
        raise ValueError("Invalid symbol")
    s = sym.strip().upper()
    if "/" in s:
        base, quote = s.split("/", 1)
    elif "-" in s:
        base, quote = s.split("-", 1)
    else:
        m = re.match(r"^([A-Z]+)([A-Z0-9]+)$", s)
        if m:
            base, quote = m.group(1), m.group(2)
        else:
            raise ValueError(f"Cannot parse symbol: {sym}")
    return f"{base}/{quote}"


def to_ccxt(sym: str) -> str:
    """Return CCXT symbol 'BASE/QUOTE'."""
    return normalize_canonical(sym)


def to_delta(sym: str, quote_map: dict | None = None) -> str:
    """Return Delta symbol without separator, applying optional quote mapping."""
    quote_map = quote_map or DELTA_QUOTE_MAP
    canon = normalize_canonical(sym)
    base, quote = canon.split("/")
    quote = quote_map.get(quote, quote)
    return f"{base}{quote}"

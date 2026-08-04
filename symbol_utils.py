
# Map common quote differences (adjust for your Delta listings)
DELTA_QUOTE_MAP = {"USDT": "USD"}

# Known quote currencies used for parsing unseparated symbols like "BTCUSD"
KNOWN_QUOTES = [
    "USDT", "USDC", "FDUSD",                    # stablecoins
    "USD", "EUR", "GBP", "INR",                  # fiat
    "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE",  # crypto quotes
]


def normalize_canonical(sym: str) -> str:
    """Return canonical form 'BASE/QUOTE' uppercase.
    
    Handles:
      - 'BTC/USDT'  -> 'BTC/USDT'   (already canonical)
      - 'BTC-USD'   -> 'BTC/USD'     (dash separator)
      - 'BTCUSD'    -> 'BTC/USD'     (no separator, known quote)
      - 'AVAXUSD'   -> 'AVAX/USD'    (no separator, known quote)
      - 'AVAXUSDT'  -> 'AVAX/USDT'   (no separator, known quote)
      - 'XAUTUSD'   -> 'XAUT/USD'    (prefers longest base)
    """
    if not sym or not isinstance(sym, str):
        raise ValueError("Invalid symbol")
    s = sym.strip().upper()

    if "/" in s:
        base, quote = s.split("/", 1)
    elif "-" in s:
        base, quote = s.split("-", 1)
    else:
        # Try all matching quote suffixes, pick the one giving the longest base
        # (i.e. shortest quote). This resolves XAUTUSD -> XAUT/USD not XAU/TUSD.
        candidates = []
        for q in KNOWN_QUOTES:
            if s.endswith(q) and len(s) > len(q):
                candidates.append((s[:-len(q)], q))

        if not candidates:
            raise ValueError(f"Cannot parse symbol: {sym}")

        # Prefer longest base (= shortest quote), breaking ties by KNOWN_QUOTES order
        base, quote = max(candidates, key=lambda pair: len(pair[0]))

    return f"{base}/{quote}"


def to_ccxt(sym: str) -> str:
    """Return CCXT symbol 'BASE/QUOTE'."""
    return normalize_canonical(sym)


def to_delta(sym: str, quote_map: dict | None = None) -> str:
    """Return Delta symbol without separator, applying optional quote mapping.
    
    Examples:
      'BTC/USDT' -> 'BTCUSD'
      'AVAX/USDT' -> 'AVAXUSD'
      'ETH/USD' -> 'ETHUSD'
    """
    quote_map = quote_map or DELTA_QUOTE_MAP
    canon = normalize_canonical(sym)
    base, quote = canon.split("/")
    quote = quote_map.get(quote, quote)
    return f"{base}{quote}"


def to_binance(sym: str) -> str:
    """Return Binance CCXT symbol, mapping USD -> USDT.
    
    Examples:
      'BTCUSD'    -> 'BTC/USDT'
      'BTC/USD'   -> 'BTC/USDT'
      'AVAXUSD'   -> 'AVAX/USDT'
      'ETH/USDT'  -> 'ETH/USDT'  (no change needed)
    """
    canon = normalize_canonical(sym)
    if canon.endswith("/USD"):
        canon = canon + "T"
    return canon


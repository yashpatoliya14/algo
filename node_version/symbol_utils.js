// Minimal symbol normalization utilities

function toCanonical(s) {
  if (!s) return s;
  s = s.trim();
  if (s.includes('/')) return s.toUpperCase();
  // e.g., BTCUSD -> BTC/USDT or BTC/USD? Keep exact quote if length 6/7
  if (s.length >= 6 && s.length <= 8) {
    // split into base and quote by last 3 or 4 chars
    const quote = s.slice(-4).toUpperCase();
    const base = s.slice(0, s.length - quote.length).toUpperCase();
    return `${base}/${quote}`;
  }
  return s.toUpperCase();
}

function toDelta(canon) {
  // Delta API expects product symbol likely as BASEQUOTE without '/'
  return canon.replace('/', '').toUpperCase();
}

module.exports = { toCanonical, toDelta };

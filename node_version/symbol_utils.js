// Symbol normalization utilities for Node.js (matching Python logic)

const DELTA_QUOTE_MAP = { "USDT": "USD" };

function toCanonical(s) {
  if (!s || typeof s !== 'string') return s;
  s = s.trim().toUpperCase();
  if (s.includes('/')) return s;
  if (s.includes('-')) {
    const parts = s.split('-');
    return `${parts[0]}/${parts[1]}`;
  }
  
  // Known quotes check
  const knownQuotes = ["USDT", "USD", "INR", "BTC"];
  for (const q of knownQuotes) {
    if (s.endsWith(q) && s.length > q.length) {
      const base = s.slice(0, s.length - q.length);
      return `${base}/${q}`;
    }
  }
  return s;
}

function toDelta(canon, quoteMap = DELTA_QUOTE_MAP) {
  const normalized = toCanonical(canon);
  if (!normalized.includes('/')) return normalized;
  let [base, quote] = normalized.split('/');
  quote = quoteMap[quote] || quote;
  return `${base}${quote}`;
}

module.exports = { toCanonical, toDelta };


const fs = require('fs');
const https = require('https');
const path = require('path');

// Load .env from project root if present
function loadDotenv(p) {
  try {
    const txt = fs.readFileSync(p, 'utf8');
    txt.split('\n').forEach(line => {
      line = line.trim();
      if (!line || line.startsWith('#')) return;
      const eq = line.indexOf('=');
      if (eq === -1) return;
      const key = line.slice(0, eq).trim();
      let val = line.slice(eq + 1).trim();
      if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
        val = val.slice(1, -1);
      }
      if (!process.env[key]) process.env[key] = val;
    });
  } catch (e) {}
}

const rootEnv = path.join(__dirname, '..', '.env');
loadDotenv(rootEnv);

const token = process.env.TELEGRAM_BOT_TOKEN;
const chatId = process.env.TELEGRAM_CHAT_ID;

if (!token || !chatId) {
  console.error('Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in environment');
  process.exit(1);
}

const payload = JSON.stringify({ chat_id: chatId, text: 'Node test message from Trend Rider (node_version/send_test_telegram.js)' });

const options = {
  method: 'POST',
  hostname: 'api.telegram.org',
  path: `/bot${token}/sendMessage`,
  headers: {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(payload)
  },
  timeout: 10000,
};

const req = https.request(options, res => {
  let data = '';
  res.on('data', ch => data += ch);
  res.on('end', () => {
    try { console.log('Response:', JSON.parse(data)); } catch (e) { console.log('Raw response:', data); }
  });
});

req.on('error', e => { console.error('Request error', e); process.exit(1); });
req.write(payload);
req.end();

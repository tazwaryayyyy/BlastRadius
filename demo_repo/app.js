/**
 * app.js — Demo repo entry point
 * Wires up all routes. This file is just for demo_repo completeness.
 */

const http = require('http');
const { handleCharge, handleStripeWebhook, getPaymentStatus } = require('./api/routes/payments');
const { loginUser, refreshToken, logoutUser } = require('./api/routes/auth');
const { handleNotification, handleSystemEvent } = require('./api/routes/webhooks');

const PORT = process.env.PORT || 3000;

// Minimal router — not a real framework, just for demo structure clarity
const routes = {
  'POST /auth/login': loginUser,
  'POST /auth/refresh': refreshToken,
  'POST /auth/logout': logoutUser,
  'POST /payments/charge': handleCharge,
  'POST /payments/webhook': handleStripeWebhook,
  'GET /payments/status': getPaymentStatus,
  'POST /webhooks/notify': handleNotification,
  'POST /webhooks/system': handleSystemEvent,
};

const server = http.createServer(async (req, res) => {
  const key = `${req.method} ${req.url.split('?')[0]}`;
  const handler = routes[key];

  if (!handler) {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not found' }));
    return;
  }

  let body = '';
  req.on('data', (chunk) => (body += chunk));
  req.on('end', async () => {
    try {
      req.body = body ? JSON.parse(body) : {};
      await handler(req, res);
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: err.message }));
    }
  });
});

if (require.main === module) {
  server.listen(PORT, () => console.log(`Demo app listening on :${PORT}`));
}

module.exports = server;

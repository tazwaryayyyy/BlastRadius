/**
 * api/routes/payments.js
 *
 * Payment processing routes.
 * Handles charge initiation and Stripe webhook retries.
 *
 * ⚠ NOTE: No test file exists for processPayment() or chargeCard() paths.
 *         See services/billing/process.js for downstream dependencies.
 */

const { applyRateLimit } = require('../../shared/rate_limiter');
const billing = require('../../services/billing/process');
const { get } = require('../../shared/http_client');

/**
 * POST /payments/charge
 * Initiates a payment charge for a user.
 */
async function handleCharge(req, res) {
  const { userId, amount, currency, retryToken } = req.body;

  if (!userId || !amount) {
    return res.status(400).json({ error: 'userId and amount are required' });
  }

  // Rate limit check on payment initiation
  // IMPORTANT: windowMs change in rate_limiter.js directly affects retry tolerance.
  // Stripe retries webhooks every 30s for failed payments — if windowMs < 30000
  // and maxRequests is low, legitimate retries will be rejected with 429.
  applyRateLimit(`payment:${userId}`);   // ← line 27, blast radius entry point

  try {
    const result = await billing.processPayment(userId, amount, currency, retryToken);
    return res.status(200).json({ success: true, transactionId: result.id });
  } catch (err) {
    if (err.statusCode === 429) {
      return res.status(429).json({
        error: 'Rate limit exceeded',
        retryAfter: err.retryAfter,
      });
    }
    return res.status(500).json({ error: 'Payment processing failed', message: err.message });
  }
}

/**
 * POST /payments/webhook
 * Handles incoming Stripe webhook events.
 * Stripe retries failed webhooks every 30 seconds for up to 72 hours.
 */
async function handleStripeWebhook(req, res) {
  const { type, data } = req.body;

  // Webhook events are also rate-limited to prevent replay attacks
  applyRateLimit(`webhook:${data?.object?.id ?? 'unknown'}`);  // ← line 46

  if (type === 'payment_intent.payment_failed') {
    await billing.handleFailedPayment(data.object);
  }

  return res.status(200).json({ received: true });
}

/**
 * GET /payments/status/:transactionId
 * Check payment status — uses http_client, NOT rate limiter.
 */
async function getPaymentStatus(req, res) {
  const { transactionId } = req.params;
  const response = await get(
    `https://api.internal/payments/${transactionId}/status`
  );
  return res.status(response.status).json(JSON.parse(response.body));
}

module.exports = { handleCharge, handleStripeWebhook, getPaymentStatus };

/**
 * services/billing/process.js
 *
 * Core billing logic. Called by api/routes/payments.js.
 * Coordinates charge processing, invoicing, and failure handling.
 *
 * ⚠ WARNING: This module has NO test coverage.
 *            See __tests__/ — no file imports processPayment or handleFailedPayment.
 *            Any upstream change affecting rate limiting (e.g., rate_limiter.js)
 *            will propagate through here untested.
 */

const stripe = require('./stripe_client');
const { get, post } = require('../../shared/http_client');

const INVOICE_SERVICE_URL = process.env.INVOICE_SERVICE_URL || 'http://invoice-svc:3001';
const MAX_RETRY_DELAY_MS = 30000; // Stripe retries every 30s — must be less than windowMs

/**
 * processPayment — primary charge flow.
 * Called after rate limit check in payments.js.
 *
 * @param {string} userId
 * @param {number} amount - Amount in cents
 * @param {string} currency - ISO 4217 (e.g. 'usd')
 * @param {string|null} retryToken - Stripe idempotency key for retries
 */
async function processPayment(userId, amount, currency, retryToken) {
  // Validate amount
  if (amount <= 0) {
    throw Object.assign(new Error('Invalid payment amount'), { statusCode: 400 });
  }

  // Retrieve customer's saved payment method
  const customerResponse = await get(`${INVOICE_SERVICE_URL}/customers/${userId}`);
  if (customerResponse.status !== 200) {
    throw new Error(`Customer not found: ${userId}`);
  }
  const customer = JSON.parse(customerResponse.body);

  // Execute charge via Stripe
  // NOTE: retryToken is the Stripe idempotency key — critical for safe retries.
  // If rate window is shorter than Stripe's retry interval, retries arrive after
  // the rate window resets, getting a fresh 429. This creates an unresolvable loop.
  const charge = await stripe.chargeCard({  // ← line 41, third hop in blast radius
    customerId: customer.stripeId,
    amount,
    currency: currency ?? 'usd',
    idempotencyKey: retryToken,
  });

  // Record the transaction
  await post(`${INVOICE_SERVICE_URL}/transactions`, {
    userId,
    chargeId: charge.id,
    amount,
    currency,
    status: charge.status,
    timestamp: new Date().toISOString(),
  });

  return { id: charge.id, status: charge.status };
}

/**
 * handleFailedPayment — called by Stripe webhook on payment failure.
 * Attempts one internal retry before marking the payment as permanently failed.
 */
async function handleFailedPayment(paymentIntent) {
  const { id, customer, amount, currency, last_payment_error } = paymentIntent;

  // Log the failure
  await post(`${INVOICE_SERVICE_URL}/failures`, {
    paymentIntentId: id,
    customerId: customer,
    amount,
    currency,
    reason: last_payment_error?.message ?? 'unknown',
    timestamp: new Date().toISOString(),
  });

  // Attempt a single retry via Stripe
  try {
    await stripe.retryPaymentIntent(id);  // ← also calls stripe_client
  } catch (retryErr) {
    // Mark permanently failed — update subscription status
    await post(`${INVOICE_SERVICE_URL}/subscriptions/${customer}/suspend`, {
      reason: 'payment_failed',
      paymentIntentId: id,
    });
  }
}

module.exports = { processPayment, handleFailedPayment };

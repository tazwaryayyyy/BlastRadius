/**
 * services/billing/stripe_client.js
 *
 * Stripe API wrapper — the terminal leaf of the CRITICAL blast radius chain.
 *
 * Call chain:
 *   rate_limiter.js (applyRateLimit)
 *     → payments.js (handleCharge)
 *       → billing/process.js (processPayment)
 *         → HERE (chargeCard)
 *
 * ⚠ No test file covers chargeCard(), retryPaymentIntent(), or any function
 *   in this file. All Stripe calls run completely untested.
 */

const STRIPE_SECRET = process.env.STRIPE_SECRET_KEY;
const STRIPE_API_URL = 'https://api.stripe.com/v1';

const { post } = require('../../shared/http_client');

/**
 * chargeCard — initiates a Stripe PaymentIntent.
 *
 * @param {object} params
 * @param {string} params.customerId - Stripe customer ID
 * @param {number} params.amount - Amount in smallest currency unit (cents)
 * @param {string} params.currency - ISO 4217 code
 * @param {string|null} params.idempotencyKey - Stripe idempotency key
 */
async function chargeCard({ customerId, amount, currency, idempotencyKey }) {
  const body = new URLSearchParams({
    amount: String(amount),
    currency,
    customer: customerId,
    'payment_method_types[]': 'card',
    confirm: 'true',
  });

  const headers = {
    Authorization: `Bearer ${STRIPE_SECRET}`,
    'Content-Type': 'application/x-www-form-urlencoded',
    ...(idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {}),
  };

  const response = await post(
    `${STRIPE_API_URL}/payment_intents`,
    body.toString(),
    { headers }
  );

  if (response.status !== 200) {
    const err = JSON.parse(response.body);
    throw Object.assign(
      new Error(err.error?.message ?? 'Stripe charge failed'),
      { statusCode: response.status, stripeCode: err.error?.code }
    );
  }

  return JSON.parse(response.body);
}

/**
 * retryPaymentIntent — confirms a previously created PaymentIntent.
 * Called by billing/process.js during failure handling.
 *
 * @param {string} paymentIntentId
 */
async function retryPaymentIntent(paymentIntentId) {
  const headers = {
    Authorization: `Bearer ${STRIPE_SECRET}`,
    'Content-Type': 'application/x-www-form-urlencoded',
  };

  const response = await post(
    `${STRIPE_API_URL}/payment_intents/${paymentIntentId}/confirm`,
    '',
    { headers }
  );

  if (response.status !== 200) {
    const err = JSON.parse(response.body);
    throw Object.assign(
      new Error(err.error?.message ?? 'Stripe retry failed'),
      { statusCode: response.status }
    );
  }

  return JSON.parse(response.body);
}

/**
 * getPaymentIntent — retrieve the current state of a PaymentIntent.
 */
async function getPaymentIntent(paymentIntentId) {
  const { get } = require('../../shared/http_client');
  const response = await get(
    `${STRIPE_API_URL}/payment_intents/${paymentIntentId}`,
    { headers: { Authorization: `Bearer ${STRIPE_SECRET}` } }
  );
  return JSON.parse(response.body);
}

module.exports = { chargeCard, retryPaymentIntent, getPaymentIntent };

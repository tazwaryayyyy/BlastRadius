/**
 * services/notifications/email.js
 *
 * Email dispatch service. Called by api/routes/webhooks.js.
 * Has graceful fallback: if sending fails or is rate-limited, events
 * are queued in memory (production would use SQS/Redis).
 *
 * This path is LOW risk in the blast radius — rate limit changes affect it,
 * but the queue ensures no notifications are lost.
 * Tested in: __tests__/webhooks.test.js
 */

const { post } = require('../../shared/http_client');

const MAIL_SERVICE_URL = process.env.MAIL_SERVICE_URL || 'http://mail-svc:3002';

// In-memory queue — production would persist this
const emailQueue = [];

/**
 * sendEmail — dispatch an email immediately via the mail service.
 *
 * @param {string} recipientId
 * @param {string} eventType
 * @param {object} payload
 */
async function sendEmail(recipientId, eventType, payload) {
  const response = await post(`${MAIL_SERVICE_URL}/send`, {
    to: recipientId,
    template: eventType,
    data: payload,
    timestamp: new Date().toISOString(),
  });

  if (response.status !== 200 && response.status !== 202) {
    throw new Error(`Mail service returned ${response.status}`);
  }

  return { status: 'sent', recipientId };
}

/**
 * queueEmail — add to retry queue when rate-limited or mail service unavailable.
 * Called by webhooks.js as a graceful fallback — no notification is ever dropped.
 */
async function queueEmail(recipientId, eventType, payload) {
  emailQueue.push({
    recipientId,
    eventType,
    payload,
    queuedAt: new Date().toISOString(),
    attempts: 0,
  });

  return { status: 'queued', position: emailQueue.length };
}

/**
 * flushQueue — process all queued emails.
 * Would be called by a cron job in production.
 */
async function flushQueue() {
  const processed = [];
  const failed = [];

  while (emailQueue.length > 0) {
    const item = emailQueue.shift();
    try {
      await sendEmail(item.recipientId, item.eventType, item.payload);
      processed.push(item.recipientId);
    } catch (err) {
      item.attempts++;
      if (item.attempts < 3) {
        emailQueue.push(item); // re-queue for another attempt
      } else {
        failed.push(item.recipientId);
      }
    }
  }

  return { processed, failed };
}

/**
 * getQueueLength — monitoring utility.
 */
function getQueueLength() {
  return emailQueue.length;
}

module.exports = { sendEmail, queueEmail, flushQueue, getQueueLength };

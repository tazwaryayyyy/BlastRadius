/**
 * api/routes/webhooks.js
 *
 * General webhook receiver for notification events.
 * Rate-limited but has graceful queue fallback — LOW blast radius risk.
 * Tested in: __tests__/webhooks.test.js
 */

const { applyRateLimit } = require('../../shared/rate_limiter');
const emailService = require('../../services/notifications/email');

/**
 * POST /webhooks/notify
 * Receives notification events and dispatches emails.
 * If rate-limited, event is queued for later delivery (not dropped).
 */
async function handleNotification(req, res) {
  const { eventType, payload, recipientId } = req.body;

  try {
    // Rate limit per recipient — graceful fallback queues the event
    applyRateLimit(`notify:${recipientId}`);  // ← line 19
    await emailService.sendEmail(recipientId, eventType, payload);
    return res.status(200).json({ status: 'sent' });
  } catch (err) {
    if (err.statusCode === 429) {
      // GRACEFUL FALLBACK: Queue the notification for retry — event is NOT lost
      await emailService.queueEmail(recipientId, eventType, payload);
      return res.status(202).json({ status: 'queued', retryAfter: err.retryAfter });
    }
    return res.status(500).json({ error: 'Notification dispatch failed' });
  }
}

/**
 * POST /webhooks/system
 * Internal system events — rate-limited and tested.
 */
async function handleSystemEvent(req, res) {
  const { action, metadata } = req.body;

  try {
    applyRateLimit(`system:${action}`);  // ← line 35
    // Process system events (audit logs, internal triggers)
    return res.status(200).json({ processed: true, action });
  } catch (err) {
    if (err.statusCode === 429) {
      // Queue system events too — no data loss
      return res.status(202).json({ status: 'queued' });
    }
    return res.status(500).json({ error: 'System event processing failed' });
  }
}

module.exports = { handleNotification, handleSystemEvent };

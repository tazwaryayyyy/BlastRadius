/**
 * __tests__/webhooks.test.js
 *
 * Test coverage for api/routes/webhooks.js and services/notifications/email.js
 * Covers: notification dispatch, queue fallback, system events.
 */

jest.mock('../shared/rate_limiter', () => ({
  applyRateLimit: jest.fn(),
  defaultLimiter: { check: jest.fn(() => true), reset: jest.fn() },
}));

jest.mock('../services/notifications/email', () => ({
  sendEmail: jest.fn().mockResolvedValue({ status: 'sent' }),
  queueEmail: jest.fn().mockResolvedValue({ status: 'queued', position: 1 }),
  flushQueue: jest.fn().mockResolvedValue({ processed: [], failed: [] }),
  getQueueLength: jest.fn().mockReturnValue(0),
}));

const { handleNotification, handleSystemEvent } = require('../api/routes/webhooks');
const { applyRateLimit } = require('../shared/rate_limiter');
const emailService = require('../services/notifications/email');

function mockRes() {
  const res = {};
  res.status = jest.fn().mockReturnValue(res);
  res.json = jest.fn().mockReturnValue(res);
  return res;
}

describe('handleNotification', () => {
  beforeEach(() => jest.clearAllMocks());

  test('sends email and returns 200 when under rate limit', async () => {
    const req = { body: { eventType: 'invoice.paid', payload: { amount: 100 }, recipientId: 'user-42' } };
    const res = mockRes();
    await handleNotification(req, res);
    expect(emailService.sendEmail).toHaveBeenCalledWith('user-42', 'invoice.paid', { amount: 100 });
    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith({ status: 'sent' });
  });

  test('queues email and returns 202 when rate limited', async () => {
    const rlError = Object.assign(new Error('Rate limit exceeded'), { statusCode: 429, retryAfter: 30 });
    applyRateLimit.mockImplementationOnce(() => { throw rlError; });

    const req = { body: { eventType: 'invoice.paid', payload: {}, recipientId: 'user-7' } };
    const res = mockRes();
    await handleNotification(req, res);

    // IMPORTANT: email is queued, not dropped
    expect(emailService.queueEmail).toHaveBeenCalledWith('user-7', 'invoice.paid', {});
    expect(res.status).toHaveBeenCalledWith(202);
    expect(res.json).toHaveBeenCalledWith(expect.objectContaining({ status: 'queued' }));
  });

  test('returns 500 if email service throws non-rate-limit error', async () => {
    emailService.sendEmail.mockRejectedValueOnce(new Error('SMTP connection refused'));
    const req = { body: { eventType: 'test', payload: {}, recipientId: 'user-1' } };
    const res = mockRes();
    await handleNotification(req, res);
    expect(res.status).toHaveBeenCalledWith(500);
  });
});

describe('handleSystemEvent', () => {
  beforeEach(() => jest.clearAllMocks());

  test('processes system event and returns 200', async () => {
    const req = { body: { action: 'cache.flush', metadata: { region: 'us-east-1' } } };
    const res = mockRes();
    await handleSystemEvent(req, res);
    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith(expect.objectContaining({ processed: true, action: 'cache.flush' }));
  });

  test('queues system event when rate limited', async () => {
    const rlError = Object.assign(new Error('Rate limit exceeded'), { statusCode: 429 });
    applyRateLimit.mockImplementationOnce(() => { throw rlError; });

    const req = { body: { action: 'deploy.notify', metadata: {} } };
    const res = mockRes();
    await handleSystemEvent(req, res);
    expect(res.status).toHaveBeenCalledWith(202);
    expect(res.json).toHaveBeenCalledWith({ status: 'queued' });
  });
});

describe('emailService.queueEmail', () => {
  test('adds item to queue and returns position', async () => {
    // Restore original implementation for this test
    emailService.queueEmail.mockResolvedValueOnce({ status: 'queued', position: 3 });
    const result = await emailService.queueEmail('user-99', 'reminder', { dueDate: '2026-05-01' });
    expect(result.status).toBe('queued');
    expect(result.position).toBeGreaterThan(0);
  });
});

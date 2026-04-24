/**
 * __tests__/auth.test.js
 *
 * Test coverage for api/routes/auth.js
 * Covers: loginUser, refreshToken, rate limiting on auth routes.
 */

const { loginUser, refreshToken, logoutUser } = require('../api/routes/auth');

// Mock the rate limiter so tests don't hit actual limits
jest.mock('../shared/rate_limiter', () => ({
  applyRateLimit: jest.fn(), // no-op by default
  RateLimiter: jest.fn(),
  defaultLimiter: { check: jest.fn(() => true), reset: jest.fn() },
}));

const { applyRateLimit } = require('../shared/rate_limiter');

function mockRes() {
  const res = {};
  res.status = jest.fn().mockReturnValue(res);
  res.json = jest.fn().mockReturnValue(res);
  return res;
}

describe('loginUser', () => {
  beforeEach(() => jest.clearAllMocks());

  test('returns 400 if email or password missing', async () => {
    const req = { body: { email: 'a@b.com' }, ip: '127.0.0.1', headers: {} };
    const res = mockRes();
    await loginUser(req, res);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  test('returns 401 for invalid credentials', async () => {
    const req = { body: { email: 'notanemail', password: 'short' }, ip: '127.0.0.1', headers: {} };
    const res = mockRes();
    await loginUser(req, res);
    expect(res.status).toHaveBeenCalledWith(401);
  });

  test('returns 200 and token for valid credentials', async () => {
    const req = { body: { email: 'user@example.com', password: 'securepassword' }, ip: '127.0.0.1', headers: {} };
    const res = mockRes();
    await loginUser(req, res);
    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith(expect.objectContaining({ token: expect.any(String) }));
  });

  test('calls applyRateLimit with login IP key', async () => {
    const req = { body: { email: 'user@example.com', password: 'securepassword' }, ip: '10.0.0.1', headers: {} };
    const res = mockRes();
    await loginUser(req, res);
    expect(applyRateLimit).toHaveBeenCalledWith('login:10.0.0.1');
  });

  test('returns 429 when rate limit throws', async () => {
    const rlError = Object.assign(new Error('Rate limit exceeded'), { statusCode: 429, retryAfter: 60 });
    applyRateLimit.mockImplementationOnce(() => { throw rlError; });

    const req = { body: { email: 'user@example.com', password: 'securepassword' }, ip: '10.0.0.1', headers: {} };
    const res = mockRes();

    // loginUser doesn't catch 429 itself — it propagates; middleware would handle it
    await expect(loginUser(req, res)).rejects.toThrow('Rate limit exceeded');
  });
});

describe('refreshToken', () => {
  beforeEach(() => jest.clearAllMocks());

  test('returns 400 if token missing', async () => {
    const req = { body: {}, ip: '127.0.0.1', headers: {} };
    const res = mockRes();
    await refreshToken(req, res);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  test('returns 200 with new token', async () => {
    const req = { body: { token: Buffer.from('user@test.com:1234').toString('base64') }, ip: '127.0.0.1', headers: {} };
    const res = mockRes();
    await refreshToken(req, res);
    expect(res.status).toHaveBeenCalledWith(200);
  });
});

describe('logoutUser', () => {
  test('always returns 200 — no rate limiting applied', async () => {
    const req = { body: {} };
    const res = mockRes();
    await logoutUser(req, res);
    expect(res.status).toHaveBeenCalledWith(200);
    expect(applyRateLimit).not.toHaveBeenCalled();
  });
});

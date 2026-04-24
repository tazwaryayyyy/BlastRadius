/**
 * api/routes/auth.js
 *
 * Authentication route handlers.
 * Rate limiting applied to login and token refresh to prevent brute force.
 * Tested in: __tests__/auth.test.js
 */

const { applyRateLimit } = require('../../shared/rate_limiter');

/**
 * POST /auth/login
 * Validates credentials and issues a session token.
 * Rate-limited per IP to prevent brute force.
 */
async function loginUser(req, res) {
  const { email, password } = req.body;
  const clientIp = req.ip ?? req.headers['x-forwarded-for'] ?? 'unknown';

  // Rate limit on IP — tested in auth.test.js
  applyRateLimit(`login:${clientIp}`);  // ← line 20

  if (!email || !password) {
    return res.status(400).json({ error: 'Email and password are required' });
  }

  try {
    // Stub auth logic — real implementation uses bcrypt + JWT
    const isValid = email.includes('@') && password.length >= 8;
    if (!isValid) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    const token = Buffer.from(`${email}:${Date.now()}`).toString('base64');
    return res.status(200).json({ token, expiresIn: 3600 });
  } catch (err) {
    return res.status(500).json({ error: 'Authentication service error' });
  }
}

/**
 * POST /auth/refresh
 * Refreshes a valid session token.
 * Also rate-limited — covered by auth.test.js.
 */
async function refreshToken(req, res) {
  const { token } = req.body;
  const clientIp = req.ip ?? req.headers['x-forwarded-for'] ?? 'unknown';

  applyRateLimit(`refresh:${clientIp}`);  // ← line 46

  if (!token) {
    return res.status(400).json({ error: 'Token is required' });
  }

  try {
    const decoded = Buffer.from(token, 'base64').toString('utf-8');
    const newToken = Buffer.from(`${decoded}:refreshed:${Date.now()}`).toString('base64');
    return res.status(200).json({ token: newToken, expiresIn: 3600 });
  } catch (err) {
    return res.status(401).json({ error: 'Invalid token' });
  }
}

/**
 * POST /auth/logout
 * Clears session — no rate limiting applied.
 */
async function logoutUser(req, res) {
  // No rate limit here — logout should always be permitted
  return res.status(200).json({ success: true });
}

module.exports = { loginUser, refreshToken, logoutUser };

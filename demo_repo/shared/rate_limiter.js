/**
 * shared/rate_limiter.js
 *
 * Sliding-window rate limiter used across API routes and services.
 * Imported by: payments, auth, webhooks.
 *
 * NOTE: Changes to windowMs or maxRequests affect ALL consumers.
 * Payment retry logic in services/billing is especially sensitive.
 */

const store = new Map();

class RateLimiter {
  constructor(options = {}) {
    this.windowMs = options.windowMs ?? 60000;      // 60 second window
    this.maxRequests = options.maxRequests ?? 100;  // 100 requests per window
    this.keyPrefix = options.keyPrefix ?? 'rl';
  }

  /**
   * Returns true if the key is within rate limit, false if exceeded.
   * @param {string} key - Identifier (userId, IP, etc.)
   */
  check(key) {
    const fullKey = `${this.keyPrefix}:${key}`;
    const now = Date.now();
    const entry = store.get(fullKey);

    if (!entry) {
      store.set(fullKey, { count: 1, resetAt: now + this.windowMs });
      return true;
    }

    if (now > entry.resetAt) {
      store.set(fullKey, { count: 1, resetAt: now + this.windowMs });
      return true;
    }

    if (entry.count >= this.maxRequests) {
      return false; // rate limited
    }

    entry.count++;
    return true;
  }

  reset(key) {
    store.delete(`${this.keyPrefix}:${key}`);
  }
}

// Default singleton used by most routes
const defaultLimiter = new RateLimiter();

/**
 * applyRateLimit — convenience export used directly in route handlers.
 * Throws a rate-limit error object if the key is exceeded.
 * @param {string} key
 */
function applyRateLimit(key) {
  const allowed = defaultLimiter.check(key);
  if (!allowed) {
    const error = new Error('Rate limit exceeded');
    error.statusCode = 429;
    error.retryAfter = Math.ceil(defaultLimiter.windowMs / 1000);
    throw error;
  }
}

module.exports = { RateLimiter, applyRateLimit, defaultLimiter };

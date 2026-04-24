/**
 * shared/http_client.js
 *
 * Generic HTTP utility for outbound requests.
 * Does NOT depend on rate_limiter — intentionally isolated.
 * Many services import this, but it is NOT in the blast radius of rate limit changes.
 */

const https = require('https');
const http = require('http');

const DEFAULT_TIMEOUT = 10000; // 10 seconds

/**
 * Simple promisified HTTP/S GET.
 * @param {string} url
 * @param {object} options
 * @returns {Promise<{status: number, body: string, headers: object}>}
 */
function get(url, options = {}) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const lib = parsed.protocol === 'https:' ? https : http;
    const timeout = options.timeout ?? DEFAULT_TIMEOUT;

    const req = lib.get(url, { headers: options.headers ?? {} }, (res) => {
      let body = '';
      res.on('data', (chunk) => (body += chunk));
      res.on('end', () =>
        resolve({ status: res.statusCode, body, headers: res.headers })
      );
    });

    req.setTimeout(timeout, () => {
      req.destroy();
      reject(new Error(`Request to ${url} timed out after ${timeout}ms`));
    });

    req.on('error', reject);
  });
}

/**
 * POST with JSON body.
 */
function post(url, body, options = {}) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const lib = parsed.protocol === 'https:' ? https : http;
    const payload = JSON.stringify(body);
    const timeout = options.timeout ?? DEFAULT_TIMEOUT;

    const reqOptions = {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload),
        ...(options.headers ?? {}),
      },
    };

    const req = lib.request(url, reqOptions, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () =>
        resolve({ status: res.statusCode, body: data, headers: res.headers })
      );
    });

    req.setTimeout(timeout, () => {
      req.destroy();
      reject(new Error(`POST to ${url} timed out`));
    });

    req.on('error', reject);
    req.write(payload);
    req.end();
  });
}

module.exports = { get, post };

# BlastRadius ⚡

> Pre-merge impact intelligence powered by IBM Bob.
> Know exactly what your PR will break — before it merges.

---

## What it does

BlastRadius gives every PR a **blast radius report**: a force-directed graph
showing every file your change can affect, ranked by risk level, with test
coverage gaps called out explicitly.

The core insight: existing tools (Copilot, Cursor, CodeRabbit) review *what
you wrote*. BlastRadius answers the question they can't: **what does merging
this affect downstream?**

---

## Why IBM Bob?

Traditional analyzers can be precise, but they take time to configure and usually end in reports nobody reads. BlastRadius turns the same question into a 30-second PR workflow engineers will actually use.

Bob holds the **entire repository in context simultaneously** so the output is fast, readable, and tied to the pull request instead of a separate analysis queue.

Specifically, Bob:
- Traces multi-hop call chains across the full codebase (not just direct imports)
- Flags lower-confidence paths explicitly when runtime wiring or dynamic dispatch requires manual verification
- Correlates changed symbols against the complete test suite to find coverage gaps
- Produces causal explanations — *why* a path is risky, not just *that* it exists

The value claim is speed, usability, and workflow integration: full-repo impact analysis in plain English, inside the PR, before merge.

---

## Stack

| Layer     | Tech                              |
|-----------|-----------------------------------|
| Backend   | FastAPI + Python 3.12             |
| AI        | IBM Bob API (+ OpenAI fallback)   |
| Frontend  | Vanilla JS + D3.js v7             |
| Deploy    | Docker Compose / Railway / Render |

---

## Project structure

```
blastradius/
├── backend/
│   ├── main.py           # FastAPI app — 3 endpoints
│   ├── bob_client.py     # IBM Bob API wrapper + fallback
│   ├── repo_loader.py    # Repo indexer + context prioritizer
│   ├── diff_parser.py    # Unified diff → changed files + symbols
│   ├── prompt_builder.py # Constructs the Bob prompt (most critical file)
│   ├── models.py         # Pydantic schemas
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── index.html        # Three-panel SPA shell
│   ├── app.js            # Main orchestrator
│   ├── graph.js          # D3 force-directed blast radius graph
│   ├── diff_viewer.js    # Syntax-highlighted diff display
│   └── styles.css        # Dark terminal aesthetic
├── demo_repo/            # Pre-seeded 15-file Node.js monorepo
│   ├── shared/
│   │   ├── rate_limiter.js   ← THE file changed in the demo PR
│   │   └── http_client.js    (safe — not in blast radius)
│   ├── api/routes/
│   │   ├── payments.js       CRITICAL chain (no tests)
│   │   ├── auth.js           MEDIUM chain (has tests)
│   │   └── webhooks.js       LOW chain (graceful fallback)
│   ├── services/
│   │   ├── billing/process.js      CRITICAL node 2
│   │   ├── billing/stripe_client.js CRITICAL leaf
│   │   └── notifications/email.js   LOW node (queues on failure)
│   └── __tests__/
│       ├── auth.test.js      covers auth chain
│       └── webhooks.test.js  covers webhook chain
├── demo_prs/
│   ├── pr_ratelimiter.diff   Main demo — tighten rate limit window
│   └── pr_auth.diff          Backup demo — token expiry change
├── docker-compose.yml
├── nginx.conf
└── .env.example
```

---

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/youruser/blastradius.git
cd blastradius
cp .env.example .env
# Edit .env — add your IBM Bob API key (or fallback LLM key)
```

### 2. Run with Docker Compose

```bash
docker-compose up --build
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs

### 3. Run locally (no Docker)

**Backend:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
# Any static server works — no build step needed
cd frontend
npx serve .          # or python -m http.server 3000
```

---

## API endpoints

| Method | Path            | Description                                      |
|--------|-----------------|--------------------------------------------------|
| POST   | `/api/analyze`  | Full analysis — returns `BlastRadiusReport` JSON |
| GET    | `/api/demo`     | One-click demo — pre-seeded rate limiter PR      |
| GET    | `/api/demo/diff`| Returns raw demo diff text for the diff viewer   |
| GET    | `/api/stream`   | SSE streaming version of analyze                 |
| GET    | `/api/health`   | Liveness probe                                   |

### POST `/api/analyze` — request body

```json
{
  "diff": "--- a/shared/rate_limiter.js\n+++ b/...",
  "repo_path": "demo_repo",
  "pr_title": "fix: tighten rate limit window",
  "stream": false
}
```

### Response — `BlastRadiusReport`

```json
{
  "changed_symbols": ["applyRateLimit"],
  "call_chains": [
    {
      "id": "chain_1",
      "risk": "CRITICAL",
      "path": ["shared/rate_limiter.js", "api/routes/payments.js", "services/billing/process.js", "services/billing/stripe_client.js"],
      "symbols": ["applyRateLimit", "handleCharge", "processPayment", "chargeCard"],
      "confidence": "HIGH",
      "confidence_reason": "Direct static import chain.",
      "has_tests": false,
      "test_files": [],
      "business_impact": "Payment retries will be blocked — halved rate window rejects Stripe retries. No test covers this path.",
      "explanation": "applyRateLimit() is called at payments.js:27 inside handleCharge(), which calls billing.processPayment(), which calls stripe.chargeCard(). No file in __tests__/ imports processPayment."
    },
    {
      "id": "chain_2",
      "risk": "MEDIUM",
      "path": ["shared/rate_limiter.js", "api/routes/auth.js"],
      "symbols": ["applyRateLimit", "loginUser"],
      "confidence": "HIGH",
      "confidence_reason": "Direct static import chain.",
      "has_tests": true,
      "test_files": ["__tests__/auth.test.js"],
      "business_impact": "Login rate limiting tightened. Auth tests cover this path — lower risk.",
      "explanation": "applyRateLimit() called at auth.js:20 inside loginUser(). __tests__/auth.test.js imports and tests loginUser with a mocked rate limiter."
    },
    {
      "id": "chain_3",
      "risk": "LOW",
      "path": ["shared/rate_limiter.js", "api/routes/webhooks.js", "services/notifications/email.js"],
      "symbols": ["applyRateLimit", "handleNotification", "sendEmail"],
      "confidence": "MEDIUM",
      "confidence_reason": "Inferred via fallback handling path — verify manually.",
      "has_tests": true,
      "test_files": ["__tests__/webhooks.test.js"],
      "business_impact": "Notification rate limiting tightened. Graceful queue fallback prevents data loss.",
      "explanation": "webhooks.js catches 429 errors and calls emailService.queueEmail() — no notifications are lost. Covered by webhooks.test.js."
    }
  ],
  "safe_paths": ["api/routes/payments.js:getPaymentStatus uses http_client directly — not affected"],
  "risk_summary": { "CRITICAL": 1, "HIGH": 0, "MEDIUM": 1, "LOW": 1 },
  "merge_recommendation": "BLOCK MERGE — CRITICAL untested billing path exposed. Add tests for processPayment() and handleCharge() before merging.",
  "suggested_actions": [
    "Add test for processPayment() covering rate limit window < 30s",
    "Add retry backoff in billing/process.js before calling chargeCard()",
    "Verify Stripe webhook retry interval against new windowMs value"
  ],
  "pr_title": "fix: tighten rate limit window for security compliance"
}
```

---

## The demo script (2 minutes)

1. **Open the app** — three panels visible, graph is idle.
2. **Press "Run Demo"** — diff loads in the left panel. Bob starts streaming.
3. **Graph renders** — three chains radiate from the blue changed node.
4. **Point out the chains**:
   - Green node (LOW) — webhooks, safe, has tests
   - Yellow node (MEDIUM) — auth, partial risk, has tests
   - **Red pulsing node (CRITICAL) — billing, no tests**
5. **Click the red node** — right panel shows the full chain, confidence label, and no-test warning.
6. **Read the header** — the risk score spikes and the verdict blocks merge.
7. **Use the checklist** — suggested actions tell the reviewer what to do before merge.
8. **Punchline**: "We're not chasing rare disasters. We're catching the hidden breakages that cause 2am pages every week."

---

## Configuration

| Variable              | Required | Description                              |
|-----------------------|----------|------------------------------------------|
| `BOB_API_URL`         | Yes*     | IBM Bob endpoint base URL                |
| `BOB_API_KEY`         | Yes*     | IBM Bob API key                          |
| `BOB_MODEL`           | No       | Model name (default: `bob-v1`)           |
| `BOB_FALLBACK_URL`    | Yes*     | Fallback LLM base URL (OpenAI-compatible)|
| `BOB_FALLBACK_API_KEY`| Yes*     | Fallback API key                         |
| `BOB_FALLBACK_MODEL`  | No       | Fallback model (default: `gpt-4o`)       |

*At least one of (Bob or fallback) must be configured.

---

## BlastRadius vs existing tools

| Capability | BlastRadius | CodeRabbit | GitHub Copilot | Cursor |
|---|---|---|---|---|
| Reviews code you wrote | ✓ | ✓ | ✓ | ✓ |
| Traces downstream impact | ✓ | ✗ | ✗ | ✗ |
| Multi-hop call graph tracing | ✓ | ✗ | ✗ | ✗ |
| Test coverage gap detection | ✓ | Partial | ✗ | ✗ |
| Merge verdict with reasoning | ✓ | ✗ | ✗ | ✗ |
| Full repo context simultaneously | ✓ (via Bob) | ✗ | ✗ | Partial |
| Works on any diff / any language | ✓ | ✓ | ✓ | ✓ |
| Visual blast radius graph | ✓ | ✗ | ✗ | ✗ |

The key distinction: every tool in this table tells you if your code is *good*. BlastRadius tells you if merging it is *safe*, fast enough to use on every PR, and clear enough that people will act on it.

---

## Troubleshooting

**Bob API returns 401**
Check `BOB_API_KEY` in `.env`. Make sure there are no trailing spaces or quotes around the key.

**Graph renders but shows no nodes**
Bob returned an empty `call_chains` array. This means the diff symbols weren't found in the repo files. Verify `repo_path` points to the correct directory and the diff file paths match the repo structure.

**SSE stream hangs / never completes**
Nginx is likely buffering the stream. Confirm `nginx.conf` has `proxy_buffering off` and `proxy_read_timeout 180s`. If running locally without nginx, the stream connects directly to FastAPI and this isn't an issue.

**`uvicorn: command not found` after install**
The venv wasn't activated. Run `source backend/.venv/bin/activate` (Linux/Mac) or `backend\.venv\Scripts\activate` (Windows) before running uvicorn.

**Docker Compose: `port 8000 already in use`**
Another process is on port 8000. Either stop it (`lsof -ti:8000 | xargs kill`) or change the port in `docker-compose.yml` and `frontend/app.js` (`window.API_BASE`).

**Bob fallback not triggering**
The fallback only activates if `BOB_API_URL` is set but unreachable, or returns a non-2xx error. If `BOB_API_URL` is empty, the fallback is used directly. Check logs for `"Bob primary failed"` to confirm fallback activation.

**Demo diff loads but analysis never finishes**
Bob's response is taking longer than `REQUEST_TIMEOUT` (120s). Increase it in `bob_client.py` or check Bob API status.

---

## IBM Bob Hackathon — May 15–17, 2026

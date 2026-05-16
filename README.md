# BlastRadius ⚡

> The average PR sits in review for 2.5 days.  
> Half that time is engineers asking "what does this break?"  
> **BlastRadius answers in 30 seconds.**

Paste a GitHub PR URL. A structured two-stage reasoning pipeline powered by IBM Bob traces every call chain across the repository, identifies uncovered critical paths, generates missing test stubs, and issues a BLOCK or PROCEED verdict — before you merge.

[![Live Demo](https://img.shields.io/badge/Live_Demo-blastradius.vercel.app-0070f3?style=for-the-badge&logo=vercel&logoColor=white)](https://blastradius-rosy.vercel.app)
[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-enabled-2088FF?style=for-the-badge&logo=github-actions&logoColor=white)](https://github.com/tazwaryayyyy/BlastRadius/blob/main/.github/workflows/blastradius.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)
[![IBM Bob](https://img.shields.io/badge/Powered_by-IBM_Bob-054ADA?style=for-the-badge&logo=ibm&logoColor=white)](https://www.ibm.com/products/watsonx-ai)

---

## Live Examples

Pre-generated reports on real open-source PRs. No API call. No cold start.

| Project | PR | Verdict | Report |
|---|---|---|---|
| Express.js | [#5223](https://github.com/expressjs/express/pull/5223) | 🚨 BLOCK | [View Report](https://blastradius-rosy.vercel.app/?report=10c53b83-92b1-4bf4-9cdf-6a597f024a83) |
| Express.js | [#7226](https://github.com/expressjs/express/pull/7226) | 🚨 BLOCK | [View Report](https://blastradius-rosy.vercel.app/?report=a0a1cde6-48d3-443f-adbe-616e4a5255f9) |
| FastAPI | [#9563](https://github.com/fastapi/fastapi/pull/9563) | ✅ PROCEED | [View Report](https://blastradius-rosy.vercel.app/?report=571fc88f-f552-44ba-a013-f982b394925b) |

---

## What It Does

A developer opens a PR. Nobody knows what it affects downstream. BlastRadius fetches the diff directly from GitHub, runs two specialized agents in sequence — TraceAgent maps every call chain across the repository, RemediationAgent writes runnable test stubs for every uncovered critical path — and renders the full impact graph in under 30 seconds. Every report gets a shareable URL.

---

## What Makes It Different

Most AI code review tools read what you wrote. BlastRadius asks a different question: **what does this change break downstream?**

It traces the transitive call chain from every changed symbol — `applyRateLimit` → `handleCharge` → `processPayment` → `chargeCard` — identifies which paths have no test coverage, generates the missing test stubs, and issues a binary BLOCK or PROCEED verdict with a shareable URL. That full-chain blast radius analysis with a machine-actionable verdict is what existing tools don't do.

| | GitHub PR Review | CodeRabbit | **BlastRadius** |
|---|---|---|---|
| Reviews what you wrote | ✓ | ✓ | ✓ |
| **Traces transitive downstream call chains** | **✗** | **✗** | **✓** |
| **BLOCK / PROCEED verdict** | **✗** | **✗** | **✓** |
| Identifies untested impact paths | ✗ | partial | ✓ |
| Auto-generates missing test stubs | ✗ | ✗ | ✓ |
| Works on any public GitHub PR URL | ✗ | ✓ | ✓ |
| Posts impact report as PR comment | ✗ | ✓ | ✓ |
| **Shareable report URL** | **✗** | **✗** | **✓** |

---

## Architecture

```
PR URL → GitHub Loader → [Stage 1: TraceAgent] ──────────────→ [Stage 2: RemediationAgent]
                               ↓ Bob: multi-hop chain-of-thought       ↓ Bob: stub generation
                         call chains + risk + AST badges         test stubs + fix summaries
                               └──────────────────────────────── Report + Share Link
```

BlastRadius runs a **structured two-stage reasoning pipeline** powered entirely by IBM Bob:

- **Stage 1 — TraceAgent:** Bob performs structured chain-of-thought reasoning across the repository context, tracing which files call which functions, how deep the impact propagates, and which paths have no test coverage. Each call chain gets an AST-verified confidence badge (VERIFIED / INFERRED). Bob emits live stage events (`tracing_callers → building_chains → checking_coverage`) streamed to the UI so you see the reasoning unfold in real time.

- **Stage 2 — RemediationAgent:** Bob's TraceAgent output feeds directly into a second focused Bob call. For every CRITICAL uncovered path, Bob generates a complete, runnable test stub with a one-line fix summary. On a BLOCK verdict, a cost estimate (based on DORA 2023 medians) surfaces the business risk.

Both stages use `BOB_PROJECT_ID`-scoped watsonx.ai inference. Context is prioritised (changed files first, then their importers) so Bob reasons over the most relevant code even for large repos.

> **How repo context works:** BlastRadius uses Bob's inference API — it does not rely on any native "repo awareness" feature in watsonx.ai. Before each Bob call, files are priority-ranked (changed files → their importers → test files → everything else), trimmed to fit the model's context budget, and injected into a structured prompt. For large repos where not all files fit, the UI shows exactly how many files Bob saw — e.g. *"Bob analyzed 47 of 312 repo files (priority-ranked)"* — so the scope of the analysis is always transparent.

---

## GitHub Actions Integration

Add BlastRadius as an automatic PR comment on every pull request:

**1. Add the secret to your repo:**

```
Settings → Secrets → Actions → New secret
Name: BLASTRADIUS_API_URL
Value: https://blastradius-api-dz0l.onrender.com
```

**2. Copy the workflow:**

```bash
curl -o .github/workflows/blastradius.yml \
  https://raw.githubusercontent.com/tazwaryayyyy/BlastRadius/main/.github/workflows/blastradius.yml
```

Every PR now gets an automatic impact report comment with risk table, remediation suggestions, and a link to the full graph.

---

## Running Locally

```bash
git clone https://github.com/tazwaryayyyy/BlastRadius
cd BlastRadius/backend
cp .env.example .env        # fill in BOB_API_KEY and BOB_API_URL
pip install -r requirements.txt
uvicorn main:app --reload
```

Open `frontend/index.html` in your browser or:

```bash
cd frontend && npx serve .
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BOB_API_KEY` | Yes | IBM Cloud API key for watsonx.ai IAM authentication |
| `BOB_API_URL` | Yes | watsonx.ai inference endpoint (e.g. https://jp-tok.ml.cloud.ibm.com/ml/v1/text/chat?version=2024-05-13) |
| `BOB_MODEL` | Yes | Model ID (e.g. meta-llama/llama-3-3-70b-instruct) |
| `BOB_PROJECT_ID` | Yes | watsonx.ai project ID |
| `BOB_FALLBACK_API_KEY` | No | Groq API key — used if Bob is unavailable |
| `BOB_FALLBACK_URL` | No | Groq OpenAI-compatible base URL |
| `BOB_FALLBACK_MODEL` | No | Groq model (e.g. llama-3.3-70b-versatile) |
| `GITHUB_TOKEN` | No | Raises GitHub rate limit from 60 to 5,000 req/hr |
| `CORS_ORIGINS` | Production | Comma-separated allowed frontend URLs |
| `STATIC_SAVE_SECRET` | Production | Secret for pinning reports to disk |
| `BLASTRADIUS_API_URL` | GitHub Actions | Your deployed backend URL |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, httpx |
| Primary AI | IBM Bob / watsonx.ai (meta-llama/llama-3-3-70b-instruct) |
| Fallback AI | Groq (llama-3.3-70b-versatile) |
| Frontend | Vanilla JS, D3.js v7 |
| GitHub Integration | REST API, Trees API, GitHub Actions bot |
| Deployment | Render (backend), Vercel (frontend) |

---

## Real-World Case Study

**Express.js [PR #5570](https://github.com/expressjs/express/pull/5570)** — a change to `router/layer.js` that modified how path parameters are decoded. The function `Layer.prototype.match` was changed to call `decodeURIComponent` without a try/catch guard.

BlastRadius traced the call chain:

```
router/layer.js → router/index.js → application.js → http.IncomingMessage
```

Verdict: **🚨 BLOCK** — `Layer.prototype.match` is called on every incoming request. No test covered the `decodeURIComponent` throw path. Three weeks after the PR merged, a `%` in a URL path caused unhandled exceptions in production for several downstream users. A `try/catch` fix was shipped in a follow-up.

BlastRadius would have flagged this before merge — the uncovered CRITICAL path and missing test stub were exactly the failure that shipped. [View the pre-generated report →](https://blastradius-rosy.vercel.app/?report=4ceba495-0714-44ca-8e8a-14e8fcb17995)

---

## IBM Bob Session Log

BlastRadius was built using IBM Bob (watsonx.ai) across 5 documented 
sessions covering prompt engineering, TypeScript symbol detection, 
AST verification, test generation, and GitHub Actions hardening.

[View full Bob usage log →](BOB_USAGE.md)

---

## License

MIT

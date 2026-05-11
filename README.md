# BlastRadius ⚡

> The average PR sits in review for 2.5 days.  
> Half that time is engineers asking "what does this break?"  
> **BlastRadius answers in 30 seconds.**

Paste a GitHub PR URL. Two autonomous AI agents trace every call chain across the repository, identify uncovered critical paths, generate missing test stubs, and issue a BLOCK or PROCEED verdict — before you merge.

[![Live Demo](https://img.shields.io/badge/Live_Demo-blastradius.vercel.app-0070f3?style=for-the-badge&logo=vercel&logoColor=white)](https://blastradius-rosy.vercel.app)
[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-enabled-2088FF?style=for-the-badge&logo=github-actions&logoColor=white)](https://github.com/tazwaryayyyy/BlastRadius/blob/main/.github/workflows/blastradius.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)
[![IBM Bob](https://img.shields.io/badge/Powered_by-IBM_Bob-054ADA?style=for-the-badge&logo=ibm&logoColor=white)](https://www.ibm.com/products/watsonx-ai)

---

## Live Examples

Pre-generated reports on real open-source PRs. No API call. No cold start.

| Project | PR | Verdict | Report |
|---|---|---|---|
| Express.js | [#5570](https://github.com/expressjs/express/pull/5570) | 🚨 BLOCK | [View Report](https://blastradius-rosy.vercel.app/?report=4ceba495-0714-44ca-8e8a-14e8fcb17995) |
| Express.js | [#7226](https://github.com/expressjs/express/pull/7226) | 🚨 BLOCK | [View Report](https://blastradius-rosy.vercel.app/?report=22c20473-9443-4bfd-b4b1-90e2c6162389) |
| FastAPI | [#9563](https://github.com/fastapi/fastapi/pull/9563) | ✅ PROCEED | [View Report](https://blastradius-rosy.vercel.app/?report=5e6bab13-b61f-417a-8288-a9ce280ea59c) |

---

## What It Does

A developer opens a PR. Nobody knows what it affects downstream. BlastRadius fetches the diff directly from GitHub, runs two specialized agents in sequence — TraceAgent maps every call chain across the repository, RemediationAgent writes runnable test stubs for every uncovered critical path — and renders the full impact graph in under 30 seconds. Every report gets a shareable URL.

---

## How It Compares

| | GitHub PR Review | CodeRabbit | **BlastRadius** |
|---|---|---|---|
| Reviews what you wrote | ✓ | ✓ | ✓ |
| Traces downstream call chains | ✗ | ✗ | ✓ |
| Identifies untested impact paths | ✗ | partial | ✓ |
| Auto-generates missing test stubs | ✗ | ✗ | ✓ |
| Works on any public GitHub PR URL | ✗ | ✓ | ✓ |
| Posts impact report as PR comment | ✗ | ✓ | ✓ |
| Shareable report URL | ✗ | ✗ | ✓ |

---

## Architecture

```
PR URL → GitHub Loader → [TraceAgent] → [RemediationAgent] → Report + Share Link
                               ↓                 ↓
                        Blast Radius Graph   Test Stubs + Fix Summary
```

TraceAgent (IBM Bob) performs multi-hop call chain reasoning across the repository context — tracing which files call which functions, how deep the impact propagates, and which paths have no test coverage. Its output feeds directly into RemediationAgent (IBM Bob), which generates complete, runnable pytest stubs for every uncovered critical path. Both agents stream real stage events to the frontend over SSE so the analysis feels live, not opaque.

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

## IBM Bob Session Log

BlastRadius was built using IBM Bob (watsonx.ai) across 5 documented 
sessions covering prompt engineering, TypeScript symbol detection, 
AST verification, test generation, and GitHub Actions hardening.

[View full Bob usage log →](BOB_USAGE.md)

---

## License

MIT

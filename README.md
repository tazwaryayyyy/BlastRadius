# BlastRadius ⚡

> The average PR sits in review for 2.5 days.  
> Half that time is engineers asking "what does this break?"  
> **BlastRadius answers in 30 seconds.**

Paste a GitHub PR URL. Two autonomous AI agents trace every call chain across the repository, identify uncovered critical paths, generate missing test stubs, and issue a BLOCK or PROCEED verdict — before you merge.

[![Live Demo](https://img.shields.io/badge/Live_Demo-blastradius.vercel.app-00ff88?style=flat)](https://blastradius-rosy.vercel.app)
[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-bot_ready-2088FF?logo=github-actions&logoColor=white)](https://github.com/tazwaryayyyy/BlastRadius/blob/main/.github/workflows/blastradius.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

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

TraceAgent (Gemini Pro) performs multi-hop call chain reasoning across the repository context — tracing which files call which functions, how deep the impact propagates, and which paths have no test coverage. Its output feeds directly into RemediationAgent (Gemini Flash), which generates complete, runnable pytest stubs for every uncovered critical path. Both agents stream real stage events to the frontend over SSE so the analysis feels live, not opaque.

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
cp .env.example .env        # fill in GEMINI_API_KEY
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
| `GEMINI_API_KEY` | Yes | Gemini API key from [aistudio.google.com](https://aistudio.google.com) |
| `GITHUB_TOKEN` | No | Raises GitHub rate limit from 60 to 5,000 req/hr |
| `CORS_ORIGINS` | Production | Comma-separated allowed frontend URLs |
| `STATIC_SAVE_SECRET` | Production | Secret for pinning reports to disk |
| `BLASTRADIUS_API_URL` | GitHub Actions | Your deployed backend URL |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, httpx |
| AI Agents | Gemini Pro (TraceAgent), Gemini Flash (RemediationAgent) |
| Frontend | Vanilla JS, D3.js v7 |
| GitHub Integration | REST API, Trees API, GitHub Actions bot |
| Deployment | Render (backend), Vercel (frontend) |

---

## License

MIT

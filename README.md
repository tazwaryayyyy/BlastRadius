# BlastRadius ⚡

> The average PR sits in review for 2.5 days.  
> Half that time is engineers asking "what does this break?"  
> **BlastRadius answers in 30 seconds.**

Paste a GitHub PR URL. Get the full call-chain impact report — powered by two autonomous AI agents — before you merge.

[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-bot_ready-2088FF?logo=github-actions&logoColor=white)](https://github.com/tazwaryayyyy/BlastRadius/blob/main/.github/workflows/blastradius.yml)
[![Live Demo](https://img.shields.io/badge/Live_Demo-blastradius--rosy.vercel.app-black?logo=vercel)](https://blastradius-rosy.vercel.app/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## Live Examples

Three pre-generated reports on real open-source PRs — no API call, no cold start, just the graph.

| Project | PR | Blast Radius |
|---|---|---|
| Express.js | [#5570](https://github.com/expressjs/express/pull/5570) | [View Report](https://blastradius-rosy.vercel.app/?report=PLACEHOLDER_UUID_1) |
| Axios | [#4124](https://github.com/axios/axios/pull/4124) | [View Report](https://blastradius-rosy.vercel.app/?report=PLACEHOLDER_UUID_2) |
| FastAPI | [#9563](https://github.com/fastapi/fastapi/pull/9563) | [View Report](https://blastradius-rosy.vercel.app/?report=PLACEHOLDER_UUID_3) |

> ⚠ Report UUIDs above are placeholders. Run the tool on each PR and replace them with the `?report=` links it generates.

---

## What It Does

A developer pastes a GitHub PR URL into the input field. BlastRadius fetches the diff and a prioritized slice of the repository context, then runs two agents in sequence: TraceAgent (Gemini Pro) walks every call chain touched by the changed symbols — across multiple hops, through dynamic dispatch boundaries, and into test files — and returns a risk-coded chain graph with a BLOCK or ALLOW verdict. RemediationAgent (Gemini Flash) then takes every CRITICAL chain that has no test coverage and writes a runnable test stub for it, so the reviewer has something concrete to copy rather than a vague warning. Both agents stream real-time stage events to the frontend over SSE, the D3 graph renders as results arrive, and a shareable UUID link is generated so the report can be dropped directly into a PR comment.

---

## How It Compares

| | GitHub PR Review | CodeRabbit | **BlastRadius** |
|---|---|---|---|
| Reviews what you wrote | ✓ | ✓ | ✓ |
| Traces downstream call chains | ✗ | ✗ | ✓ |
| Identifies untested impact paths | ✗ | partial | ✓ |
| Auto-generates missing test stubs | ✗ | ✗ | ✓ |
| Works on any public GitHub PR | ✗ | ✓ | ✓ |
| Posts to PR as a bot comment | ✗ | ✓ | ✓ |

The distinction: every tool in this table tells you if your code is *good*. BlastRadius tells you if merging it is *safe*.

---

## Architecture

TraceAgent uses Gemini Pro's extended reasoning window to walk multi-hop call chains across the full repository context, returning a structured risk report with per-chain confidence ratings and test coverage flags. RemediationAgent then takes only the CRITICAL, untested chains from that report and calls Gemini Flash to produce a runnable pytest stub and a one-line fix summary for each — fast enough to complete before a reviewer finishes reading the diff. Both agents emit named stage events over a shared asyncio queue, which the SSE endpoint forwards to the frontend in real time. Completed reports are stored with a UUID and served from `/api/report/{id}` so the link is shareable indefinitely.

```
PR URL → GitHub Loader → [TraceAgent] → [RemediationAgent] → Report + Share Link
                               ↓                   ↓
                        Blast Radius Graph    Test Stubs + Fix Summary
```

---

## GitHub Actions Integration

Add one secret to your repo, copy the workflow file — the bot posts a risk table and test stubs as a PR comment on every push.

**Setup:**

```
Settings → Secrets → Actions → New secret
Name:  BLASTRADIUS_API_URL
Value: https://blastradius-api-dz0l.onrender.com
```

Then copy [`.github/workflows/blastradius.yml`](https://github.com/tazwaryayyyy/BlastRadius/blob/main/.github/workflows/blastradius.yml) into your own repo. No other configuration needed.

<!-- Add screenshot of bot PR comment here -->

The bot comment includes: a risk-level table for every impacted call chain, auto-generated test stubs for any uncovered CRITICAL paths, and a link to the full interactive graph.

---

## Running Locally

```bash
git clone https://github.com/tazwaryayyyy/BlastRadius.git
cd blastradius/backend
cp .env.example .env        # fill in GEMINI_API_KEY
pip install -r requirements.txt
uvicorn main:app --reload
```

```bash
# Frontend — open in browser directly or serve it:
cd frontend && npx serve .
```

API docs available at `http://localhost:8000/docs`.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Gemini API key from [aistudio.google.com](https://aistudio.google.com) |
| `GITHUB_TOKEN` | No | Raises GitHub API rate limit from 60 to 5,000 req/hr |
| `CORS_ORIGINS` | Production | Comma-separated list of allowed frontend origins |
| `BLASTRADIUS_API_URL` | GitHub Actions | Your deployed backend URL, set as a repo secret |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, httpx |
| AI Agents | Gemini 2.0 Pro (TraceAgent), Gemini 2.0 Flash (RemediationAgent) |
| Frontend | Vanilla JS, D3.js v7 |
| GitHub Integration | REST API, Trees API, GitHub Actions |
| Deployment | Render (backend), Vercel (frontend) |

---

## License

MIT

"""
main.py
BlastRadius — FastAPI backend

Endpoints:
  POST /api/analyze       Full analysis, returns BlastRadiusReport
  GET  /api/demo          One-click demo using pre-seeded PR + repo
  GET  /api/stream        SSE streaming version of /analyze
  GET  /api/health        Liveness probe
"""

import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from models import AnalyzeRequest, BlastRadiusReport, RiskSummary
from repo_loader import load_repo
from diff_parser import parse_diff
from prompt_builder import build_system_prompt, build_user_prompt
from bob_client import analyze as bob_analyze, analyze_stream

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger("blastradius")

# ── App ───────────────────────────────────────────────────────────
app = FastAPI(
    title="BlastRadius",
    description="Pre-merge impact prediction powered by IBM Bob",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files if present
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# Absolute base path for demo assets
BASE_DIR = Path(__file__).parent.parent


# ── Helpers ───────────────────────────────────────────────────────

def _parse_report(raw_json: str, pr_title: str | None) -> BlastRadiusReport:
    """Parse Bob's JSON output into a validated BlastRadiusReport."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Bob returned invalid JSON: {exc}")

    # Normalise risk_summary — Bob may return lowercase keys
    rs = data.get("risk_summary", {})
    normalised_rs = {k.upper(): v for k, v in rs.items()}
    data["risk_summary"] = RiskSummary(**{
        lvl: normalised_rs.get(lvl, 0)
        for lvl in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
    })

    data["pr_title"] = pr_title

    try:
        return BlastRadiusReport(**data)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Report validation failed: {exc}")


async def _run_analysis(req: AnalyzeRequest) -> BlastRadiusReport:
    """Core pipeline: load repo → parse diff → build prompt → call Bob → parse result."""
    # Resolve repo path relative to project root
    repo_path = str(BASE_DIR / req.repo_path) if not os.path.isabs(req.repo_path) else req.repo_path

    try:
        all_files = load_repo(repo_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if not all_files:
        raise HTTPException(status_code=400, detail="No readable files found in repo_path")

    diff_result = parse_diff(req.diff)
    if not diff_result.changed_files:
        raise HTTPException(status_code=400, detail="Could not extract changed files from diff")

    system  = build_system_prompt()
    user    = build_user_prompt(all_files, diff_result)

    logger.info(
        f"Analyzing PR: {req.pr_title!r} | "
        f"changed={diff_result.changed_files} | "
        f"symbols={diff_result.symbols} | "
        f"repo_files={len(all_files)}"
    )

    raw_json = await bob_analyze(system, user)
    return _parse_report(raw_json, req.pr_title)


# ── Routes ────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "blastradius"}


@app.post("/api/analyze", response_model=BlastRadiusReport)
async def analyze(req: AnalyzeRequest) -> BlastRadiusReport:
    """Full analysis endpoint. Returns BlastRadiusReport JSON."""
    return await _run_analysis(req)


@app.get("/api/demo", response_model=BlastRadiusReport)
async def demo() -> BlastRadiusReport:
    """
    One-click demo endpoint.
    Loads the pre-seeded rate_limiter PR diff against the demo_repo.
    No request body needed — ideal for the hackathon presentation.
    """
    diff_path = BASE_DIR / "demo_prs" / "pr_ratelimiter.diff"
    if not diff_path.exists():
        raise HTTPException(status_code=404, detail="Demo diff not found")

    diff_text = diff_path.read_text()
    req = AnalyzeRequest(
        diff=diff_text,
        repo_path="demo_repo",
        pr_title="fix: tighten rate limit window for security compliance",
    )
    return await _run_analysis(req)


@app.get("/api/stream")
async def stream_analysis(
    diff: str = Query(..., description="Unified diff text"),
    repo_path: str = Query("demo_repo"),
    pr_title: str = Query(None),
):
    """
    SSE streaming endpoint.
    Returns Bob's raw reasoning token-by-token, then a final [DONE] event
    with the complete BlastRadiusReport JSON.

    Frontend listens with EventSource or fetch + ReadableStream.
    """
    repo_full = str(BASE_DIR / repo_path) if not os.path.isabs(repo_path) else repo_path

    try:
        all_files = load_repo(repo_full)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    diff_result = parse_diff(diff)
    system = build_system_prompt()
    user   = build_user_prompt(all_files, diff_result)

    accumulated = []

    async def event_gen():
        try:
            async for chunk in analyze_stream(system, user):
                accumulated.append(chunk)
                # Stream raw tokens to frontend
                yield f"data: {json.dumps({'type': 'token', 'content': chunk, 'token_count': len(''.join(accumulated))})}\n\n"

            # Parse the accumulated JSON and send the final structured report
            raw_json = "".join(accumulated)
            report = _parse_report(raw_json, pr_title)
            yield f"data: {json.dumps({'type': 'done', 'report': report.model_dump()})}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@app.get("/api/demo/diff")
async def demo_diff() -> dict:
    """Return the raw demo diff text (used by frontend diff viewer)."""
    diff_path = BASE_DIR / "demo_prs" / "pr_ratelimiter.diff"
    if not diff_path.exists():
        raise HTTPException(status_code=404, detail="Demo diff not found")
    return {"diff": diff_path.read_text(), "pr_title": "fix: tighten rate limit window for security compliance"}

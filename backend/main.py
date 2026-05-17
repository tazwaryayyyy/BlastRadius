"""
main.py
BlastRadius — FastAPI backend (IBM Bob two-stage reasoning pipeline)

Endpoints:
  GET  /api/health            Liveness probe (also / and /health)
  GET  /api/warmup            Pre-loads demo repo into memory
  POST /api/analyze           Full analysis, returns BlastRadiusReport
  GET  /api/demo              One-click demo analysis against demo_repo
  GET  /api/demo/diff         Returns raw demo diff text for the frontend viewer
  POST /api/stream/session    Creates a single-use session token from a diff payload
  GET  /api/stream            SSE stream of stage events + final report (session_id)
  POST /api/analyze/github    SSE stream triggered by a GitHub PR URL
  GET  /api/report/{id}       Retrieve a previously stored report by UUID
"""

import asyncio
import json
import logging
import os
import time
import uuid
from collections import OrderedDict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from config import CONTEXT_BUDGET_CHARS, CONTEXT_BUDGET_MIN
from diff_parser import parse_diff
from models import AnalyzeRequest, BlastRadiusReport, GithubAnalyzeRequest, RiskSummary
from prompt_builder import build_system_prompt, build_user_prompt
from remediation_agent import RemediationAgent
from report_store import get_report, save_static_report, store_report
from repo_loader import get_context_bundle, load_repo
from trace_agent import TraceAgent

logging.basicConfig(level=logging.INFO,
                    format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger("blastradius")

# ── App ───────────────────────────────────────────────────────────
app = FastAPI(
    title="BlastRadius",
    description="Pre-merge impact prediction powered by IBM Bob (watsonx.ai)",
    version="2.0.0",
)

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    allow_credentials=False,
)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

HERE = Path(__file__).resolve().parent
BASE_DIR = HERE if (HERE / "demo_prs").exists() and (HERE /
                                                     "demo_repo").exists() else HERE.parent
ALLOWED_REPO_ROOT = BASE_DIR.resolve()

_session_store: OrderedDict[str, dict] = OrderedDict()
_SESSION_LIMIT = 500


# ── Security ──────────────────────────────────────────────────────

def safe_repo_path(raw: str) -> Path:
    candidate = (ALLOWED_REPO_ROOT / raw).resolve()
    if not str(candidate).startswith(str(ALLOWED_REPO_ROOT)):
        raise HTTPException(status_code=400, detail="Invalid repository path.")
    if not candidate.exists():
        raise HTTPException(
            status_code=404, detail="Repository path not found.")
    return candidate


# ── Report normalisation ──────────────────────────────────────────

def _parse_report(raw_json: str, pr_title: str | None) -> BlastRadiusReport:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        logger.error("LLM response JSON parse failure: %s", exc)
        raise HTTPException(
            502, "Analysis service returned an unreadable response.") from exc

    rs = data.get("risk_summary", {})
    data["risk_summary"] = RiskSummary(**{
        lvl: {k.upper(): v for k, v in rs.items()}.get(lvl, 0)
        for lvl in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
    })

    for chain in data.get("call_chains", []):
        if isinstance(chain, dict) and "confidence" in chain:
            chain["confidence"] = str(chain["confidence"]).upper()

    if not isinstance(data.get("suggested_actions"), list):
        data["suggested_actions"] = []

    data["pr_title"] = pr_title

    try:
        return BlastRadiusReport(**data)
    except Exception as exc:
        logger.error("Report schema validation failure: %s", exc)
        raise HTTPException(
            502, "Analysis service returned an unreadable response.") from exc


def _stage(name: str) -> str:
    return f"data: {json.dumps({'type': 'stage', 'stage': name})}\n\n"


def _sse_response(gen) -> StreamingResponse:
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Shared async pipeline generator ──────────────────────────────

async def _analysis_event_gen(
    all_files: dict[str, str],
    diff_text: str,
    pr_title: str | None,
    image_b64: str | None = None,
    mime_type: str | None = None,
    context_stats=None,
):
    q: asyncio.Queue[str] = asyncio.Queue()

    try:
        yield _stage("parsing_diff")
        diff_result = parse_diff(diff_text)
        if not diff_result.changed_files:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Could not extract changed files from diff.'})}\n\n"
            return

        # Compute context stats for local-repo flows (demo / stream) that don't supply them
        if context_stats is None:
            _, context_stats = get_context_bundle(
                all_files, diff_result.changed_files, diff_result.symbols
            )

        trace = TraceAgent(all_files)
        trace_task = asyncio.create_task(
            trace.run(diff_result, image_b64=image_b64, mime_type=mime_type,
                      stage_callback=lambda s: q.put_nowait(_stage(s)))
        )
        while not trace_task.done():
            while not q.empty():
                yield q.get_nowait()
            await asyncio.sleep(0.05)
        while not q.empty():
            yield q.get_nowait()
        report_dict = await trace_task

        # Emit real token count from Bob response after TraceAgent
        trace_tokens = report_dict.pop("_trace_tokens", 0)
        yield f"data: {json.dumps({'type': 'token', 'token_count': trace_tokens, 'stage': 'trace'})}\n\n"

        rem_task = asyncio.create_task(
            RemediationAgent().run(report_dict, all_files,
                                   stage_callback=lambda s: q.put_nowait(_stage(s)))
        )
        while not rem_task.done():
            while not q.empty():
                yield q.get_nowait()
            await asyncio.sleep(0.05)
        while not q.empty():
            yield q.get_nowait()
        report_dict = await rem_task

        # Emit real token count from Bob response after RemediationAgent
        rem_tokens = report_dict.pop("_remediation_tokens", 0)
        yield f"data: {json.dumps({'type': 'token', 'token_count': rem_tokens, 'stage': 'remediation'})}\n\n"

        # Promote _inference_backend to a proper report field before serialisation
        report_dict["inference_backend"] = report_dict.pop(
            "_inference_backend", "bob")

        if context_stats:
            report_dict["context_stats"] = context_stats.model_dump()

        report = _parse_report(json.dumps(report_dict), pr_title)
        report_id = await store_report(report)

        yield f"data: {json.dumps({'type': 'result', 'report': report.model_dump(), 'report_id': report_id})}\n\n"
        yield 'data: {"type": "done"}\n\n'

    except HTTPException as exc:
        logger.error("Stream pipeline error: %s", exc.detail)
        yield f"data: {json.dumps({'type': 'error', 'message': exc.detail})}\n\n"
    except (ValueError, RuntimeError) as exc:
        logger.error("Stream agent error: %s", exc)
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
    except json.JSONDecodeError as exc:
        logger.error("Stream JSON parse error: %s", exc)
        yield f"data: {json.dumps({'type': 'error', 'message': 'Bob returned an unreadable response — please retry.'})}\n\n"


# ── Non-streaming pipeline (used by /api/analyze and /api/demo) ───

async def _run_analysis(req: AnalyzeRequest) -> BlastRadiusReport:
    repo_path = safe_repo_path(req.repo_path)

    try:
        all_files = load_repo(str(repo_path))
    except FileNotFoundError as exc:
        raise HTTPException(404, "Repository path not found.") from exc

    if not all_files:
        raise HTTPException(400, "No readable files found in repo_path")

    diff_result = parse_diff(req.diff)
    if not diff_result.changed_files:
        raise HTTPException(400, "Could not extract changed files from diff")

    logger.info("Analyzing PR: %r | changed=%s | repo_files=%d",
                req.pr_title, diff_result.changed_files, len(all_files))

    try:
        trace = TraceAgent(all_files)
        report_dict = await trace.run(diff_result)
        report_dict = await RemediationAgent().run(report_dict, all_files)
        report_dict.pop("_trace_tokens", None)
        report_dict.pop("_remediation_tokens", None)
        report_dict["inference_backend"] = report_dict.pop(
            "_inference_backend", "bob")
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("Analysis service error: %s", exc)
        raise HTTPException(
            503, "Analysis service is not configured.") from exc
    except RuntimeError as exc:
        logger.error("Analysis failed: %s", exc)
        raise HTTPException(502, "Analysis service is unavailable.") from exc

    return _parse_report(json.dumps(report_dict), req.pr_title)


# ── Routes ────────────────────────────────────────────────────────

@app.get("/api/health")
@app.get("/health")
@app.get("/")
async def health():
    return {"status": "ok", "service": "blastradius"}


@app.get("/api/warmup")
async def warmup():
    try:
        load_repo(str(safe_repo_path("demo_repo")))
    except HTTPException:
        pass
    return {"status": "warm"}


@app.post("/api/analyze", response_model=BlastRadiusReport)
async def analyze(req: AnalyzeRequest) -> BlastRadiusReport:
    return await _run_analysis(req)


@app.get("/api/demo", response_model=BlastRadiusReport)
async def demo() -> BlastRadiusReport:
    diff_path = BASE_DIR / "demo_prs" / "pr_ratelimiter.diff"
    if not diff_path.exists():
        raise HTTPException(404, "Demo diff not found")
    req = AnalyzeRequest(
        diff=diff_path.read_text(encoding="utf-8"),
        repo_path="demo_repo",
        pr_title="fix: tighten rate limit window for security compliance",
    )
    return await _run_analysis(req)


@app.get("/api/demo/diff")
async def demo_diff() -> dict:
    diff_path = BASE_DIR / "demo_prs" / "pr_ratelimiter.diff"
    if not diff_path.exists():
        raise HTTPException(404, "Demo diff not found")
    return {
        "diff": diff_path.read_text(encoding="utf-8"),
        "pr_title": "fix: tighten rate limit window for security compliance",
    }


@app.post("/api/stream/session")
async def create_stream_session(req: AnalyzeRequest) -> dict:
    safe_path = safe_repo_path(req.repo_path)
    session_id = str(uuid.uuid4())
    _session_store[session_id] = {
        "diff": req.diff,
        "repo_path": str(safe_path),
        "pr_title": req.pr_title,
        "created_at": time.monotonic(),
    }
    if len(_session_store) > _SESSION_LIMIT:
        _session_store.popitem(last=False)
    return {"session_id": session_id}


@app.get("/api/stream")
async def stream_analysis(session_id: str = Query(...)):
    session = _session_store.pop(session_id, None)
    if session is None:
        raise HTTPException(404, "Session not found or already used.")

    diff_text = session["diff"]
    repo_path = session["repo_path"]
    pr_title = session.get("pr_title")
    image_b64 = session.get("image_b64")
    mime_type = session.get("mime_type")

    async def event_gen():
        yield _stage("loading_repo")
        try:
            all_files = load_repo(repo_path)
        except FileNotFoundError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Repository path not found.'})}\n\n"
            return
        if not all_files:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No readable files found.'})}\n\n"
            return
        async for chunk in _analysis_event_gen(all_files, diff_text, pr_title, image_b64, mime_type):
            yield chunk

    return _sse_response(event_gen())


@app.post("/api/analyze/github")
async def analyze_github_pr(body: GithubAnalyzeRequest):
    import httpx
    from github_loader import fetch_pr_diff, fetch_repo_context, parse_pr_url

    try:
        owner, repo, pr_number = await parse_pr_url(body.pr_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    gh_headers = {"Accept": "application/vnd.github+json"}
    gh_token = os.getenv("GITHUB_TOKEN", "")
    if gh_token:
        gh_headers["Authorization"] = f"Bearer {gh_token}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            pr_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
                headers=gh_headers,
            )
            if pr_resp.status_code == 404:
                raise HTTPException(404, "PR not found.")
            if pr_resp.status_code == 403:
                reset = pr_resp.headers.get("X-RateLimit-Reset", "unknown")
                raise HTTPException(
                    403, f"GitHub rate limit exceeded. Resets at {reset}. Set GITHUB_TOKEN for higher limits.")
            if pr_resp.status_code != 200:
                raise HTTPException(
                    502, f"GitHub API returned {pr_resp.status_code}.")
            pr_data = pr_resp.json()

        ref = pr_data["base"]["sha"]
        diff_text = await fetch_pr_diff(owner, repo, pr_number)
        diff_result = parse_diff(diff_text)
        files, stats = await fetch_repo_context(
            owner, repo, ref, priority_files=diff_result.changed_files
        )
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(504, "GitHub API timed out. Try again.")
    except Exception as exc:
        logger.error("GitHub fetch failed: %s", exc)
        raise HTTPException(502, f"Failed to fetch PR from GitHub: {exc}")

    pr_title = pr_data.get("title")

    async def event_gen():
        yield _stage("loading_repo")
        if not files:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No readable files found in repo.'})}\n\n"
            return
        async for chunk in _analysis_event_gen(
            files, diff_text, pr_title, body.image_b64, body.mime_type, stats
        ):
            yield chunk

    return _sse_response(event_gen())


@app.get("/api/report/{report_id}")
async def get_report_endpoint(report_id: str):
    report = await get_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found or expired.")
    return report


STATIC_SAVE_SECRET = os.getenv("STATIC_SAVE_SECRET", "")


@app.post("/api/report/{report_id}/pin")
async def pin_report(report_id: str, secret: str = Query(...)):
    if not STATIC_SAVE_SECRET or secret != STATIC_SAVE_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden.")
    report = await get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found.")
    await save_static_report(report_id, report)
    return {"pinned": report_id}

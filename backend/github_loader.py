import asyncio
import logging
import os
import re

import httpx
from fastapi import HTTPException

from config import CONTEXT_BUDGET_CHARS
from models import ContextStats
from repo_loader import SKIP_DIRS, SKIP_EXTENSIONS, prioritize_files

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


def _gh_headers() -> dict[str, str]:
    h: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


async def parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    m = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url.strip())
    if not m:
        raise ValueError(
            f"Invalid GitHub PR URL: {pr_url!r}. "
            "Expected https://github.com/owner/repo/pull/N"
        )
    return m.group(1), m.group(2), int(m.group(3))


async def fetch_pr_diff(owner: str, repo: str, pr_number: int) -> str:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            url,
            headers={**_gh_headers(), "Accept": "application/vnd.github.v3.diff"},
        )
    if resp.status_code == 404:
        raise HTTPException(
            404, f"PR #{pr_number} not found in {owner}/{repo}.")
    if resp.status_code == 403:
        reset = resp.headers.get("X-RateLimit-Reset", "unknown")
        raise HTTPException(
            403, f"GitHub rate limit exceeded. Resets at {reset}.")
    resp.raise_for_status()
    return resp.text


async def fetch_repo_context(
    owner: str,
    repo: str,
    ref: str,
    priority_files: list[str],
    budget_chars: int = CONTEXT_BUDGET_CHARS,
) -> tuple[dict[str, str], ContextStats]:
    tree_url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{ref}?recursive=1"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(tree_url, headers=_gh_headers())
        if resp.status_code == 403:
            reset = resp.headers.get("X-RateLimit-Reset", "unknown")
            raise HTTPException(
                403, f"GitHub rate limit exceeded fetching repo tree. Resets at {reset}.")
        if resp.status_code == 404:
            raise HTTPException(404, "Repository or ref not found on GitHub.")
        if resp.status_code != 200:
            raise HTTPException(
                502, f"GitHub API returned {resp.status_code} fetching repo tree.")
        tree_data = resp.json()

    all_paths = [
        item["path"]
        for item in tree_data.get("tree", [])
        if item["type"] == "blob"
        and not any(item["path"].endswith(ext) for ext in SKIP_EXTENSIONS)
        and not any(seg in item["path"].split("/") for seg in SKIP_DIRS)
    ]
    total_files = len(all_paths)

    # Score files by relevance without content — prioritize_files accepts empty strings
    ordered = prioritize_files({p: "" for p in all_paths}, priority_files, [])
    top_paths = ordered[:100]

    sem = asyncio.Semaphore(20)

    async def fetch_one(path: str) -> tuple[str, str]:
        async with sem:
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
            try:
                async with httpx.AsyncClient(timeout=10.0) as c:
                    r = await c.get(raw_url)
                    return path, r.text if r.status_code == 200 else ""
            except httpx.HTTPError:
                return path, ""

    results = await asyncio.gather(*[fetch_one(p) for p in top_paths])

    files: dict[str, str] = {}
    total_chars = 0
    for path, content in results:
        if not content.strip():
            continue
        if total_chars + len(content) > budget_chars:
            break
        files[path] = content
        total_chars += len(content)

    stats = ContextStats(
        files_in_repo=total_files,
        files_sent_to_model=len(files),
        chars_sent=total_chars,
        budget_used_pct=round(total_chars / max(budget_chars, 1) * 100, 1),
    )
    return files, stats

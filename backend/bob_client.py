"""
bob_client.py
Async HTTP client for the IBM Bob API.

- Primary: IBM Bob endpoint (BOB_API_URL)
- Fallback: Any OpenAI-compatible endpoint (BOB_FALLBACK_URL)
  The same prompt works across models — just swap base URL + model name.
- Streaming: bob_stream() yields raw text chunks via SSE.
"""

import os
import json
import asyncio
import logging
import httpx
from typing import AsyncIterator

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────
BOB_URL = os.getenv("BOB_API_URL", "").rstrip("/")
BOB_KEY = os.getenv("BOB_API_KEY", "")
BOB_MODEL = os.getenv("BOB_MODEL", "bob-v1")

FALLBACK_URL = os.getenv("BOB_FALLBACK_URL", "").rstrip("/")
FALLBACK_KEY = os.getenv("BOB_FALLBACK_API_KEY", "")
FALLBACK_MODEL = os.getenv("BOB_FALLBACK_MODEL", "gpt-4o")

REQUEST_TIMEOUT = 120.0
MAX_RETRIES = 2


def _is_413(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 413


def _compact_user_prompt(user: str, max_chars: int = 12_000) -> str:
    """Reduce prompt size when provider rejects payload as too large."""
    compacted = user

    files_header = "## REPOSITORY FILES"
    diff_header = "\n\n## PR DIFF"
    start = compacted.find(files_header)
    end = compacted.find(diff_header)
    if start != -1 and end != -1 and end > start:
        compacted = (
            compacted[:start]
            + "## REPOSITORY FILES\n\n[omitted to fit provider payload limits]"
            + compacted[end:]
        )

    if len(compacted) <= max_chars:
        return compacted

    # Keep both prefix and suffix to preserve task instructions and diff context.
    keep_head = max_chars // 2
    keep_tail = max_chars - keep_head
    return compacted[:keep_head] + "\n\n[truncated]\n\n" + compacted[-keep_tail:]


async def _analyze_with_model(
    client: httpx.AsyncClient,
    system: str,
    user: str,
    url: str,
    key: str,
    model: str,
) -> str:
    payload = _build_payload(system, user, model)
    try:
        response = await _post(client, url, key, payload)
        raw = _extract_text(response.json())
        return _clean_json(raw)
    except httpx.HTTPStatusError as exc:
        if not _is_413(exc):
            raise

        compact_user = _compact_user_prompt(user)
        if compact_user == user:
            raise

        logger.warning(
            "Payload too large (413). Retrying with compact prompt...")
        response = await _post(client, url, key, _build_payload(system, compact_user, model))
        raw = _extract_text(response.json())
        return _clean_json(raw)


def _build_payload(system: str, user: str, model: str, stream: bool = False) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens": 4096,
        "temperature": 0,   # deterministic — analysis, not creativity
        "stream": stream,
    }


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


async def _post(
    client: httpx.AsyncClient,
    url: str,
    key: str,
    payload: dict,
) -> httpx.Response:
    """POST with retry on 429 / 503."""
    endpoint = f"{url}/chat/completions"
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.post(
                endpoint,
                json=payload,
                headers=_headers(key),
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code in (429, 503) and attempt < MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning(
                    "Rate limited (%s), retrying in %ss...",
                    response.status_code,
                    wait,
                )
                await asyncio.sleep(wait)
                continue
            response.raise_for_status()
            return response
        except httpx.TimeoutException:
            if attempt < MAX_RETRIES:
                continue
            raise

    raise RuntimeError("All retries exhausted")


def _extract_text(data: dict) -> str:
    """Extract content string from OpenAI-compatible response."""
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise ValueError(f"Unexpected API response shape: {data}") from exc


def _clean_json(raw: str) -> str:
    """Strip accidental markdown fences around JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    return raw.strip()


# ── Public API ────────────────────────────────────────────────────

async def analyze(system: str, user: str) -> str:
    """
    Send prompt to Bob (or fallback) and return the raw JSON string.
    Raises ValueError if neither endpoint is configured.
    """
    if not BOB_URL and not FALLBACK_URL:
        raise ValueError(
            "Neither BOB_API_URL nor BOB_FALLBACK_URL is set. "
            "Copy .env.example to .env and fill in your credentials."
        )

    async with httpx.AsyncClient() as client:
        # Try primary Bob endpoint
        if BOB_URL:
            try:
                logger.info("Calling IBM Bob API…")
                return await _analyze_with_model(
                    client,
                    system,
                    user,
                    BOB_URL,
                    BOB_KEY,
                    BOB_MODEL,
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Bob primary failed: %s. Trying fallback...", exc)

        # Fallback to OpenAI-compatible endpoint
        if FALLBACK_URL:
            logger.info("Calling fallback (%s)...", FALLBACK_MODEL)
            return await _analyze_with_model(
                client,
                system,
                user,
                FALLBACK_URL,
                FALLBACK_KEY,
                FALLBACK_MODEL,
            )

    raise RuntimeError("All API endpoints failed")


async def analyze_stream(system: str, user: str) -> AsyncIterator[str]:
    """
    Stream Bob's response token-by-token.
    Yields text chunks as they arrive (SSE data payloads).
    Falls back to non-streaming + fake token delay if streaming unavailable.
    """
    if not BOB_URL and not FALLBACK_URL:
        yield json.dumps({"error": "No API endpoint configured"})
        return

    url = BOB_URL if BOB_URL else FALLBACK_URL
    key = BOB_KEY if BOB_URL else FALLBACK_KEY
    model = BOB_MODEL if BOB_URL else FALLBACK_MODEL

    payload = _build_payload(system, user, model, stream=True)
    endpoint = f"{url}/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            async with client.stream(
                "POST", endpoint, json=payload, headers=_headers(key)
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload_str = line[6:].strip()
                    if payload_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload_str)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError):
                        continue
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Graceful degradation: fall back to non-streaming
        logger.warning(
            "Streaming failed: %s. Falling back to batch mode...", exc)
        result = await analyze(system, user)
        # Simulate streaming with small chunks
        chunk_size = 12
        for i in range(0, len(result), chunk_size):
            yield result[i: i + chunk_size]
            await asyncio.sleep(0.02)

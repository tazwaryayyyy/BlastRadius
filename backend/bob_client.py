"""
bob_client.py
IBM Bob API client for BlastRadius.

IBM Bob is OpenAI-compatible (same request/response shape as OpenAI chat completions).
Falls back to a secondary OpenAI-compatible endpoint if Bob is unavailable.
"""

import asyncio
import json
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

# ── Primary: IBM Bob ───────────────────────────────────────────────
BOB_API_KEY = os.getenv("BOB_API_KEY", "")
BOB_API_URL = os.getenv(
    "BOB_API_URL",
    "https://jp-tok.ml.cloud.ibm.com/ml/v1/text/chat?version=2024-05-13",
)
BOB_MODEL = os.getenv("BOB_MODEL", "meta-llama/llama-3-3-70b-instruct")
BOB_PROJECT_ID = os.getenv("BOB_PROJECT_ID", "")
# ── Fallback: any OpenAI-compatible endpoint ───────────────────────
BOB_FALLBACK_API_KEY = os.getenv("BOB_FALLBACK_API_KEY", "")
BOB_FALLBACK_URL = os.getenv("BOB_FALLBACK_URL", "")
BOB_FALLBACK_MODEL = os.getenv("BOB_FALLBACK_MODEL", "gpt-4o")

_TIMEOUT = 120.0
_MAX_RETRIES = 3

# ── IAM token cache ───────────────────────────────────
_iam_token: str = ""
_iam_token_expiry: float = 0.0


async def _get_iam_token() -> str:
    """Exchange BOB_API_KEY for an IBM Cloud IAM bearer token.

    The token is cached in memory and refreshed when within 60 seconds of expiry.
    """
    global _iam_token, _iam_token_expiry
    if _iam_token and time.monotonic() < _iam_token_expiry - 60:
        return _iam_token
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://iam.cloud.ibm.com/identity/token",
            data={
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": BOB_API_KEY,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        _iam_token = data["access_token"]
        _iam_token_expiry = time.monotonic() + data["expires_in"]
        return _iam_token


def _clean_json(raw: str) -> str:
    """Strip ```json fences and surrounding whitespace from a raw LLM response."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines and lines[-1]
                        == "```" else lines[1:])
    return raw.strip()


async def call_bob(
    prompt: str,
    temperature: float = 0.0,
    max_tokens: int = 8192,
) -> str:
    """Call the IBM Bob API (OpenAI-compatible chat completions).

    Retries up to _MAX_RETRIES times on 429. Falls back to the secondary
    endpoint on any other non-200 response. Logs all errors — never leaks
    raw HTTP errors to the caller.
    """
    if not BOB_API_KEY:
        raise ValueError("BOB_API_KEY is not set.")

    token = await _get_iam_token()
    url = BOB_API_URL
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model_id": BOB_MODEL,
        "project_id": BOB_PROJECT_ID,
        "messages": [{"role": "user", "content": prompt}],
        "parameters": {
            "temperature": temperature,
            "max_new_tokens": max_tokens,
        },
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await client.post(url, headers=headers, json=payload)

                if resp.status_code == 429:
                    wait = min(2 ** attempt, 8)
                    logger.warning(
                        "Bob 429 rate limit — retrying in %ss (attempt %d)",
                        wait, attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code != 200:
                    logger.error(
                        "Bob HTTP %s — trying fallback", resp.status_code)
                    return await _call_fallback(prompt, temperature, max_tokens)

                resp.raise_for_status()
                data = resp.json()
                try:
                    if "results" in data:
                        return data["results"][0]["generated_text"]
                    elif "choices" in data:
                        return data["choices"][0]["message"]["content"]
                    else:
                        raise ValueError(
                            f"Unrecognized response shape: {list(data.keys())}")
                except (KeyError, IndexError) as exc:
                    logger.error("Unexpected Bob response shape: %s", data)
                    raise ValueError("Bob call failed") from exc

            except httpx.HTTPStatusError as exc:
                logger.error("Bob HTTP %s: %s", exc.response.status_code, exc)
                return await _call_fallback(prompt, temperature, max_tokens)

            except httpx.TimeoutException:
                if attempt < _MAX_RETRIES - 1:
                    continue
                raise ValueError("Bob call timed out")

    raise ValueError("Bob call failed — all retries exhausted")


async def _call_fallback(
    prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """Secondary OpenAI-compatible endpoint, used when Bob is unavailable."""
    if not BOB_FALLBACK_API_KEY or not BOB_FALLBACK_URL:
        raise ValueError("Analysis service unavailable.")

    logger.warning(
        "\u26a0\ufe0f  IBM Bob unavailable — analysis running on FALLBACK endpoint (%s). "
        "Set BOB_API_KEY and BOB_API_URL to use Bob.",
        BOB_FALLBACK_URL,
    )

    url = f"{BOB_FALLBACK_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {BOB_FALLBACK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": BOB_FALLBACK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.error("Fallback also failed: %s", exc)
            raise ValueError("Analysis service unavailable.") from exc


async def call_bob_multimodal(
    text_prompt: str,
    image_b64: str,
    mime_type: str,
) -> str:
    """IBM Bob does not support multimodal natively.

    Strips the image, logs a warning, and forwards the text prompt only with
    a note that the diagram could not be processed.
    """
    logger.warning(
        "call_bob_multimodal: IBM Bob does not support multimodal input — "
        "image will be stripped and text-only prompt forwarded."
    )
    augmented = (
        text_prompt
        + "\n\nNote: An architecture diagram was provided but could not be processed."
    )
    return await call_bob(augmented)

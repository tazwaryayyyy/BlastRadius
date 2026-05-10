import asyncio
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

GEMINI_PRO = "gemini-2.0-flash-thinking-exp"
GEMINI_FLASH = "gemini-2.0-flash"

_TIMEOUT = 120.0
_MAX_RETRIES = 3


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines and lines[-1]
                        == "```" else lines[1:])
    return raw.strip()


async def call_gemini(
    prompt: str,
    model: str = GEMINI_PRO,
    temperature: float = 0.0,
    max_tokens: int = 8192,
) -> str:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set.")

    url = f"{GEMINI_API_BASE}/models/{model}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 429:
                    wait = min(2 ** attempt, 8)
                    logger.warning(
                        "Gemini 429 rate limit — retrying in %ss (attempt %d)", wait, attempt + 1)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                try:
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError) as exc:
                    logger.error("Unexpected Gemini response shape: %s", data)
                    raise ValueError("Gemini call failed") from exc
            except httpx.HTTPStatusError as exc:
                logger.error("Gemini HTTP %s: %s",
                             exc.response.status_code, exc)
                raise ValueError("Gemini call failed") from exc
            except httpx.TimeoutException:
                if attempt < _MAX_RETRIES - 1:
                    continue
                raise ValueError("Gemini call timed out")

    raise ValueError("Gemini call failed — all retries exhausted")


async def call_gemini_multimodal(
    text_prompt: str,
    image_b64: str,
    mime_type: str,
    model: str = GEMINI_FLASH,
) -> str:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set.")

    url = f"{GEMINI_API_BASE}/models/{model}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [
                {"text": text_prompt},
                {"inline_data": {"mime_type": mime_type, "data": image_b64}},
            ]
        }],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8192},
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            logger.error("Unexpected Gemini multimodal response: %s",
                         resp.json() if resp else {})
            raise ValueError("Gemini multimodal call failed") from exc
        except httpx.HTTPStatusError as exc:
            logger.error("Gemini multimodal HTTP %s: %s",
                         exc.response.status_code, exc)
            raise ValueError("Gemini multimodal call failed") from exc

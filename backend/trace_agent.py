import json
import logging
from typing import Callable

from gemini_client import GEMINI_PRO, _clean_json, call_gemini, call_gemini_multimodal
from models import DiffResult
from prompt_builder import build_system_prompt, build_user_prompt

logger = logging.getLogger(__name__)


class TraceAgent:
    """
    Traces call chains across a repository to map PR blast radius.
    Uses Gemini Pro for multi-hop reasoning over repo context.
    """

    def __init__(self, repo_context: dict[str, str]):
        self.repo_context = repo_context

    async def run(
        self,
        diff: DiffResult,
        image_b64: str | None = None,
        mime_type: str | None = None,
        stage_callback: Callable[[str], None] | None = None,
    ) -> dict:
        def _cb(name: str) -> None:
            if stage_callback:
                stage_callback(name)

        _cb("tracing_callers")
        system = build_system_prompt()
        user = build_user_prompt(self.repo_context, diff)
        # Gemini uses a single content field; system instruction is prepended to ensure
        # it is always present regardless of which Gemini variant handles the request.
        full_prompt = f"{system}\n\n{user}"

        _cb("building_chains")
        if image_b64 and mime_type:
            raw = await call_gemini_multimodal(full_prompt, image_b64, mime_type)
        else:
            raw = await call_gemini(full_prompt, model=GEMINI_PRO)

        _cb("checking_coverage")
        return json.loads(_clean_json(raw))

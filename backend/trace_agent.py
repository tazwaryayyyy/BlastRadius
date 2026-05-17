import json
import logging
import os
from typing import Callable

from ast_verifier import verify_call
from bob_client import call_bob, call_bob_multimodal, _clean_json
from models import DiffResult
from prompt_builder import build_system_prompt, build_user_prompt

logger = logging.getLogger(__name__)


class TraceAgent:
    """
    Traces call chains across a repository to map PR blast radius.
    Uses IBM Bob (watsonx.ai) for multi-hop reasoning over repo context.
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
        # Bob expects a single content field; system instruction is prepended to ensure
        # it is always present regardless of which model variant handles the request.
        full_prompt = f"{system}\n\n{user}"

        _cb("building_chains")
        if image_b64 and mime_type:
            raw, token_count, backend = await call_bob_multimodal(full_prompt, image_b64, mime_type)
        else:
            raw, token_count, backend = await call_bob(full_prompt)

        _cb("checking_coverage")
        cleaned = _clean_json(raw)
        if not cleaned:
            raise ValueError("Bob returned an empty response — please retry.")
        report_dict = json.loads(cleaned)
        report_dict["_trace_tokens"] = token_count
        report_dict["_inference_backend"] = backend
        # Preserve the full stage-1 exchange so RemediationAgent can build a
        # genuine multi-turn conversation — Bob sees its own prior analysis.
        report_dict["_stage1_exchange"] = [
            {"role": "user", "content": full_prompt},
            {"role": "assistant", "content": raw},
        ]

        # ── AST verification: badge each call chain edge ──────────────
        for chain in report_dict.get("call_chains", []):
            path: list[str] = chain.get("path", [])
            if len(path) < 2:
                chain["verification_status"] = "UNVERIFIABLE"
                continue
            caller_file = path[0]
            callee_path = path[1]
            caller_content = self.repo_context.get(caller_file, "")
            if not caller_content:
                chain["verification_status"] = "UNVERIFIABLE"
                continue
            callee_name = os.path.splitext(os.path.basename(callee_path))[0]
            ext = os.path.splitext(caller_file)[1]
            chain["verification_status"] = verify_call(
                caller_content, callee_name, ext)

        return report_dict

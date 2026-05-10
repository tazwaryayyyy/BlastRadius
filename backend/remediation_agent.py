import json
import logging
from typing import Callable

from gemini_client import GEMINI_FLASH, _clean_json, call_gemini
from models import RemediationResult

logger = logging.getLogger(__name__)


class RemediationAgent:
    """
    Generates test stubs and fix recommendations for uncovered critical paths.
    Operates on TraceAgent output. Uses Gemini Flash for speed.
    """

    async def run(
        self,
        report_dict: dict,
        repo_context: dict[str, str],
        stage_callback: Callable[[str], None] | None = None,
    ) -> dict:
        critical_uncovered = [
            c for c in report_dict.get("call_chains", [])
            if c.get("risk") == "CRITICAL" and not c.get("has_tests", True)
        ]

        remediations: list[dict] = []
        for chain in critical_uncovered:
            prompt = _build_prompt(chain, repo_context)
            try:
                raw = await call_gemini(prompt, model=GEMINI_FLASH)
                data = json.loads(_clean_json(raw))
                remediations.append(RemediationResult(**data).model_dump())
            except Exception as exc:
                logger.error(
                    "RemediationAgent skipping chain %s: %s", chain.get("id"), exc)

        report_dict["remediations"] = remediations

        if stage_callback:
            stage_callback("generating_verdict")

        return report_dict


def _build_prompt(chain: dict, repo_context: dict[str, str]) -> str:
    chain_id = chain.get("id", "unknown")
    path: list[str] = chain.get("path", [])
    symbols: list[str] = chain.get("symbols", [])
    impact: str = chain.get("business_impact", "")

    file_blocks = "\n\n".join(
        f"### {p}\n```\n{repo_context[p]}\n```"
        for p in path if p in repo_context
    )

    leaf = path[-1].split("/")[-1] if path else "module"
    module_name = leaf.replace(".js", "").replace(".ts", "").replace(".py", "")

    return (
        f"You are a test engineer. Generate a complete, runnable pytest stub for this "
        f"untested CRITICAL code path. No preamble. Output ONLY valid JSON.\n\n"
        f"Chain: {chain_id}\nPath: {' -> '.join(path)}\n"
        f"Symbols: {', '.join(symbols)}\nBusiness impact: {impact}\n\n"
        f"Source files:\n{file_blocks}\n\n"
        f"Output exactly this JSON shape:\n"
        f'{{"chain_id": "{chain_id}", '
        f'"test_file_path": "tests/test_{module_name}.py", '
        f'"test_stub": "<complete runnable pytest code with real imports and assertions>", '
        f'"fix_summary": "<one sentence engineers can act on immediately>"}}'
    )

import json
import logging
from typing import Callable

from bob_client import call_bob, _clean_json
from models import CostEstimate, RemediationResult

logger = logging.getLogger(__name__)

# DORA 2023: median time to restore service after incident = 1.5 hours
# PagerDuty 2023: average cost per incident hour = $600 (eng + on-call + ops)
# Assumes 1 CRITICAL uncovered chain = 1 potential incident
INCIDENT_RESTORE_HOURS = 1.5
COST_PER_HOUR = 600
HOURS_SAVED_PER_STUB = 1.6  # time to manually write + debug a test


class RemediationAgent:
    """
    Generates test stubs and fix recommendations for uncovered critical paths.
    Operates on TraceAgent output. Uses IBM Bob (watsonx.ai).
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
                raw = await call_bob(prompt)
                data = json.loads(_clean_json(raw))
                remediations.append(RemediationResult(**data).model_dump())
            except Exception as exc:
                logger.error(
                    "RemediationAgent skipping chain %s: %s", chain.get("id"), exc)

        report_dict["remediations"] = remediations

        # ── Cost estimate (only when verdict is BLOCK) ─────────────────
        if report_dict.get("merge_recommendation", "").upper().find("BLOCK") != -1:
            critical_uncovered_count = len([
                c for c in report_dict.get("call_chains", [])
                if c.get("risk") == "CRITICAL" and not c.get("has_tests", True)
            ])
            stubs_count = len(remediations)
            incident_cost = critical_uncovered_count * \
                INCIDENT_RESTORE_HOURS * COST_PER_HOUR
            hours_saved = stubs_count * HOURS_SAVED_PER_STUB
            cost_estimate = CostEstimate(
                incident_cost_usd=round(incident_cost, 2),
                hours_saved=round(hours_saved, 1),
                stubs_generated=stubs_count,
                calculation_basis=(
                    f"Based on {critical_uncovered_count} critical uncovered path(s). "
                    f"DORA 2023: median restore time {INCIDENT_RESTORE_HOURS}h "
                    f"at ${COST_PER_HOUR}/hr engineering cost."
                ),
            )
            report_dict["cost_estimate"] = cost_estimate.model_dump()

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

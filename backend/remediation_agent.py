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
        # Pop stage-1 exchange before processing — used for multi-turn context below
        stage1_exchange: list[dict] = report_dict.pop("_stage1_exchange", [])
        prior_backend: str = report_dict.pop("_inference_backend", "bob")

        uncovered_chains = [
            c for c in report_dict.get("call_chains", [])
            if c.get("risk") in ("CRITICAL", "HIGH") and not c.get("has_tests", True)
        ]

        remediations: list[dict] = []
        remediation_tokens = 0
        used_fallback = prior_backend == "fallback"
        for chain in uncovered_chains:
            prompt = _build_prompt(chain, repo_context)
            # Multi-turn: append Stage 2 ask to Stage 1 exchange so Bob sees
            # its own prior trace analysis as conversation context.
            messages = stage1_exchange + [{"role": "user", "content": prompt}]
            try:
                raw, tokens, backend = await call_bob(messages=messages)
                if backend == "fallback":
                    used_fallback = True
                remediation_tokens += tokens
                data = json.loads(_clean_json(raw))
                remediations.append(RemediationResult(**data).model_dump())
            except Exception as exc:
                logger.error(
                    "RemediationAgent skipping chain %s: %s", chain.get("id"), exc)

        report_dict["remediations"] = remediations
        report_dict["_remediation_tokens"] = remediation_tokens
        # Propagate backend: sticky — once any call hit fallback, the report is "fallback"
        report_dict["_inference_backend"] = "fallback" if used_fallback else "bob"

        # ── Cost estimate (only when verdict is BLOCK) ─────────────────
        if report_dict.get("merge_recommendation", "").upper().find("BLOCK") != -1:
            all_chains = report_dict.get("call_chains", [])
            critical_uncovered_count = len([
                c for c in all_chains
                if c.get("risk") == "CRITICAL" and not c.get("has_tests", True)
            ])
            high_uncovered_count = len([
                c for c in all_chains
                if c.get("risk") == "HIGH" and not c.get("has_tests", True)
            ])
            stubs_count = len(remediations)
            # CRITICAL paths weighted at full incident cost; HIGH at 50%
            incident_cost = (
                critical_uncovered_count + high_uncovered_count * 0.5
            ) * INCIDENT_RESTORE_HOURS * COST_PER_HOUR
            hours_saved = stubs_count * HOURS_SAVED_PER_STUB
            parts = []
            if critical_uncovered_count:
                parts.append(f"{critical_uncovered_count} critical")
            if high_uncovered_count:
                parts.append(f"{high_uncovered_count} high-risk")
            path_desc = (" + ".join(parts) +
                         " uncovered path(s)") if parts else "uncovered paths"
            cost_estimate = CostEstimate(
                incident_cost_usd=round(incident_cost, 2),
                hours_saved=round(hours_saved, 1),
                stubs_generated=stubs_count,
                calculation_basis=(
                    f"Based on {path_desc}. "
                    f"DORA 2023: median restore time {INCIDENT_RESTORE_HOURS}h "
                    f"at ${COST_PER_HOUR}/hr engineering cost. "
                    f"Estimate based on industry medians — your actual figures may vary."
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

    risk_level = chain.get("risk", "CRITICAL")
    return (
        f"You are a test engineer. Generate a complete, runnable pytest stub for this "
        f"untested {risk_level} code path. No preamble. Output ONLY valid JSON.\n\n"
        f"Chain: {chain_id}\nPath: {' -> '.join(path)}\n"
        f"Symbols: {', '.join(symbols)}\nBusiness impact: {impact}\n\n"
        f"Source files:\n{file_blocks}\n\n"
        f"Output exactly this JSON shape:\n"
        f'{{"chain_id": "{chain_id}", '
        f'"test_file_path": "tests/test_{module_name}.py", '
        f'"test_stub": "<complete runnable pytest code with real imports and assertions>", '
        f'"fix_summary": "<one sentence engineers can act on immediately>"}}'
    )

"""
prompt_builder.py
Constructs the system and user prompts for Bob.

Design principles:
- System prompt is short (<100 words). All reasoning load goes in the user turn.
- File contents wrapped in fenced code blocks with filenames as headers.
- Step-by-step task instruction BEFORE the JSON format forces Bob to reason
    before generating output, dramatically reducing hallucination.
- Hard "Output ONLY valid JSON" at the end prevents markdown wrapping.
"""

from models import DiffResult
from repo_loader import build_file_tree, get_context_bundle

# -----------------------------------------------------------------
# Extension → language mapping for syntax highlighting in the prompt
# -----------------------------------------------------------------
EXT_LANG: dict[str, str] = {
    ".js": "javascript", ".ts": "typescript", ".jsx": "javascript",
    ".tsx": "typescript", ".py": "python", ".go": "go",
    ".java": "java", ".rb": "ruby", ".rs": "rust",
    ".cs": "csharp", ".cpp": "cpp", ".c": "c",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".sh": "bash", ".md": "markdown",
}


def _ext(path: str) -> str:
    import os
    return EXT_LANG.get(os.path.splitext(path)[-1].lower(), "")


# -----------------------------------------------------------------
# System prompt
# -----------------------------------------------------------------
SYSTEM_PROMPT = """You are BlastRadius — a precise code impact analysis engine with access to a complete repository.
Your sole job: trace the full behavioral impact of a PR change across the codebase.
Rules:
- Reason step by step BEFORE outputting JSON.
- Never guess. Only report call chains you can directly trace through the provided code.
- Never output markdown. Never wrap JSON in backticks.
- Be concise but accurate in business_impact fields — no jargon."""


# -----------------------------------------------------------------
# Task instruction block (injected at end of user prompt)
# -----------------------------------------------------------------
TASK_BLOCK = """
## YOUR TASK

Follow these steps IN ORDER before producing output:

STEP 1 — SYMBOL IDENTIFICATION
For each changed symbol listed above, find EVERY call site across all provided files.
Quote the exact file path and line content where each call occurs.

STEP 2 — CHAIN TRACING (transitive, max 5 hops)
For each call site, trace upward: what calls the function that calls the changed symbol?
Continue until you reach entry points (HTTP route handlers, queue consumers, cron functions, CLI commands, exports).
Build the complete chain from changed file → entry point.

STEP 3 — RISK CLASSIFICATION
For each complete chain, assign risk:
    CRITICAL = chain reaches financial, auth, or data-mutation logic AND has no test coverage
    HIGH     = chain reaches core business logic with partial or no test coverage
    MEDIUM   = chain reaches secondary logic; some tests exist but gaps remain
    LOW      = chain is well-tested or has graceful fallback (try/catch, queue, etc.)

STEP 3A — CONFIDENCE LABEL
For each chain, assign a confidence level based on how directly the path is proven in code.
    HIGH   = direct static import or explicit call chain shown in provided files
    MEDIUM = one step inferred from surrounding code structure; still likely correct
    LOW    = dynamic dispatch, indirect runtime wiring, or partial evidence only
Use explicit uncertainty language in confidence_reason whenever anything is inferred.

STEP 4 — TEST COVERAGE CHECK
For each chain, check whether any file in __tests__/, *.test.*, or *.spec.* explicitly
imports and calls a function in this chain's path. Set has_tests accordingly.

STEP 5 — OUTPUT
Produce ONLY the following JSON object. No preamble. No markdown. No backticks.

{
    "changed_symbols": ["<list of changed symbol names>"],
    "call_chains": [
    {
      "id": "chain_1",
      "risk": "CRITICAL",
      "path": ["shared/rate_limiter.js", "api/routes/payments.js", "services/billing/process.js"],
      "symbols": ["applyRateLimit", "processPayment", "chargeCard"],
      "confidence": "HIGH",
      "confidence_reason": "Direct static import chain.",
      "has_tests": false,
      "test_files": [],
      "business_impact": "Payment retries will be blocked — halved rate window rejects legitimate Stripe retries. No test covers this.",
      "explanation": "applyRateLimit() exported from rate_limiter.js is called at payments.js:47 inside processPayment(), which calls chargeCard() in billing/process.js. No file in __tests__/ imports or calls processPayment."
    }
    ],
    "safe_paths": ["api/routes/health.js uses a rate-limit bypass — unaffected"],
    "risk_summary": {"CRITICAL": 1, "HIGH": 0, "MEDIUM": 1, "LOW": 1},
    "merge_recommendation": "BLOCK MERGE — CRITICAL untested billing path exposed. Add tests for processPayment() before merging.",
    "suggested_actions": [
    "Add test for processPayment() covering rate limit window < 30s",
    "Add retry backoff in billing/process.js before calling chargeCard()",
    "Verify Stripe webhook retry interval against new windowMs value"
    ]
}
"""


# -----------------------------------------------------------------
# Public API
# -----------------------------------------------------------------
def build_system_prompt() -> str:
    return SYSTEM_PROMPT.strip()


def build_user_prompt(
    all_files: dict[str, str],
    diff: DiffResult,
) -> str:
    sections: list[str] = []

    # ── 1. Repository file contents (context-limited, priority-ordered) ──
    # Keep prompt under provider payload limits by adapting context to diff size.
    # Larger diffs consume more budget, so repository context is reduced accordingly.
    dynamic_repo_budget = max(12_000, 38_000 - len(diff.raw_diff))
    bundle = get_context_bundle(
        all_files,
        diff.changed_files,
        diff.symbols,
        context_limit=dynamic_repo_budget,
    )

    # ── 2. File tree (only included files, not the entire repository) ─────
    file_tree = build_file_tree(list(bundle.keys()))
    omitted = max(0, len(all_files) - len(bundle))
    omitted_note = f"\n(Omitted {omitted} lower-priority files to fit model context.)" if omitted else ""
    sections.append(
        f"## REPOSITORY STRUCTURE\n```\n{file_tree}\n```{omitted_note}")

    # ── 3. Repository file contents ───────────────────────────────
    file_blocks: list[str] = []
    for path, content in bundle.items():
        lang = _ext(path)
        file_blocks.append(f"### {path}\n```{lang}\n{content}\n```")
    sections.append("## REPOSITORY FILES\n\n" + "\n\n".join(file_blocks))

    # ── 4. PR diff ────────────────────────────────────────────────
    sections.append(f"## PR DIFF\n```diff\n{diff.raw_diff}\n```")

    # ── 5. Changed symbols ────────────────────────────────────────
    if diff.symbols:
        sym_list = "\n".join(f"- `{s}`" for s in diff.symbols)
        sections.append(
            f"## CHANGED SYMBOLS\nThe following symbols were modified in this PR:\n{sym_list}")
    else:
        sections.append(
            "## CHANGED SYMBOLS\n"
            "No named symbols detected automatically. "
            "Infer changed behaviour from the diff above."
        )

    # ── 6. Task instruction ───────────────────────────────────────
    sections.append(TASK_BLOCK.strip())

    return "\n\n".join(sections)

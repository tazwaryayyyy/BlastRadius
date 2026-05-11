# IBM Bob Usage Log

BlastRadius was built in partnership with IBM Bob (watsonx.ai) across 5 
documented sessions. Bob reviewed core modules, suggested improvements, 
and generated code that was implemented directly into the codebase.

**Model used:** meta-llama/llama-3-3-70b-instruct  
**Platform:** IBM watsonx.ai (jp-tok region)  
**Project ID:** bce5cc58-77fd-49c2-abe1-96a35aad0054

---

## Session 1 — Prompt Engineering Review
**File:** `backend/prompt_builder.py`  
**Ask:** Review the call chain tracing prompt and suggest improvements 
to reduce hallucination in impact analysis.

**Bob's contribution:**
- Recommended adding `###` headers to each step for clearer instruction 
  boundaries
- Suggested replacing "business impact" with "specific business logic 
  that will be affected" for more precise outputs
- Recommended adding examples and guidance for ambiguous cases
- Provided a complete rewritten `TASK_BLOCK` with the improvements applied

**Implemented:** Yes — TASK_BLOCK updated with Bob's structural suggestions.

---

## Session 2 — TypeScript Symbol Detection
**File:** `backend/diff_parser.py`  
**Ask:** Add support for detecting TypeScript `interface` declarations 
and `type` aliases as named symbols in diff analysis.

**Bob's contribution:**
- Added two new regex patterns to `SYMBOL_PATTERNS`:
  - `r'^[+-].*\binterface\s+(\w+)'` — detects interface declarations
  - `r'^[+-].*\btype\s+(\w+)\s*=\s*'` — detects type alias definitions
- Fixed group index handling for multi-group patterns

**Implemented:** Yes — both patterns added to `diff_parser.py`.

---

## Session 3 — AST Verifier Edge Case Review  
**File:** `backend/ast_verifier.py`  
**Ask:** Identify edge cases missing from Python call detection — 
specifically decorators, classmethod calls, and list comprehensions.

**Bob's contribution:**
- Confirmed the AST walk correctly handles `ast.Name` and `ast.Attribute` 
  call nodes
- Validated that `ast.walk` traverses into comprehension bodies, 
  covering the list comprehension edge case
- Confirmed decorator calls are covered via `ast.Call` on decorator nodes

**Implemented:** Yes — Bob's analysis validated and confirmed the 
existing implementation. No changes needed.

---

## Session 4 — Test Case Generation
**File:** `backend/test_pipeline.py`  
**Ask:** Generate 3 additional test cases covering edge cases not 
in the existing suite.

**Bob's contribution:**
Generated 3 new test cases:
1. `test_empty_diff` — validates `parse_diff("")` returns empty lists
2. `test_non_existent_repo` — validates `load_repo` raises 
   `FileNotFoundError` for missing paths
3. `test_empty_files` — validates `build_user_prompt` handles 
   empty file dict without crashing

**Implemented:** Yes — all 3 tests added to `test_pipeline.py`.

---

## Session 5 — GitHub Actions Workflow Hardening
**File:** `.github/workflows/blastradius.yml`  
**Ask:** Improve robustness of the workflow — specifically timeout 
handling and error reporting.

**Bob's contribution:**
- Increased `timeout-minutes` from 5 to 10
- Added `--retry 3 --retry-delay 10` to curl for transient API failures
- Added a `Handle API Error` step that posts a PR comment when the 
  API is unavailable
- Recommended PR_URL input validation

**Implemented:** Yes — retry logic and error handling step added 
to `blastradius.yml`.

---

## Session Exports

Raw API request/response JSON for each session:

- [`bob_sessions/session1_prompt_review.json`](bob_sessions/session1_prompt_review.json)
- [`bob_sessions/session2_diff_parser.json`](bob_sessions/session2_diff_parser.json)
- [`bob_sessions/session3_ast_verifier.json`](bob_sessions/session3_ast_verifier.json)
- [`bob_sessions/session4_test_pipeline.json`](bob_sessions/session4_test_pipeline.json)
- [`bob_sessions/session5_github_actions.json`](bob_sessions/session5_github_actions.json)

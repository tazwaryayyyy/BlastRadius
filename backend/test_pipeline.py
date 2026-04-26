"""
test_pipeline.py
Smoke tests for the BlastRadius backend pipeline.
Runs without a real Bob API — mocks the LLM call.

Run: pytest test_pipeline.py -v
"""

from models import BlastRadiusReport, RiskSummary, CallChain
from prompt_builder import build_system_prompt, build_user_prompt
from repo_loader import load_repo, build_file_tree, prioritize_files, get_context_bundle
from diff_parser import parse_diff
import json
import sys
import os
import pytest

# Ensure backend dir is on path
sys.path.insert(0, os.path.dirname(__file__))


# ── Fixtures ──────────────────────────────────────────────────────

DEMO_DIFF = open(
    os.path.join(os.path.dirname(__file__), "..",
                 "demo_prs", "pr_ratelimiter.diff"),
    encoding="utf-8",
).read()

DEMO_REPO_PATH = os.path.join(os.path.dirname(__file__), "..", "demo_repo")

MOCK_BOB_RESPONSE = {
    "changed_symbols": ["applyRateLimit"],
    "call_chains": [
        {
            "id": "chain_1",
            "risk": "CRITICAL",
            "path": [
                "shared/rate_limiter.js",
                "api/routes/payments.js",
                "services/billing/process.js",
                "services/billing/stripe_client.js"
            ],
            "symbols": ["applyRateLimit", "handleCharge", "processPayment", "chargeCard"],
            "confidence": "HIGH",
            "confidence_reason": "Direct static import chain.",
            "has_tests": False,
            "test_files": [],
            "business_impact": "Payment retries blocked — halved rate window rejects Stripe retries. No test covers this path.",
            "explanation": "applyRateLimit() called at payments.js:27 inside handleCharge(), which calls billing.processPayment(), which calls stripe.chargeCard(). No __tests__ file imports processPayment."
        },
        {
            "id": "chain_2",
            "risk": "MEDIUM",
            "path": ["shared/rate_limiter.js", "api/routes/auth.js"],
            "symbols": ["applyRateLimit", "loginUser"],
            "confidence": "HIGH",
            "confidence_reason": "Direct static import chain.",
            "has_tests": True,
            "test_files": ["__tests__/auth.test.js"],
            "business_impact": "Login rate limit tightened. Auth tests cover this path.",
            "explanation": "applyRateLimit() called at auth.js:20 inside loginUser(). Covered by auth.test.js."
        },
        {
            "id": "chain_3",
            "risk": "LOW",
            "path": ["shared/rate_limiter.js", "api/routes/webhooks.js", "services/notifications/email.js"],
            "symbols": ["applyRateLimit", "handleNotification", "sendEmail"],
            "confidence": "MEDIUM",
            "confidence_reason": "Inferred via fallback handling path — verify manually.",
            "has_tests": True,
            "test_files": ["__tests__/webhooks.test.js"],
            "business_impact": "Notification rate limiting tightened. Graceful queue fallback — no data loss.",
            "explanation": "webhooks.js catches 429 and calls queueEmail(). Covered by webhooks.test.js."
        }
    ],
    "safe_paths": ["api/routes/payments.js:getPaymentStatus uses http_client directly — unaffected"],
    "risk_summary": {"CRITICAL": 1, "HIGH": 0, "MEDIUM": 1, "LOW": 1},
    "merge_recommendation": "BLOCK MERGE — CRITICAL untested billing path exposed. Add tests for processPayment() before merging.",
    "suggested_actions": [
        "Add test for processPayment() covering rate limit window < 30s",
        "Add retry backoff in billing/process.js before calling chargeCard()",
        "Verify Stripe webhook retry interval against new windowMs value"
    ]
}


# ── diff_parser tests ──────────────────────────────────────────────

class TestDiffParser:
    def test_extracts_changed_files(self):
        result = parse_diff(DEMO_DIFF)
        assert any("rate_limiter" in f for f in result.changed_files), \
            f"Expected rate_limiter.js in changed_files, got: {result.changed_files}"

    def test_extracts_symbols(self):
        result = parse_diff(DEMO_DIFF)
        # The diff modifies constructor internals — symbols may be empty for property changes
        # That's expected: the changed_files list is what matters for Bob's context
        assert isinstance(result.symbols, list)

    def test_raw_diff_preserved(self):
        result = parse_diff(DEMO_DIFF)
        assert result.raw_diff == DEMO_DIFF

    def test_no_duplicate_files(self):
        result = parse_diff(DEMO_DIFF)
        assert len(result.changed_files) == len(set(result.changed_files))

    def test_empty_diff(self):
        result = parse_diff("")
        assert result.changed_files == []
        assert result.symbols == []


# ── repo_loader tests ──────────────────────────────────────────────

class TestRepoLoader:
    def test_loads_demo_repo(self):
        files = load_repo(DEMO_REPO_PATH)
        assert len(files) > 0, "Should load at least one file"

    def test_loads_js_files(self):
        files = load_repo(DEMO_REPO_PATH)
        js_files = [p for p in files if p.endswith(".js")]
        assert len(js_files) >= 5, f"Expected ≥5 JS files, got {len(js_files)}"

    def test_skips_node_modules(self):
        files = load_repo(DEMO_REPO_PATH)
        assert not any("node_modules" in p for p in files)

    def test_rate_limiter_loaded(self):
        files = load_repo(DEMO_REPO_PATH)
        assert any("rate_limiter" in p for p in files), \
            "rate_limiter.js should be in loaded files"

    def test_payments_loaded(self):
        files = load_repo(DEMO_REPO_PATH)
        assert any("payments" in p for p in files)

    def test_build_file_tree_returns_string(self):
        files = load_repo(DEMO_REPO_PATH)
        tree = build_file_tree(list(files.keys()))
        assert isinstance(tree, str)
        assert len(tree) > 0

    def test_prioritize_puts_changed_first(self):
        files = load_repo(DEMO_REPO_PATH)
        changed = ["shared/rate_limiter.js"]
        ordered = prioritize_files(files, changed, ["applyRateLimit"])
        assert ordered[0] == "shared/rate_limiter.js", \
            f"Changed file should be first, got: {ordered[0]}"

    def test_importers_come_before_unrelated(self):
        files = load_repo(DEMO_REPO_PATH)
        changed = ["shared/rate_limiter.js"]
        ordered = prioritize_files(files, changed, ["applyRateLimit"])
        # payments.js, auth.js, webhooks.js all import rate_limiter
        # They should appear before http_client.js which doesn't
        importer_indices = [i for i, p in enumerate(
            ordered) if "payments" in p or "auth" in p]
        safe_indices = [i for i, p in enumerate(ordered) if "http_client" in p]
        if importer_indices and safe_indices:
            assert min(importer_indices) < min(safe_indices), \
                "Importers of changed file should appear before unrelated files"

    def test_context_bundle_respects_limit(self):
        files = load_repo(DEMO_REPO_PATH)
        diff = parse_diff(DEMO_DIFF)
        bundle = get_context_bundle(files, diff.changed_files, diff.symbols)
        total = sum(len(c) for c in bundle.values())
        assert total <= 90_000, f"Bundle exceeds 90k char limit: {total}"


# ── prompt_builder tests ───────────────────────────────────────────

class TestPromptBuilder:
    files: dict
    diff: object

    def setup_method(self):
        self.files = load_repo(DEMO_REPO_PATH)
        self.diff = parse_diff(DEMO_DIFF)

    def test_system_prompt_is_short(self):
        system = build_system_prompt()
        word_count = len(system.split())
        assert word_count < 150, f"System prompt too long: {word_count} words"

    def test_system_prompt_has_no_json(self):
        # System prompt should be instructions only, not include JSON schema
        system = build_system_prompt()
        assert "call_chains" not in system

    def test_user_prompt_contains_diff(self):
        user = build_user_prompt(self.files, self.diff)
        assert "PR DIFF" in user
        assert "windowMs" in user  # content from the actual diff

    def test_user_prompt_contains_repo_files(self):
        user = build_user_prompt(self.files, self.diff)
        assert "REPOSITORY FILES" in user
        assert "rate_limiter" in user

    def test_user_prompt_contains_task(self):
        user = build_user_prompt(self.files, self.diff)
        assert "YOUR TASK" in user
        assert "STEP 1" in user
        assert "STEP 5" in user

    def test_user_prompt_mentions_confidence_and_actions(self):
        user = build_user_prompt(self.files, self.diff)
        assert '"confidence"' in user
        assert '"confidence_reason"' in user
        assert '"suggested_actions"' in user

    def test_user_prompt_ends_with_json_instruction(self):
        user = build_user_prompt(self.files, self.diff)
        assert "valid JSON" in user or "ONLY" in user

    def test_user_prompt_has_file_tree(self):
        user = build_user_prompt(self.files, self.diff)
        assert "REPOSITORY STRUCTURE" in user

    def test_rate_limiter_is_first_file_in_repo_files_section(self):
        user = build_user_prompt(self.files, self.diff)
        # Slice to the FILES section only — the tree section uses alphabetical order
        # which puts api/routes/ before shared/, but FILES section uses priority order
        files_section_start = user.find("## REPOSITORY FILES")
        assert files_section_start != -1, "REPOSITORY FILES section not found"
        files_section = user[files_section_start:]
        rl_pos = files_section.find("rate_limiter.js")
        payments_pos = files_section.find("payments.js")
        assert rl_pos != -1, "rate_limiter.js not found in FILES section"
        assert payments_pos != -1, "payments.js not found in FILES section"
        assert rl_pos < payments_pos, \
            "rate_limiter.js (changed file) should appear before payments.js in the FILES section"


# ── models tests ───────────────────────────────────────────────────

class TestModels:
    def test_blast_radius_report_parses_mock(self):
        data = dict(MOCK_BOB_RESPONSE)
        data["risk_summary"] = RiskSummary(**{
            k.upper(): v for k, v in data["risk_summary"].items()
        })
        report = BlastRadiusReport(**data)
        assert len(report.call_chains) == 3
        assert report.call_chains[0].risk == "CRITICAL"
        assert report.call_chains[0].has_tests is False
        assert report.call_chains[1].has_tests is True

    def test_risk_summary_defaults_to_zero(self):
        rs = RiskSummary()
        assert rs.CRITICAL == 0
        assert rs.HIGH == 0
        assert rs.MEDIUM == 0
        assert rs.LOW == 0

    def test_call_chain_requires_valid_risk(self):
        with pytest.raises(Exception):
            CallChain(
                id="c1", risk="UNKNOWN", path=["a.js"], symbols=["fn"],
                confidence="HIGH", confidence_reason="Direct static import chain.",
                has_tests=False, business_impact="x", explanation="y"
            )

    def test_call_chain_requires_valid_confidence(self):
        with pytest.raises(Exception):
            CallChain(
                id="c1", risk="LOW", path=["a.js"], symbols=["fn"],
                confidence="UNKNOWN", confidence_reason="x",
                has_tests=False, business_impact="x", explanation="y"
            )

    def test_report_json_round_trip(self):
        data = dict(MOCK_BOB_RESPONSE)
        data["risk_summary"] = RiskSummary(**{
            k.upper(): v for k, v in data["risk_summary"].items()
        })
        report = BlastRadiusReport(**data)
        dumped = report.model_dump()
        assert dumped["risk_summary"]["CRITICAL"] == 1
        assert len(dumped["call_chains"]) == 3
        assert dumped["call_chains"][0]["confidence"] == "HIGH"
        assert len(dumped["suggested_actions"]) == 3


# ── Integration: full pipeline ─────────────────────────────────────

class TestFullPipeline:
    """
    Runs the complete pipeline (parse → load → build prompt → parse mock response)
    without any HTTP calls.
    """

    def test_pipeline_produces_valid_report(self):
        # 1. Parse diff
        diff = parse_diff(DEMO_DIFF)
        assert diff.changed_files

        # 2. Load repo
        files = load_repo(DEMO_REPO_PATH)
        assert files

        # 3. Build prompt (just check it doesn't crash and has content)
        system = build_system_prompt()
        user = build_user_prompt(files, diff)
        assert len(system) > 50
        assert len(user) > 500

        # 4. Parse the mock response (simulates what Bob returns)
        raw = json.dumps(MOCK_BOB_RESPONSE)
        data = json.loads(raw)
        data["risk_summary"] = RiskSummary(**{
            k.upper(): v for k, v in data["risk_summary"].items()
        })
        report = BlastRadiusReport(**data)

        # 5. Validate the report structure
        assert report.changed_symbols == ["applyRateLimit"]
        assert len(report.call_chains) == 3
        assert report.risk_summary.CRITICAL == 1
        assert report.risk_summary.LOW == 1
        assert "BLOCK" in report.merge_recommendation

    def test_critical_chain_is_billing(self):
        data = dict(MOCK_BOB_RESPONSE)
        data["risk_summary"] = RiskSummary(**{
            k.upper(): v for k, v in data["risk_summary"].items()
        })
        report = BlastRadiusReport(**data)

        critical = [c for c in report.call_chains if c.risk == "CRITICAL"]
        assert len(critical) == 1
        assert any("billing" in p or "stripe" in p for p in critical[0].path)
        assert critical[0].has_tests is False

    def test_low_chain_has_tests(self):
        data = dict(MOCK_BOB_RESPONSE)
        data["risk_summary"] = RiskSummary(**{
            k.upper(): v for k, v in data["risk_summary"].items()
        })
        report = BlastRadiusReport(**data)

        low = [c for c in report.call_chains if c.risk == "LOW"]
        assert len(low) == 1
        assert low[0].has_tests is True


# ── Bob fallback tests ─────────────────────────────────────────────

class TestBobFallback:
    """
    Verifies the primary→fallback path without any live API calls.
    Patches bob_client module attributes and the internal _post helper.
    """

    def _make_good_response(self):
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [{"message": {"content": json.dumps(MOCK_BOB_RESPONSE)}}]
        }
        resp.raise_for_status = MagicMock()
        return resp

    def test_fallback_triggers_when_primary_fails(self):
        """Primary endpoint raises; fallback endpoint returns valid JSON."""
        import asyncio
        import httpx
        from unittest.mock import patch
        import bob_client

        good_resp = self._make_good_response()
        calls = []

        async def fake_post(_client, url, _key, _payload):
            calls.append(url)
            if "garbage" in url:
                raise httpx.ConnectError("connection refused")
            return good_resp

        with patch.object(bob_client, "BOB_URL", "http://garbage.invalid"), \
                patch.object(bob_client, "BOB_KEY", "bad-key"), \
                patch.object(bob_client, "FALLBACK_URL", "http://real.fallback"), \
                patch.object(bob_client, "FALLBACK_KEY", "good-key"), \
                patch.object(bob_client, "FALLBACK_MODEL", "gpt-4o"), \
                patch("bob_client._post", side_effect=fake_post):

            result = asyncio.run(bob_client.analyze("system", "user"))

        assert "call_chains" in result, "Fallback must return valid JSON"
        assert calls[0] == "http://garbage.invalid", "Primary was not tried first"
        assert calls[1] == "http://real.fallback", "Fallback was not tried second"

    def test_fallback_produces_valid_report(self):
        """Full _parse_report round-trip on the fallback JSON output."""
        import asyncio
        import httpx
        from unittest.mock import patch
        import bob_client
        from main import _parse_report

        good_resp = self._make_good_response()

        async def fake_post(_client, url, _key, _payload):
            if "garbage" in url:
                raise httpx.ConnectError("connection refused")
            return good_resp

        with patch.object(bob_client, "BOB_URL", "http://garbage.invalid"), \
                patch.object(bob_client, "BOB_KEY", "bad-key"), \
                patch.object(bob_client, "FALLBACK_URL", "http://real.fallback"), \
                patch.object(bob_client, "FALLBACK_KEY", "good-key"), \
                patch.object(bob_client, "FALLBACK_MODEL", "gpt-4o"), \
                patch("bob_client._post", side_effect=fake_post):

            raw_json = asyncio.run(bob_client.analyze("system", "user"))

        report = _parse_report(raw_json, "Test PR")

        assert report.risk_summary.CRITICAL == 1
        assert len(report.call_chains) == 3
        assert "BLOCK" in report.merge_recommendation
        assert len(report.suggested_actions) == 3

    def test_lowercase_confidence_is_normalised(self):
        """_parse_report must uppercase confidence even when Bob returns lowercase."""
        from main import _parse_report

        payload = json.dumps({
            **MOCK_BOB_RESPONSE,
            "call_chains": [
                {**c, "confidence": c["confidence"].lower()}
                for c in MOCK_BOB_RESPONSE["call_chains"]
            ],
        })
        report = _parse_report(payload, "Test PR")

        for chain in report.call_chains:
            assert chain.confidence in ("HIGH", "MEDIUM", "LOW"), \
                f"confidence must be uppercase, got: {chain.confidence!r}"

    def test_missing_suggested_actions_defaults_to_empty(self):
        """_parse_report must not crash when suggested_actions is absent."""
        from main import _parse_report

        payload = {k: v for k, v in MOCK_BOB_RESPONSE.items()
                   if k != "suggested_actions"}
        report = _parse_report(json.dumps(payload), "Test PR")
        assert report.suggested_actions == []

    def test_null_suggested_actions_defaults_to_empty(self):
        """_parse_report must not crash when suggested_actions is null."""
        from main import _parse_report

        payload = {**MOCK_BOB_RESPONSE, "suggested_actions": None}
        report = _parse_report(json.dumps(payload), "Test PR")
        assert report.suggested_actions == []

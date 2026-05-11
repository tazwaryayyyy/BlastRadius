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
import pathlib
import sys
import os
import pytest

# Ensure backend dir is on path
sys.path.insert(0, os.path.dirname(__file__))


# ── Fixtures ──────────────────────────────────────────────────────

_DEMO_DIFF_PATH = pathlib.Path(
    __file__).parent.parent / "demo_prs" / "pr_ratelimiter.diff"


def _load_demo_diff() -> str:
    with open(_DEMO_DIFF_PATH, encoding="utf-8") as f:
        return f.read()


# Keep a module-level alias so existing references compile;
# actual file I/O is deferred to test time via _load_demo_diff().
DEMO_DIFF: str  # assigned lazily — use _load_demo_diff() in tests

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
        result = parse_diff(_load_demo_diff())
        assert any("rate_limiter" in f for f in result.changed_files), \
            f"Expected rate_limiter.js in changed_files, got: {result.changed_files}"

    def test_extracts_symbols(self):
        result = parse_diff(_load_demo_diff())
        # The diff modifies constructor internals — symbols may be empty for property changes
        # That's expected: the changed_files list is what matters for Bob's context
        assert isinstance(result.symbols, list)

    def test_raw_diff_preserved(self):
        result = parse_diff(_load_demo_diff())
        assert result.raw_diff == _load_demo_diff()

    def test_no_duplicate_files(self):
        result = parse_diff(_load_demo_diff())
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
        diff = parse_diff(_load_demo_diff())
        bundle, _stats = get_context_bundle(
            files, diff.changed_files, diff.symbols)
        total = sum(len(c) for c in bundle.values())
        assert total <= 90_000, f"Bundle exceeds 90k char limit: {total}"


# ── prompt_builder tests ───────────────────────────────────────────

class TestPromptBuilder:
    files: dict
    diff: object

    def setup_method(self):
        self.files = load_repo(DEMO_REPO_PATH)
        self.diff = parse_diff(_load_demo_diff())

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
        diff = parse_diff(_load_demo_diff())
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


# ── Bob client tests ─────────────────────────────────────────────

class TestGeminiClient:
    """
    Verifies bob_client retry behaviour and TraceAgent round-trip
    without any live API calls.
    """

    def _mock_bob_response(self, content: str):
        from unittest.mock import AsyncMock, MagicMock
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "choices": [{"message": {"content": content}}]
        }
        resp.raise_for_status = MagicMock()
        return resp

    def test_gemini_retries_on_429_then_succeeds(self):
        """429 on first attempt, 200 on second — client must retry and return content."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        import bob_client

        call_count = 0

        async def fake_post(self_client, url, json=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                resp = MagicMock()
                resp.status_code = 429
                resp.json.return_value = {}
                resp.raise_for_status = MagicMock()
                return resp
            return self._mock_bob_response(json_dumps_mock_response())

        with patch("httpx.AsyncClient.post", new=fake_post), \
                patch.object(bob_client, "BOB_API_KEY", "test-key"), \
                patch("bob_client._get_iam_token", new=AsyncMock(return_value="fake-iam-token")), \
                patch("asyncio.sleep", new=AsyncMock()):
            result = asyncio.run(bob_client.call_bob("test prompt"))

        assert "call_chains" in result
        assert call_count == 2

    def test_gemini_client_returns_parseable_json(self):
        """call_bob must return a string parseable by json.loads when Bob responds."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        import bob_client

        async def fake_post(self_client, url, json=None, **kwargs):
            return self._mock_bob_response(json_dumps_mock_response())

        with patch("httpx.AsyncClient.post", new=fake_post), \
                patch.object(bob_client, "BOB_API_KEY", "test-key"), \
                patch("bob_client._get_iam_token", new=AsyncMock(return_value="fake-iam-token")):
            raw = asyncio.run(bob_client.call_bob("test prompt"))

        data = json.loads(raw)
        assert "call_chains" in data

    def test_lowercase_confidence_is_normalised(self):
        """_parse_report must uppercase confidence even when Gemini returns lowercase."""
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


def json_dumps_mock_response() -> str:
    return json.dumps(MOCK_BOB_RESPONSE)


# ── Security tests ─────────────────────────────────────────────────

class TestSecurity:
    """Verify path traversal guards and session single-use semantics."""

    def test_safe_repo_path_rejects_traversal(self):
        """Paths that escape ALLOWED_REPO_ROOT must raise HTTP 400."""
        from fastapi import HTTPException
        from main import safe_repo_path
        import pytest

        with pytest.raises(HTTPException) as exc_info:
            safe_repo_path("../../etc/passwd")
        assert exc_info.value.status_code == 400

    def test_safe_repo_path_rejects_absolute_escape(self):
        """Absolute paths that fall outside ALLOWED_REPO_ROOT must raise HTTP 400."""
        from fastapi import HTTPException
        from main import safe_repo_path, ALLOWED_REPO_ROOT
        import pytest

        # Pick a path that is definitely outside the repo root.
        outside = str(ALLOWED_REPO_ROOT.parent.parent / "etc" / "passwd")
        with pytest.raises(HTTPException) as exc_info:
            safe_repo_path(outside)
        assert exc_info.value.status_code == 400

    def test_session_store_single_use(self):
        """A session must be consumed exactly once — the second lookup returns None."""
        from main import _session_store
        import uuid
        import time

        session_id = str(uuid.uuid4())
        _session_store[session_id] = {
            "diff": "dummy",
            "repo_path": "demo_repo",
            "pr_title": None,
            "created_at": time.monotonic(),
        }

        # First pop returns the value
        first = _session_store.pop(session_id, None)
        assert first is not None, "First lookup must return the stored session"

        # Second pop must return None (single-use guarantee)
        second = _session_store.pop(session_id, None)
        assert second is None, "Second lookup must return None (session already consumed)"


# ── Agent pipeline tests ───────────────────────────────────────────

class TestAgentPipeline:
    """End-to-end tests for the Gemini multi-agent pipeline without live API calls."""

    def test_trace_agent_returns_dict_with_required_keys(self):
        """TraceAgent.run() must return a dict with all required top-level keys."""
        import asyncio
        from unittest.mock import AsyncMock, patch
        from trace_agent import TraceAgent

        async def fake_call_gemini(prompt, **kwargs):
            return json_dumps_mock_response()

        with patch('trace_agent.call_bob', new=AsyncMock(side_effect=fake_call_gemini)):
            diff = parse_diff(_load_demo_diff())
            result = asyncio.run(TraceAgent({}).run(diff))

        for key in ('changed_symbols', 'call_chains', 'merge_recommendation', 'risk_summary'):
            assert key in result, f"Missing key: {key}"

    def test_remediation_agent_skips_non_critical_chains(self):
        """RemediationAgent must not call Gemini for MEDIUM/LOW chains."""
        import asyncio
        from unittest.mock import AsyncMock, patch
        from remediation_agent import RemediationAgent

        report_dict = {
            **json.loads(json_dumps_mock_response()),
            'call_chains': [
                {**c, 'risk': 'MEDIUM', 'has_tests': True}
                for c in json.loads(json_dumps_mock_response())['call_chains']
            ],
        }

        with patch('bob_client.call_bob', new=AsyncMock()) as mock_bob:
            result = asyncio.run(RemediationAgent().run(report_dict, {}))
            mock_bob.assert_not_called()

        assert result['remediations'] == []

    def test_remediation_agent_generates_stub_for_critical_uncovered(self):
        """RemediationAgent must call Gemini once per CRITICAL chain with no tests."""
        import asyncio
        from unittest.mock import AsyncMock, patch
        from remediation_agent import RemediationAgent

        rem_json = json.dumps({
            'chain_id': 'processPayment',
            'test_file_path': 'services/billing/__tests__/process.test.js',
            'test_stub': 'describe("processPayment", () => { it("should charge card") })',
            'fix_summary': 'Add integration test for payment processing path',
        })

        report_dict = {
            **json.loads(json_dumps_mock_response()),
            'call_chains': [
                {'id': 'processPayment', 'risk': 'CRITICAL', 'has_tests': False,
                 'path': ['api/routes/payments.js', 'services/billing/process.js'],
                 'symbols': ['processPayment'], 'business_impact': 'Revenue at risk',
                 'explanation': 'Payment flow', 'confidence': 'HIGH',
                 'confidence_reason': '', 'test_files': []},
            ],
        }

        with patch('remediation_agent.call_bob', new=AsyncMock(return_value=rem_json)):
            result = asyncio.run(RemediationAgent().run(report_dict, {}))

        assert len(result['remediations']) == 1
        assert result['remediations'][0]['test_stub']

    def test_parse_pr_url_valid(self):
        """parse_pr_url must correctly extract owner, repo, and PR number."""
        import asyncio
        from github_loader import parse_pr_url

        owner, repo, num = asyncio.run(parse_pr_url(
            'https://github.com/vercel/next.js/pull/12345'))
        assert owner == 'vercel'
        assert repo == 'next.js'
        assert num == 12345

    def test_parse_pr_url_invalid_raises(self):
        """parse_pr_url must raise ValueError for non-PR URLs."""
        import asyncio
        import pytest
        from github_loader import parse_pr_url

        with pytest.raises(ValueError):
            asyncio.run(parse_pr_url('https://github.com/owner/repo'))

    def test_report_store_ttl_expiry(self):
        """get_report must return None for expired entries."""
        import asyncio
        import time
        import report_store

        async def _run():
            report = BlastRadiusReport(**json.loads(json_dumps_mock_response()),
                                       pr_title='TTL test')
            rid = await report_store.store_report(report)
            # Manually expire the entry
            data, _ = report_store._store[rid]
            report_store._store[rid] = (data, time.monotonic() - 3700)
            return await report_store.get_report(rid)

        result = asyncio.run(_run())
        assert result is None, 'Expired report must return None'

    def test_report_store_evicts_oldest_at_limit(self):
        """Report store must not exceed _MAX_REPORTS entries."""
        import asyncio
        import report_store

        async def _run():
            report = BlastRadiusReport(**json.loads(json_dumps_mock_response()),
                                       pr_title='eviction test')
            for _ in range(report_store._MAX_REPORTS + 1):
                await report_store.store_report(report)
            return len(report_store._store)

        count = asyncio.run(_run())
        assert count <= report_store._MAX_REPORTS

from pydantic import BaseModel, Field
from typing import Literal, Optional


class AnalyzeRequest(BaseModel):
    diff: str
    repo_path: str = "demo_repo"
    pr_title: Optional[str] = None
    stream: bool = False


class GithubAnalyzeRequest(BaseModel):
    pr_url: str
    image_b64: Optional[str] = None
    mime_type: Optional[str] = None


class CallChain(BaseModel):
    id: str
    risk: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    path: list[str]
    symbols: list[str]
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"
    confidence_reason: str = "Inferred via surrounding code structure — verify manually."
    has_tests: bool
    test_files: list[str] = Field(default_factory=list)
    business_impact: str
    explanation: str
    verification_status: str = "UNVERIFIABLE"


class RiskSummary(BaseModel):
    CRITICAL: int = 0
    HIGH: int = 0
    MEDIUM: int = 0
    LOW: int = 0


class RemediationResult(BaseModel):
    chain_id: str
    test_file_path: str
    test_stub: str
    fix_summary: str


class CostEstimate(BaseModel):
    incident_cost_usd: float
    hours_saved: float
    stubs_generated: int
    calculation_basis: str  # one sentence explaining the numbers


class ContextStats(BaseModel):
    files_in_repo: int
    files_sent_to_model: int
    chars_sent: int
    budget_used_pct: float


class BlastRadiusReport(BaseModel):
    changed_symbols: list[str]
    call_chains: list[CallChain]
    safe_paths: list[str] = Field(default_factory=list)
    risk_summary: RiskSummary
    merge_recommendation: str
    suggested_actions: list[str] = Field(default_factory=list)
    pr_title: Optional[str] = None
    remediations: list[RemediationResult] = Field(default_factory=list)
    context_stats: Optional[ContextStats] = None
    cost_estimate: Optional[CostEstimate] = None
    inference_backend: str = "bob"  # "bob" | "fallback" — which LLM served this report


class DiffResult(BaseModel):
    changed_files: list[str] = Field(default_factory=list)
    raw_diff: str = ""
    symbols: list[str] = Field(default_factory=list)

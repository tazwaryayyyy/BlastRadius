from pydantic import BaseModel, Field
from typing import Literal, Optional


class AnalyzeRequest(BaseModel):
    diff: str
    repo_path: str = "demo_repo"
    pr_title: Optional[str] = None
    stream: bool = False


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


class RiskSummary(BaseModel):
    CRITICAL: int = 0
    HIGH: int = 0
    MEDIUM: int = 0
    LOW: int = 0


class BlastRadiusReport(BaseModel):
    changed_symbols: list[str]
    call_chains: list[CallChain]
    safe_paths: list[str] = Field(default_factory=list)
    risk_summary: RiskSummary
    merge_recommendation: str
    suggested_actions: list[str] = Field(default_factory=list)
    pr_title: Optional[str] = None


class DiffResult(BaseModel):
    changed_files: list[str] = Field(default_factory=list)
    raw_diff: str = ""
    symbols: list[str] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    label: str
    risk: str
    is_changed: bool = False
    has_tests: bool = True
    chain_count: int = 0


class GraphEdge(BaseModel):
    source: str
    target: str
    risk: str

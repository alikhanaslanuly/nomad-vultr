from typing import Literal
from pydantic import BaseModel, Field

Verdict = Literal["SAFE_OBSERVED", "SUSPICIOUS", "MALICIOUS", "ERROR"]
Profile = Literal["dev-laptop", "ci", "future-date"]
Tier = Literal["standard", "burn"]


class JobCreate(BaseModel):
    input_type: Literal["paste", "zip", "npm"]
    content: str | None = None
    filename: str = "install.sh"
    ref: str | None = None
    claim: str | None = None
    profiles: list[Profile] = Field(default_factory=lambda: ["dev-laptop", "ci"])
    tier: Tier = "standard"
    invite_code: str | None = None


class JobStatus(BaseModel):
    job_id: str
    status: str
    stage: str
    verdict: Verdict | None = None
    risk_score: int = 0
    tier: Tier = "standard"
    created_at: str
    finished_at: str | None = None


class CodeRef(BaseModel):
    file: str
    line_start: int
    line_end: int


class FindingOut(BaseModel):
    id: str
    severity: Literal["info", "warn", "alert"]
    rule: str = ""
    claim: str = ""
    observed: str = ""
    evidence_event_ids: list[str] = Field(default_factory=list)
    code_ref: CodeRef | None = None


class RunOut(BaseModel):
    run_id: str
    profile: str
    outcome: str
    duration_ms: int = 0
    event_count: int = 0


class Report(BaseModel):
    job_id: str
    verdict: Verdict
    risk_score: int
    confidence: Literal["low", "medium", "high"]
    headline: str
    claim: dict
    behavior_summary: str
    findings: list[FindingOut]
    runs: list[RunOut]
    recommendations: list[str]
    limitations: list[str]
    receipt_id: str | None = None
    tier: Tier
    llm: dict


class LLMHypothesis(BaseModel):
    id: str
    text: str


class LLMExperiment(BaseModel):
    profile: Profile
    focus: str


class LLMHarnessFile(BaseModel):
    path: str
    content: str


class PlannerOutput(BaseModel):
    hypotheses: list[LLMHypothesis]
    experiments: list[LLMExperiment]
    harness: dict  # {"files": [...], "entrypoint": [...], "notes": "..."}
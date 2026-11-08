import os
from typing import Literal, List, Dict, Any, Optional

try:
    from pydantic import BaseModel, Field

    class FileSpec(BaseModel):
        path: str
        content_b64: str

    class LimitsSpec(BaseModel):
        cpu: float = 1.0
        mem_mb: int = 512
        pids: int = 128
        timeout_s: int = 30
        disk_mb: int = 128
        stdout_kb: int = 256

    class NetworkSpec(BaseModel):
        mode: Literal["none", "honeynet", "fetch-allowlist"] = "honeynet"
        allowlist: List[str] = Field(default_factory=list)

    class FetchSpec(BaseModel):
        type: Optional[Literal["npm"]] = None
        ref: Optional[str] = None

    class RunManifest(BaseModel):
        run_id: str
        profile: Literal["dev-laptop", "ci", "future-date"] = "dev-laptop"
        image: str = "airlock-sandbox:node-py"
        files: List[FileSpec] = Field(default_factory=list)
        entrypoint: List[str]
        env: Dict[str, str] = Field(default_factory=dict)
        limits: LimitsSpec = Field(default_factory=LimitsSpec)
        network: NetworkSpec = Field(default_factory=NetworkSpec)
        canary_set: str = "default"
        fetch: Optional[FetchSpec] = None

    class HealthResponse(BaseModel):
        ok: bool = True
        image_digest: str = "sha256:airlock-node-py-v1"
        runtime: Literal["runsc", "runc"] = "runsc"
        observer: Literal["gvisor", "strace"] = "gvisor"

    class RunSummary(BaseModel):
        outcome: Literal["completed", "timeout", "killed", "error"]
        exit_code: int
        duration_ms: int
        events_sha256: str
        artifacts: List[str] = Field(default_factory=lambda: ["stdout.txt", "stderr.txt"])

except ImportError:
    from dataclasses import dataclass, field

    @dataclass
    class FileSpec:
        path: str
        content_b64: str

    @dataclass
    class LimitsSpec:
        cpu: float = 1.0
        mem_mb: int = 512
        pids: int = 128
        timeout_s: int = 30
        disk_mb: int = 128
        stdout_kb: int = 256

    @dataclass
    class NetworkSpec:
        mode: str = "honeynet"
        allowlist: List[str] = field(default_factory=list)

    @dataclass
    class FetchSpec:
        type: Optional[str] = None
        ref: Optional[str] = None

    @dataclass
    class RunManifest:
        run_id: str
        entrypoint: List[str]
        profile: str = "dev-laptop"
        image: str = "airlock-sandbox:node-py"
        files: List[FileSpec] = field(default_factory=list)
        env: Dict[str, str] = field(default_factory=dict)
        limits: LimitsSpec = field(default_factory=LimitsSpec)
        network: NetworkSpec = field(default_factory=NetworkSpec)
        canary_set: str = "default"
        fetch: Optional[FetchSpec] = None

    @dataclass
    class HealthResponse:
        ok: bool = True
        image_digest: str = "sha256:airlock-node-py-v1"
        runtime: str = "runsc"
        observer: str = "gvisor"

    @dataclass
    class RunSummary:
        outcome: str
        exit_code: int
        duration_ms: int
        events_sha256: str
        artifacts: List[str] = field(default_factory=lambda: ["stdout.txt", "stderr.txt"])

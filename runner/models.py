from typing import Literal

from pydantic import BaseModel, Field


class FileSpec(BaseModel):
    path: str
    content_b64: str


class LimitsSpec(BaseModel):
    cpu: float = Field(default=1.0, ge=0.1, le=4)
    mem_mb: int = Field(default=512, ge=32, le=2048)
    pids: int = Field(default=128, ge=8, le=512)
    timeout_s: int = Field(default=30, ge=1, le=120)
    disk_mb: int = Field(default=128, ge=8, le=256)
    stdout_kb: int = Field(default=256, ge=1, le=1024)


class NetworkSpec(BaseModel):
    mode: Literal["none", "honeynet", "fetch-allowlist"] = "honeynet"
    allowlist: list[str] = Field(default_factory=list)


class FetchSpec(BaseModel):
    type: Literal["npm"] | None = None
    ref: str | None = None


class RunManifest(BaseModel):
    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    profile: Literal["dev-laptop", "ci", "future-date"] = "dev-laptop"
    image: str = "airlock-sandbox:node-py"
    files: list[FileSpec] = Field(default_factory=list, max_length=130)
    entrypoint: list[str] = Field(min_length=1, max_length=32)
    env: dict[str, str] = Field(default_factory=dict)
    limits: LimitsSpec = Field(default_factory=LimitsSpec)
    network: NetworkSpec = Field(default_factory=NetworkSpec)
    canary_set: str = "default"
    fetch: FetchSpec | None = None


class HealthResponse(BaseModel):
    ok: bool
    image_digest: str | None = None
    runtime: str | None = None
    observer: str | None = None
    observer_verified: bool = False
    honeynet_verified: bool = False
    mode: Literal["live"] = "live"
    error: str | None = None


class RunSummary(BaseModel):
    outcome: Literal["completed", "timeout", "killed", "error"]
    exit_code: int
    duration_ms: int
    events_sha256: str
    stdout_sha256: str = ""
    image_digest: str = ""
    observation_complete: bool = False
    artifacts: list[str] = Field(default_factory=lambda: ["stdout.txt", "stderr.txt"])

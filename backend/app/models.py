import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:22]}"


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    id:            Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("job"))
    owner:         Mapped[str] = mapped_column(String, default="anon")
    input_type:    Mapped[str] = mapped_column(String)
    input_ref:     Mapped[str] = mapped_column(Text, default="")
    claim_text:    Mapped[str] = mapped_column(Text, default="")
    claim_source:  Mapped[str] = mapped_column(String, default="user")
    profiles:      Mapped[list] = mapped_column(JSON, default=list)
    isolation_tier:Mapped[str] = mapped_column(String, default="standard")
    status:        Mapped[str] = mapped_column(String, default="queued")
    stage:         Mapped[str] = mapped_column(String, default="")
    verdict:       Mapped[str | None] = mapped_column(String, nullable=True)
    risk_score:    Mapped[int] = mapped_column(Integer, default=0)
    created_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at:   Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    llm_model:     Mapped[str] = mapped_column(String, default="")
    llm_tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    llm_tokens_out:Mapped[int] = mapped_column(Integer, default=0)


class Run(Base):
    __tablename__ = "runs"
    id:           Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("run"))
    job_id:       Mapped[str] = mapped_column(String, ForeignKey("jobs.id"), index=True)
    profile:      Mapped[str] = mapped_column(String)
    container_id: Mapped[str] = mapped_column(String, default="")
    started_at:   Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at:     Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exit_code:    Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome:      Mapped[str] = mapped_column(String, default="")
    limits_json:  Mapped[dict] = mapped_column(JSON, default=dict)
    event_count:  Mapped[int] = mapped_column(Integer, default=0)
    duration_ms:  Mapped[int] = mapped_column(Integer, default=0)
    events_sha256:Mapped[str] = mapped_column(String, default="")


class Event(Base):
    __tablename__ = "events"
    id:       Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("evt"))
    job_id:   Mapped[str] = mapped_column(String, ForeignKey("jobs.id"), index=True)
    run_id:   Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    seq:      Mapped[int] = mapped_column(Integer, index=True)
    ts:       Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    kind:     Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String, default="info")
    observer: Mapped[str] = mapped_column(String, default="")
    source:   Mapped[str] = mapped_column(String, default="host")
    detail:   Mapped[dict] = mapped_column(JSON, default=dict)


class AgentStep(Base):
    __tablename__ = "agent_steps"
    id:          Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("step"))
    job_id:      Mapped[str] = mapped_column(String, ForeignKey("jobs.id"), index=True)
    step_no:     Mapped[int] = mapped_column(Integer)
    role:        Mapped[str] = mapped_column(String)  # planner|explainer
    prompt_hash: Mapped[str] = mapped_column(String, default="")
    response_json: Mapped[dict] = mapped_column(JSON, default=dict)
    tokens_in:   Mapped[int] = mapped_column(Integer, default=0)
    tokens_out:  Mapped[int] = mapped_column(Integer, default=0)


class Finding(Base):
    __tablename__ = "findings"
    id:               Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("f"))
    job_id:           Mapped[str] = mapped_column(String, ForeignKey("jobs.id"), index=True)
    severity:         Mapped[str] = mapped_column(String)
    rule:             Mapped[str] = mapped_column(String, default="")
    claim:            Mapped[str] = mapped_column(Text, default="")
    observed:         Mapped[str] = mapped_column(Text, default="")
    evidence_event_ids:Mapped[list] = mapped_column(JSON, default=list)
    code_ref:         Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Receipt(Base):
    __tablename__ = "receipts"
    id:           Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("rcp"))
    job_id:       Mapped[str] = mapped_column(String, ForeignKey("jobs.id"), index=True)
    manifest_json:Mapped[dict] = mapped_column(JSON, default=dict)
    chain_hash:   Mapped[str] = mapped_column(String)
    signature:    Mapped[str] = mapped_column(String)
    verified_at:  Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verify_result:Mapped[dict | None] = mapped_column(JSON, nullable=True)
"""Typed observable contracts for the Phase 3B single-Agent runtime."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from procurement_agent.tools.models import ToolCallRecord


ResponseOutcome = Literal["ANSWERED", "CLARIFICATION_REQUIRED", "INSUFFICIENT_EVIDENCE"]
OrchestrationVersion = Literal["baseline", "guardrails_v1"]
RequirementsVersion = Literal["requirements_v2", "requirements_v2_1"]


class RequestRequirementsV2(BaseModel):
    """Small, model-declared semantic preflight contract without hidden reasoning."""

    model_config = ConfigDict(extra="forbid")

    decision_definition: Literal["SUFFICIENT", "MISSING_REQUIRED_CRITERIA", "AMBIGUOUS_ENTITY", "MISSING_REQUIRED_SCOPE"]
    clarification_question: str | None = None
    policy_support_requirement: Literal["NONE", "STATUS_ONLY", "EXPLAINABLE_POLICY_EVIDENCE"]


class ModelPreflight(BaseModel):
    """Observable result of the same-model preflight request."""

    model_config = ConfigDict(extra="forbid")

    request_requirements: RequestRequirementsV2
    usage: dict[str, Any] = Field(default_factory=dict)
    served_model: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)


class GuardrailEvent(BaseModel):
    """Observable deterministic guardrail state, without model reasoning."""

    model_config = ConfigDict(extra="forbid")

    event_type: Literal["EVIDENCE_COMPLETENESS_GUARD"]
    triggered: bool
    remediation_attempt: int = Field(ge=1)
    reason_code: Literal["MISSING_REQUIRED_POLICY_EVIDENCE"]


class AgentCitation(BaseModel):
    """A model citation selector; trusted metadata is materialized after validation."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str | None = Field(default=None, description="For Retrieval evidence, provide the exact returned chunk_id. The runtime materializes citation metadata from that trusted ID.")
    document_id: str | None = None
    title: str | None = None
    version: str | None = None
    section: str | None = None
    page: int | None = Field(default=None, ge=1)


class AgentFinalResponse(BaseModel):
    """User-facing structured answer produced after the bounded tool loop."""

    model_config = ConfigDict(extra="forbid")

    response_outcome: ResponseOutcome
    answer: str = Field(min_length=1)
    citations: list[AgentCitation] = Field(default_factory=list)
    tool_call_ids: list[str] = Field(default_factory=list)
    evidence_summary: str = ""
    limitations: list[str] = Field(default_factory=list)


class ModelToolCall(BaseModel):
    """An observable function request; no hidden model reasoning is retained."""

    model_config = ConfigDict(extra="forbid")

    call_id: str
    tool_name: str
    arguments: dict[str, Any]


class ModelTurn(BaseModel):
    """One model response, either tool requests or a validated final response."""

    model_config = ConfigDict(extra="forbid")

    assistant_content: str | None = None
    tool_calls: list[ModelToolCall] = Field(default_factory=list)
    final_response: AgentFinalResponse | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    served_model: str | None = None


class ModelDiagnostic(BaseModel):
    """Sanitized development diagnostic, never a provider request or secret."""

    model_config = ConfigDict(extra="forbid")

    stage: str
    exception_class: str
    message: str


class CitationValidationRecord(BaseModel):
    """Safe observable result for each model-provided citation selector."""

    model_config = ConfigDict(extra="forbid")

    model_citation: AgentCitation
    outcome: Literal["MATERIALIZED_FROM_CHUNK_ID", "MATCHED_RUN_EVIDENCE", "REJECTED"]
    reason: str


class EvidenceReference(BaseModel):
    """Citation metadata actually emitted by Retrieval or Compliance during a run."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["retrieval", "compliance"]
    tool_call_id: str
    chunk_id: str | None = None
    document_id: str
    title: str
    version: str
    section: str
    page: int


class AgentRunTrace(BaseModel):
    """Framework-neutral run trace used by CLI and deterministic evaluation."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    case_id: str | None = None
    model: str
    prompt_version: str
    orchestration_version: OrchestrationVersion
    requirements_version: RequirementsVersion
    user_query: str
    resolved_target_date: date | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: float | None = None
    preflight_model_requests: int = 0
    preflight_duration_ms: float | None = None
    model_turn_count: int = 0
    tool_call_records: list[ToolCallRecord] = Field(default_factory=list)
    tool_names: list[str] = Field(default_factory=list)
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    final_response: AgentFinalResponse | None = None
    termination_reason: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    model_diagnostics: list[ModelDiagnostic] = Field(default_factory=list)
    citation_validation: list[CitationValidationRecord] = Field(default_factory=list)
    request_requirements: RequestRequirementsV2 | None = None
    guardrail_events: list[GuardrailEvent] = Field(default_factory=list)
    evidence_remediation_count: int = 0


class AgentConfig(BaseModel):
    """Small, explicit execution limits for one single-request Agent run."""

    model_config = ConfigDict(extra="forbid")

    max_model_turns: int = Field(default=7, ge=1, le=12)
    max_tool_calls: int = Field(default=10, ge=1, le=20)
    max_identical_tool_calls: int = Field(default=2, ge=1, le=5)
    prompt_version: Literal["agent_v1", "agent_v2"] = "agent_v1"
    orchestration_version: OrchestrationVersion = "baseline"
    requirements_version: RequirementsVersion = "requirements_v2"

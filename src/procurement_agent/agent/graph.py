"""One explicit bounded LangGraph loop over the four Phase 3A tool interfaces."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from time import perf_counter
from typing import Any, Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from procurement_agent.agent.model_adapter import ModelAdapter, ModelAdapterError
from procurement_agent.agent.models import AgentCitation, AgentConfig, AgentFinalResponse, AgentRunTrace, CitationValidationRecord, EvidenceReference, GuardrailEvent, ModelDiagnostic, ModelPreflight, ModelToolCall, ModelTurn, RequestRequirementsV2
from procurement_agent.agent.prompts import system_prompt
from procurement_agent.agent.tool_schemas import openai_tool_schemas
from procurement_agent.retrieval.policy_retrieval import EVAL_AS_OF_DATE
from procurement_agent.tools.models import ToolCallRecord, ToolError, ToolResponse, json_value
from procurement_agent.tools.registry import TOOL_REGISTRY, ToolRegistry, create_tool_registry


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    original_user_query: str
    resolved_target_date: date | None
    pending_tool_calls: list[ModelToolCall]
    tool_call_records: list[ToolCallRecord]
    evidence_references: list[EvidenceReference]
    repeated_calls: dict[str, int]
    step_count: int
    tool_call_count: int
    final_response: AgentFinalResponse | None
    termination_reason: str | None
    usage: dict[str, Any]
    model_diagnostics: list[ModelDiagnostic]
    citation_validation: list[CitationValidationRecord]
    served_model: str | None
    request_requirements: RequestRequirementsV2 | None
    guardrail_events: list[GuardrailEvent]
    evidence_remediation_count: int


def _compact_for_model(value: Any, *, max_list_items: int = 30, max_text_characters: int = 2_000) -> Any:
    """Bound visible tool context without changing the complete runtime trace/result."""

    if isinstance(value, str):
        return value if len(value) <= max_text_characters else value[:max_text_characters] + "…[truncated]"
    if isinstance(value, list):
        compact = [_compact_for_model(item, max_list_items=max_list_items, max_text_characters=max_text_characters) for item in value[:max_list_items]]
        return compact if len(value) <= max_list_items else compact + [{"context_items_truncated": len(value) - max_list_items}]
    if isinstance(value, dict):
        return {key: _compact_for_model(item, max_list_items=max_list_items, max_text_characters=max_text_characters) for key, item in value.items()}
    return value


def _tool_error_record(call: ModelToolCall, code: str, message: str) -> ToolCallRecord:
    timestamp = datetime.now(timezone.utc)
    return ToolCallRecord(call.call_id, call.tool_name, json_value(call.arguments), timestamp, timestamp, 0.0, False, None, ToolError(code, message))


def _safe_final(outcome: Literal["ANSWERED", "CLARIFICATION_REQUIRED", "INSUFFICIENT_EVIDENCE"], answer: str, limitation: str, tool_call_ids: list[str] | None = None) -> AgentFinalResponse:
    return AgentFinalResponse(response_outcome=outcome, answer=answer, tool_call_ids=tool_call_ids or [], evidence_summary="", limitations=[limitation])


class ProcurementAgent:
    """A single-request LangGraph Agent with finite model/tool-call budgets."""

    def __init__(self, model_adapter: ModelAdapter, *, tool_registry: ToolRegistry | None = None, config: AgentConfig | None = None) -> None:
        self.model_adapter = model_adapter
        self.registry = tool_registry or create_tool_registry()
        self._owns_registry = tool_registry is None
        self.config = config or AgentConfig()
        self._tool_schemas = openai_tool_schemas()
        self._final_schema = AgentFinalResponse.model_json_schema()
        self.graph = self._build_graph()

    def close(self) -> None:
        if self._owns_registry:
            self.registry.close()

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("agent", self._model_node)
        graph.add_node("tools", self._tool_node)
        graph.add_node("validate_final", self._final_validation_node)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", self._route_model_output, {"tools": "tools", "validate_final": "validate_final"})
        graph.add_conditional_edges("tools", self._route_after_tools, {"agent": "agent", "validate_final": "validate_final"})
        graph.add_conditional_edges("validate_final", self._route_final_validation, {"agent": "agent", "end": END})
        return graph.compile()

    def run(self, user_query: str, *, case_id: str | None = None, target_date: date | None = None) -> AgentRunTrace:
        if not user_query.strip():
            raise ValueError("user_query must not be empty")
        started_at, started_clock = datetime.now(timezone.utc), perf_counter()
        preflight_executed = self.config.orchestration_version == "guardrails_v1"
        preflight_error: ModelDiagnostic | None = None
        try:
            preflight = self._run_preflight(user_query)
        except ModelAdapterError as error:
            preflight, preflight_error = None, error.diagnostic
        requirements = preflight.request_requirements if preflight is not None else None
        usage = {"request_count": int(preflight_executed), "preflight_turns": [preflight.usage] if preflight is not None and preflight_executed else [], "turns": []}
        if requirements is not None and requirements.decision_definition != "SUFFICIENT":
            ended_at = datetime.now(timezone.utc)
            return AgentRunTrace(
                run_id=str(uuid4()), case_id=case_id, model=preflight.served_model or self.model_adapter.model_name, prompt_version=self.config.prompt_version,
                orchestration_version=self.config.orchestration_version, requirements_version=self.config.requirements_version, user_query=user_query, resolved_target_date=target_date, started_at=started_at, ended_at=ended_at,
                duration_ms=round((perf_counter() - started_clock) * 1000, 3), preflight_model_requests=int(preflight_executed), preflight_duration_ms=preflight.duration_ms,
                final_response=_safe_final("CLARIFICATION_REQUIRED", requirements.clarification_question or "Please clarify the decision criterion needed for this request.", "DECISION_CRITERION_UNDEFINED"),
                usage=usage, request_requirements=requirements,
            )
        if preflight is None:
            ended_at = datetime.now(timezone.utc)
            return AgentRunTrace(
                run_id=str(uuid4()), case_id=case_id, model=self.model_adapter.model_name, prompt_version=self.config.prompt_version,
                orchestration_version=self.config.orchestration_version, requirements_version=self.config.requirements_version, user_query=user_query, resolved_target_date=target_date, started_at=started_at, ended_at=ended_at,
                duration_ms=round((perf_counter() - started_clock) * 1000, 3), preflight_model_requests=int(preflight_executed),
                final_response=_safe_final("INSUFFICIENT_EVIDENCE", "The analysis could not be started because the request classification was unavailable.", "PREFLIGHT_EXECUTION_ERROR"),
                termination_reason="PREFLIGHT_EXECUTION_ERROR", usage=usage, model_diagnostics=[preflight_error] if preflight_error is not None else [],
            )
        result = self.graph.invoke({
            "messages": [{"role": "system", "content": system_prompt(self.config.prompt_version)}, {"role": "user", "content": user_query}],
            "original_user_query": user_query,
            "resolved_target_date": target_date,
            "pending_tool_calls": [],
            "tool_call_records": [],
            "evidence_references": [],
            "repeated_calls": {},
            "step_count": 0,
            "tool_call_count": 0,
            "usage": usage,
            "model_diagnostics": [],
            "citation_validation": [],
            "served_model": None,
            "request_requirements": requirements,
            "guardrail_events": [],
            "evidence_remediation_count": 0,
        })
        ended_at = datetime.now(timezone.utc)
        return AgentRunTrace(
            run_id=str(uuid4()), case_id=case_id, model=result.get("served_model") or preflight.served_model or self.model_adapter.model_name, prompt_version=self.config.prompt_version,
            orchestration_version=self.config.orchestration_version,
            requirements_version=self.config.requirements_version,
            user_query=user_query, resolved_target_date=result.get("resolved_target_date"), started_at=started_at, ended_at=ended_at,
            duration_ms=round((perf_counter() - started_clock) * 1000, 3), preflight_model_requests=int(preflight_executed), preflight_duration_ms=preflight.duration_ms if preflight_executed else None, model_turn_count=result.get("step_count", 0),
            tool_call_records=result.get("tool_call_records", []), tool_names=[record.tool_name for record in result.get("tool_call_records", [])],
            evidence_references=result.get("evidence_references", []), final_response=result.get("final_response"),
            termination_reason=result.get("termination_reason"), usage=result.get("usage", {}), model_diagnostics=result.get("model_diagnostics", []),
            citation_validation=result.get("citation_validation", []), request_requirements=result.get("request_requirements"),
            guardrail_events=result.get("guardrail_events", []), evidence_remediation_count=result.get("evidence_remediation_count", 0),
        )

    def _run_preflight(self, user_query: str) -> ModelPreflight | None:
        if self.config.orchestration_version == "baseline":
            return ModelPreflight(request_requirements=RequestRequirementsV2(decision_definition="SUFFICIENT", clarification_question=None, policy_support_requirement="NONE"))
        return self.model_adapter.preflight(user_query, self.config.requirements_version)

    def _model_node(self, state: AgentState) -> dict[str, Any]:
        if state["step_count"] >= self.config.max_model_turns:
            return {"final_response": _safe_final("INSUFFICIENT_EVIDENCE", "I could not complete a grounded analysis within the configured execution limit.", "MODEL_TURN_LIMIT"), "termination_reason": "MODEL_TURN_LIMIT", "pending_tool_calls": []}
        try:
            turn = self.model_adapter.complete(state["messages"], self._tool_schemas, self._final_schema)
        except ModelAdapterError as error:
            return {"final_response": _safe_final("INSUFFICIENT_EVIDENCE", "The analysis could not be completed because the model response was unavailable or invalid.", "MODEL_EXECUTION_ERROR"), "termination_reason": "MODEL_EXECUTION_ERROR", "pending_tool_calls": [], "model_diagnostics": [*state.get("model_diagnostics", []), error.diagnostic]}

        assistant = {"role": "assistant", "content": turn.assistant_content or ""}
        if turn.tool_calls:
            assistant["tool_calls"] = [{"id": call.call_id, "type": "function", "function": {"name": call.tool_name, "arguments": json.dumps(call.arguments, sort_keys=True)}} for call in turn.tool_calls]
        usage = dict(state["usage"])
        usage["request_count"] = usage.get("request_count", 0) + 1
        usage["turns"] = [*usage.get("turns", []), turn.usage]
        return {"messages": [*state["messages"], assistant], "pending_tool_calls": turn.tool_calls, "final_response": turn.final_response, "step_count": state["step_count"] + 1, "usage": usage, "served_model": turn.served_model or state.get("served_model")}

    @staticmethod
    def _route_model_output(state: AgentState) -> Literal["tools", "validate_final"]:
        return "tools" if state.get("pending_tool_calls") and state.get("final_response") is None else "validate_final"

    @staticmethod
    def _route_after_tools(state: AgentState) -> Literal["agent", "validate_final"]:
        return "validate_final" if state.get("final_response") is not None else "agent"

    @staticmethod
    def _route_final_validation(state: AgentState) -> Literal["agent", "end"]:
        return "agent" if state.get("final_response") is None and state.get("termination_reason") is None else "end"

    def _tool_node(self, state: AgentState) -> dict[str, Any]:
        records = list(state["tool_call_records"])
        evidence = list(state["evidence_references"])
        messages = list(state["messages"])
        repeated = dict(state["repeated_calls"])
        tool_count = state["tool_call_count"]
        resolved_target_date = state.get("resolved_target_date")
        final: AgentFinalResponse | None = None
        termination: str | None = None

        for requested in state["pending_tool_calls"]:
            if tool_count >= self.config.max_tool_calls:
                records.append(_tool_error_record(requested, "TOOL_CALL_LIMIT", "Configured total tool-call limit reached."))
                final = _safe_final("INSUFFICIENT_EVIDENCE", "I could not complete a grounded analysis within the configured tool-call limit.", "TOOL_CALL_LIMIT", [record.call_id for record in records])
                termination = "TOOL_CALL_LIMIT"
                break
            normalized = f"{requested.tool_name}:{json.dumps(requested.arguments, sort_keys=True, separators=(',', ':'))}"
            repeated[normalized] = repeated.get(normalized, 0) + 1
            if repeated[normalized] > self.config.max_identical_tool_calls:
                records.append(_tool_error_record(requested, "REPEATED_TOOL_CALL_BLOCKED", "Identical tool call was blocked by the repetition limit."))
                final = _safe_final("INSUFFICIENT_EVIDENCE", "I could not complete a grounded analysis because repeated identical tool calls were blocked.", "REPEATED_TOOL_CALL_LIMIT", [record.call_id for record in records])
                termination = "REPEATED_TOOL_CALL_LIMIT"
                break
            if requested.tool_name not in TOOL_REGISTRY:
                response_payload = {"error": {"code": "UNKNOWN_TOOL", "message": "Requested tool is not available."}}
                records.append(_tool_error_record(requested, "UNKNOWN_TOOL", "Requested tool is not part of the accepted registry."))
            else:
                response: ToolResponse[Any] = self.registry.execute(requested.tool_name, requested.arguments)
                records.append(response.to_call_record(requested.arguments))
                response_payload = response.to_dict()
                if response.metadata.success and response.result is not None:
                    evidence.extend(self._evidence_from_response(response, response.metadata.call_id))
                    if requested.tool_name == "retrieve_procurement_policy":
                        resolved_target_date = response.result.target_date
            messages.append({"role": "tool", "tool_call_id": requested.call_id, "content": json.dumps(_compact_for_model(response_payload), sort_keys=True)})
            tool_count += 1

        return {"messages": messages, "pending_tool_calls": [], "tool_call_records": records, "evidence_references": evidence, "repeated_calls": repeated, "tool_call_count": tool_count, "resolved_target_date": resolved_target_date, "final_response": final, "termination_reason": termination}

    @staticmethod
    def _evidence_from_response(response: ToolResponse[Any], tool_call_id: str) -> list[EvidenceReference]:
        result = response.result
        if response.metadata.tool_name == "retrieve_procurement_policy" and result is not None:
            return [EvidenceReference(source="retrieval", tool_call_id=tool_call_id, chunk_id=item.chunk_id, document_id=item.document_id, title=item.title, version=item.version, section=item.section_label, page=item.page_number) for item in result.evidence]
        if response.metadata.tool_name == "check_policy_compliance" and result is not None:
            return [EvidenceReference(source="compliance", tool_call_id=tool_call_id, document_id=rule.provenance.source_document_id, title=rule.provenance.title, version=rule.provenance.version, section=rule.provenance.section, page=rule.provenance.page) for rule in result.rule_results if rule.applicable]
        return []

    def _final_validation_node(self, state: AgentState) -> dict[str, Any]:
        requirements = state.get("request_requirements")
        records = state.get("tool_call_records", [])
        inventory = state.get("evidence_references", [])
        compliance_used = any(record.tool_name == "check_policy_compliance" and record.success for record in records)
        retrieval_evidence_exists = any(reference.source == "retrieval" for reference in inventory)
        if (
            self.config.orchestration_version == "guardrails_v1"
            and requirements is not None
            and requirements.policy_support_requirement == "EXPLAINABLE_POLICY_EVIDENCE"
            and compliance_used
            and not retrieval_evidence_exists
        ):
            remediation_count = state.get("evidence_remediation_count", 0)
            event = GuardrailEvent(event_type="EVIDENCE_COMPLETENESS_GUARD", triggered=True, remediation_attempt=max(remediation_count, 1), reason_code="MISSING_REQUIRED_POLICY_EVIDENCE")
            if remediation_count == 0:
                return {
                    "messages": [*state["messages"], {"role": "system", "content": "The requested answer requires explainable policy evidence. Compliance results exist, but applicable PDF policy evidence has not yet been retrieved. Retrieve the applicable policy evidence before finalizing and cite returned run-local evidence identifiers."}],
                    "final_response": None,
                    "guardrail_events": [*state.get("guardrail_events", []), event],
                    "evidence_remediation_count": 1,
                }
            return {
                "final_response": _safe_final("INSUFFICIENT_EVIDENCE", "Required explainable policy evidence was not obtained after the bounded remediation opportunity.", "POLICY_EVIDENCE_GUARD_UNSATISFIED", [record.call_id for record in records]),
                "termination_reason": "POLICY_EVIDENCE_GUARD_UNSATISFIED",
                "guardrail_events": [*state.get("guardrail_events", []), event],
                "evidence_remediation_count": remediation_count,
            }
        final = state.get("final_response") or _safe_final("INSUFFICIENT_EVIDENCE", "I did not receive a complete final response from the model.", "MISSING_FINAL_RESPONSE")
        record_ids = {record.call_id for record in records}
        valid_citations: list[AgentCitation] = []
        validation_records: list[CitationValidationRecord] = []
        for citation in final.citations:
            reference = next((item for item in inventory if citation.chunk_id and item.chunk_id == citation.chunk_id), None)
            if reference is not None:
                valid_citations.append(self._materialize_citation(reference))
                validation_records.append(CitationValidationRecord(model_citation=citation, outcome="MATERIALIZED_FROM_CHUNK_ID", reason="CHUNK_ID_FOUND_IN_RUN_EVIDENCE"))
            elif any(self._citation_matches(citation, item) for item in inventory):
                reference = next(item for item in inventory if self._citation_matches(citation, item))
                valid_citations.append(self._materialize_citation(reference))
                validation_records.append(CitationValidationRecord(model_citation=citation, outcome="MATCHED_RUN_EVIDENCE", reason="COMPLETE_METADATA_MATCHED_RUN_EVIDENCE"))
            else:
                reason = "CHUNK_ID_NOT_IN_RUN_EVIDENCE" if citation.chunk_id else "NO_COMPLETE_MATCH_IN_RUN_EVIDENCE"
                validation_records.append(CitationValidationRecord(model_citation=citation, outcome="REJECTED", reason=reason))
        valid_tool_call_ids = [call_id for call_id in final.tool_call_ids if call_id in record_ids]
        limitations = list(final.limitations)
        rejected_count = sum(record.outcome == "REJECTED" for record in validation_records)
        if rejected_count:
            limitations.append(f"INVALID_CITATIONS_REJECTED:{rejected_count}")
        if len(valid_tool_call_ids) != len(final.tool_call_ids):
            limitations.append("INVALID_TOOL_CALL_IDS_REJECTED")
        termination = state.get("termination_reason")
        if rejected_count and termination is None:
            termination = "INVALID_CITATION_REJECTED"
        return {"final_response": final.model_copy(update={"citations": valid_citations, "tool_call_ids": valid_tool_call_ids, "limitations": limitations}), "termination_reason": termination, "citation_validation": validation_records}

    @staticmethod
    def _citation_matches(citation: AgentCitation, reference: EvidenceReference) -> bool:
        return (
            citation.document_id == reference.document_id and citation.title == reference.title and citation.version == reference.version
            and citation.section == reference.section and citation.page == reference.page
            and (citation.chunk_id is None or citation.chunk_id == reference.chunk_id)
        )

    @staticmethod
    def _materialize_citation(reference: EvidenceReference) -> AgentCitation:
        return AgentCitation(chunk_id=reference.chunk_id, document_id=reference.document_id, title=reference.title, version=reference.version, section=reference.section, page=reference.page)

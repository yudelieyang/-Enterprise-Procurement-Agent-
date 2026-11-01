from __future__ import annotations

import json
import os
from datetime import date

import pytest

from procurement_agent.agent.graph import ProcurementAgent
from procurement_agent.agent.model_adapter import LiveOpenAIModelAdapter, ModelAdapter, ModelAdapterError, ScriptedModelAdapter
from procurement_agent.agent.models import AgentCitation, AgentConfig, AgentFinalResponse, ModelPreflight, ModelToolCall, ModelTurn, RequestRequirementsV2
from procurement_agent.agent.tool_schemas import openai_tool_schemas


def _final(outcome: str = "ANSWERED", *, citations: list[AgentCitation] | None = None, tool_call_ids: list[str] | None = None) -> ModelTurn:
    return ModelTurn(final_response=AgentFinalResponse(response_outcome=outcome, answer="Grounded scripted response.", citations=citations or [], tool_call_ids=tool_call_ids or [], evidence_summary="Scripted evidence."))


def test_single_graph_executes_compliance_then_retrieval_and_keeps_real_evidence_citation():
    citation = AgentCitation(chunk_id="APPROVAL_MATRIX_2026_1:2026.1:p2:s4_2:c1", document_id="APPROVAL_MATRIX_2026_1", title="Approval Authority Matrix", version="2026.1", section="Section 4.2", page=2)
    adapter = ScriptedModelAdapter([
        ModelTurn(tool_calls=[ModelToolCall(call_id="model-compliance", tool_name="check_policy_compliance", arguments={"po_number": "PO-2026-1842"})]),
        ModelTurn(tool_calls=[ModelToolCall(call_id="model-retrieval", tool_name="retrieve_procurement_policy", arguments={"query": "approval requirements above 50000", "target_date": "2026-06-30"})]),
        _final(citations=[citation]),
    ])
    agent = ProcurementAgent(adapter)
    try:
        trace = agent.run("Is PO-2026-1842 compliant with supporting policy evidence?", case_id="UNIT-CANONICAL")
    finally:
        agent.close()
    assert trace.tool_names == ["check_policy_compliance", "retrieve_procurement_policy"]
    assert trace.final_response.response_outcome == "ANSWERED"
    assert trace.final_response.citations == [citation]
    assert trace.citation_validation[-1].outcome == "MATERIALIZED_FROM_CHUNK_ID"
    assert trace.model_turn_count == 3
    assert trace.termination_reason is None


def test_clarification_requires_no_tool_call_and_insufficient_evidence_can_follow_empty_retrieval():
    clarification = ProcurementAgent(ScriptedModelAdapter([_final("CLARIFICATION_REQUIRED")]))
    try:
        trace = clarification.run("Is Acme our preferred supplier?")
    finally:
        clarification.close()
    assert not trace.tool_call_records
    assert trace.final_response.response_outcome == "CLARIFICATION_REQUIRED"

    unsupported = ProcurementAgent(ScriptedModelAdapter([
        ModelTurn(tool_calls=[ModelToolCall(call_id="model-2024", tool_name="retrieve_procurement_policy", arguments={"query": "2024 contract policy", "target_date": "2024-06-30"})]),
        _final("INSUFFICIENT_EVIDENCE"),
    ]))
    try:
        trace = unsupported.run("What did the 2024 contract policy require?")
    finally:
        unsupported.close()
    assert trace.tool_names == ["retrieve_procurement_policy"]
    assert trace.final_response.response_outcome == "INSUFFICIENT_EVIDENCE"
    assert not trace.evidence_references
    assert trace.resolved_target_date == date(2024, 6, 30)


def test_sql_safety_error_is_observable_and_invalid_citations_or_call_ids_are_rejected():
    fake_citation = AgentCitation(chunk_id="not-a-real-chunk", document_id="NOT_REAL", title="Invented", version="2099", section="Section 1", page=1)
    agent = ProcurementAgent(ScriptedModelAdapter([
        ModelTurn(tool_calls=[ModelToolCall(call_id="model-sql", tool_name="query_procurement_database", arguments={"sql": "DELETE FROM suppliers"})]),
        _final(citations=[fake_citation], tool_call_ids=["not-a-runtime-call"]),
    ]))
    try:
        trace = agent.run("Delete all suppliers.")
    finally:
        agent.close()
    assert trace.tool_call_records[0].error.code == "SQL_SAFETY_VIOLATION"
    assert trace.final_response.citations == []
    assert trace.final_response.tool_call_ids == []
    assert "INVALID_CITATIONS_REJECTED:1" in trace.final_response.limitations
    assert "INVALID_TOOL_CALL_IDS_REJECTED" in trace.final_response.limitations
    assert trace.termination_reason == "INVALID_CITATION_REJECTED"
    assert trace.citation_validation[0].reason == "CHUNK_ID_NOT_IN_RUN_EVIDENCE"


def test_citation_validation_materializes_trusted_chunk_ids_and_rejects_unmatched_metadata():
    known_chunk = "APPROVAL_MATRIX_2026_1:2026.1:p2:s4_2:c1"

    def run(citation: AgentCitation):
        agent = ProcurementAgent(ScriptedModelAdapter([
            ModelTurn(tool_calls=[ModelToolCall(call_id="model-retrieval", tool_name="retrieve_procurement_policy", arguments={"query": "approval requirements above 50000", "target_date": "2026-06-30"})]),
            _final(citations=[citation]),
        ]))
        try:
            return agent.run("What approvals are required above $50,000?")
        finally:
            agent.close()

    materialized = run(AgentCitation(chunk_id=known_chunk))
    assert materialized.final_response.citations == [AgentCitation(chunk_id=known_chunk, document_id="APPROVAL_MATRIX_2026_1", title="Approval Authority Matrix", version="2026.1", section="Section 4.2", page=2)]
    assert materialized.citation_validation[0].outcome == "MATERIALIZED_FROM_CHUNK_ID"

    incorrect_reconstruction = run(AgentCitation(chunk_id=known_chunk, document_id="WRONG_DOCUMENT", title="Wrong title", version="2099.1", section="Section 99", page=99))
    assert incorrect_reconstruction.final_response.citations == materialized.final_response.citations
    assert incorrect_reconstruction.citation_validation[0].outcome == "MATERIALIZED_FROM_CHUNK_ID"

    wrong_document = run(AgentCitation(document_id="WRONG_DOCUMENT", title="Approval Authority Matrix", version="2026.1", section="Section 4.2", page=2))
    wrong_version = run(AgentCitation(document_id="APPROVAL_MATRIX_2026_1", title="Approval Authority Matrix", version="2099.1", section="Section 4.2", page=2))
    wrong_page = run(AgentCitation(document_id="APPROVAL_MATRIX_2026_1", title="Approval Authority Matrix", version="2026.1", section="Section 4.2", page=99))
    assert not wrong_document.final_response.citations and wrong_document.citation_validation[0].reason == "NO_COMPLETE_MATCH_IN_RUN_EVIDENCE"
    assert not wrong_version.final_response.citations and wrong_version.citation_validation[0].reason == "NO_COMPLETE_MATCH_IN_RUN_EVIDENCE"
    assert not wrong_page.final_response.citations and wrong_page.citation_validation[0].reason == "NO_COMPLETE_MATCH_IN_RUN_EVIDENCE"


def test_unknown_and_repeated_tool_calls_are_bounded_without_provider_calls():
    repeated = ModelToolCall(call_id="same", tool_name="query_procurement_database", arguments={"sql": "SELECT 1 AS value"})
    agent = ProcurementAgent(ScriptedModelAdapter([
        ModelTurn(tool_calls=[repeated]), ModelTurn(tool_calls=[repeated]), ModelTurn(tool_calls=[repeated]),
    ]), config=AgentConfig(max_identical_tool_calls=2))
    try:
        trace = agent.run("Run the same query repeatedly.")
    finally:
        agent.close()
    assert len(trace.tool_call_records) == 3
    assert trace.tool_call_records[-1].error.code == "REPEATED_TOOL_CALL_BLOCKED"
    assert trace.final_response.response_outcome == "INSUFFICIENT_EVIDENCE"
    assert trace.termination_reason == "REPEATED_TOOL_CALL_LIMIT"

    unknown = ProcurementAgent(ScriptedModelAdapter([
        ModelTurn(tool_calls=[ModelToolCall(call_id="unknown", tool_name="invent_tool", arguments={})]), _final(),
    ]))
    try:
        trace = unknown.run("Use an unavailable tool.")
    finally:
        unknown.close()
    assert trace.tool_call_records[0].error.code == "UNKNOWN_TOOL"


def test_model_turn_and_total_tool_call_limits_are_deterministic():
    call = ModelToolCall(call_id="one", tool_name="query_procurement_database", arguments={"sql": "SELECT 1 AS value"})
    agent = ProcurementAgent(ScriptedModelAdapter([ModelTurn(tool_calls=[call])]), config=AgentConfig(max_model_turns=1))
    try:
        trace = agent.run("Count something.")
    finally:
        agent.close()
    assert trace.tool_names == ["query_procurement_database"]
    assert trace.termination_reason == "MODEL_TURN_LIMIT"
    assert trace.final_response.response_outcome == "INSUFFICIENT_EVIDENCE"

    agent = ProcurementAgent(ScriptedModelAdapter([
        ModelTurn(tool_calls=[
            ModelToolCall(call_id="first", tool_name="query_procurement_database", arguments={"sql": "SELECT 1 AS value"}),
            ModelToolCall(call_id="second", tool_name="query_procurement_database", arguments={"sql": "SELECT 2 AS value"}),
        ]),
    ]), config=AgentConfig(max_tool_calls=1))
    try:
        trace = agent.run("Run two queries.")
    finally:
        agent.close()
    assert trace.tool_call_records[-1].error.code == "TOOL_CALL_LIMIT"
    assert trace.termination_reason == "TOOL_CALL_LIMIT"


def test_compliance_rule_provenance_is_a_valid_citation_source():
    citation = AgentCitation(document_id="APPROVAL_MATRIX_2026_1", title="Approval Authority Matrix", version="2026.1", section="Section 4.2", page=2)
    agent = ProcurementAgent(ScriptedModelAdapter([
        ModelTurn(tool_calls=[ModelToolCall(call_id="model-compliance", tool_name="check_policy_compliance", arguments={"po_number": "PO-2026-1842"})]),
        _final(citations=[citation]),
    ]))
    try:
        trace = agent.run("Is PO-2026-1842 compliant?")
    finally:
        agent.close()
    assert trace.final_response.citations == [citation]
    assert trace.evidence_references[0].source == "compliance"


def test_openai_function_schemas_are_strict_complete_and_deterministic():
    schemas = openai_tool_schemas()
    assert [schema["function"]["name"] for schema in schemas] == [
        "query_procurement_database", "retrieve_procurement_policy", "analyze_procurement_data", "check_policy_compliance",
    ]
    for schema in schemas:
        function = schema["function"]
        parameters = function["parameters"]
        assert function["strict"] is True
        assert parameters["additionalProperties"] is False
        assert parameters["required"] == list(parameters["properties"])
    assert openai_tool_schemas() == schemas


def test_model_failure_trace_keeps_a_sanitized_stage_diagnostic():
    class FailingAdapter(ModelAdapter):
        model_name = "failing-test-model"

        def complete(self, messages, tools, final_response_schema):
            raise ModelAdapterError("OpenAI model request failed", stage="openai_chat_completions_parse", cause=ValueError("API_KEY=sk-test-secret schema rejected"))

    agent = ProcurementAgent(FailingAdapter())
    try:
        trace = agent.run("Test a model failure.")
    finally:
        agent.close()
    assert trace.termination_reason == "MODEL_EXECUTION_ERROR"
    assert trace.model_diagnostics[0].stage == "openai_chat_completions_parse"
    assert trace.model_diagnostics[0].exception_class == "ValueError"
    assert "sk-test-secret" not in trace.model_diagnostics[0].message
    assert "[redacted]" in trace.model_diagnostics[0].message


def _run_v2_scripted(turns: list[ModelTurn], query: str):
    adapter = ScriptedModelAdapter(turns)
    agent = ProcurementAgent(adapter, config=AgentConfig(prompt_version="agent_v2"))
    try:
        trace = agent.run(query)
    finally:
        agent.close()
    return trace, adapter


def test_agent_v2_scripted_structured_ranking_uses_sql_only():
    trace, adapter = _run_v2_scripted([
        ModelTurn(tool_calls=[ModelToolCall(call_id="rank", tool_name="query_procurement_database", arguments={"sql": "SELECT supplier_code FROM suppliers ORDER BY supplier_code LIMIT 1", "max_rows": 1})]),
        _final(),
    ], "Which supplier had the highest spend in the requested period?")
    assert trace.prompt_version == "agent_v2"
    assert trace.tool_names == ["query_procurement_database"]
    assert "Choose the smallest sufficient tool set" in adapter.requests[0]["messages"][0]["content"]


def test_agent_v2_scripted_supported_growth_analysis_uses_analytics_only():
    trace, _ = _run_v2_scripted([
        ModelTurn(tool_calls=[ModelToolCall(call_id="growth", tool_name="analyze_procurement_data", arguments={
            "operation": "supplier_spend_growth", "supplier_code": "SUP-042", "comparison_start": "2025-01-01", "comparison_end": "2025-06-30", "current_start": "2026-01-01", "current_end": "2026-06-30",
        })]),
        _final(),
    ], "How did the supplier's H1 spend grow year over year?")
    assert trace.tool_names == ["analyze_procurement_data"]
    assert trace.final_response.response_outcome == "ANSWERED"


def test_agent_v2_scripted_undefined_decision_criterion_clarifies_without_tools():
    trace, _ = _run_v2_scripted([_final("CLARIFICATION_REQUIRED")], "Is this supplier preferred?")
    assert trace.tool_names == []
    assert trace.final_response.response_outcome == "CLARIFICATION_REQUIRED"


def test_agent_v2_scripted_explainable_compliance_uses_compliance_and_retrieval():
    citation = AgentCitation(chunk_id="APPROVAL_MATRIX_2026_1:2026.1:p2:s4_2:c1")
    trace, _ = _run_v2_scripted([
        ModelTurn(tool_calls=[ModelToolCall(call_id="audit", tool_name="check_policy_compliance", arguments={"po_number": "PO-2026-1842"})]),
        ModelTurn(tool_calls=[ModelToolCall(call_id="policy", tool_name="retrieve_procurement_policy", arguments={"query": "approval requirement for a purchase commitment", "target_date": "2026-06-30", "top_k": 3, "retrieval_mode": "hybrid"})]),
        _final(citations=[citation]),
    ], "Is this purchase order compliant, and what policy evidence supports the answer?")
    assert trace.tool_names == ["check_policy_compliance", "retrieve_procurement_policy"]
    assert trace.final_response.citations[0].chunk_id == citation.chunk_id


def test_agent_v2_scripted_policy_explanation_continues_after_compliance_before_finalizing():
    trace, adapter = _run_v2_scripted([
        ModelTurn(tool_calls=[ModelToolCall(call_id="audit", tool_name="check_policy_compliance", arguments={"po_number": "PO-2026-1842"})]),
        ModelTurn(tool_calls=[ModelToolCall(call_id="policy", tool_name="retrieve_procurement_policy", arguments={"query": "contract and approval policy basis", "target_date": "2026-06-30", "top_k": 3, "retrieval_mode": "hybrid"})]),
        _final(),
    ], "Audit this order and explain the applicable policy basis.")
    assert trace.model_turn_count == 3
    assert trace.tool_names == ["check_policy_compliance", "retrieve_procurement_policy"]
    assert len(adapter.requests) == 3


def _requirements(decision_definition: str = "SUFFICIENT", policy_support_requirement: str = "NONE", clarification_question: str | None = None) -> RequestRequirementsV2:
    return RequestRequirementsV2(decision_definition=decision_definition, clarification_question=clarification_question, policy_support_requirement=policy_support_requirement)


def _guarded_agent(turns: list[ModelTurn], requirements: RequestRequirementsV2, requirements_version: str = "requirements_v2"):
    adapter = ScriptedModelAdapter(turns, preflights=[ModelPreflight(request_requirements=requirements, usage={"total_tokens": 11}, duration_ms=1.25)])
    return ProcurementAgent(adapter, config=AgentConfig(prompt_version="agent_v2", orchestration_version="guardrails_v1", requirements_version=requirements_version)), adapter


def test_guardrails_v1_clarification_preflight_returns_without_business_tools():
    requirements = _requirements("MISSING_REQUIRED_CRITERIA", clarification_question="Which category, region or business unit, and definition of preferred supplier should I use?")
    agent, adapter = _guarded_agent([], requirements)
    try:
        trace = agent.run("Is Acme our preferred supplier?")
    finally:
        agent.close()
    assert trace.final_response.response_outcome == "CLARIFICATION_REQUIRED"
    assert trace.final_response.answer == requirements.clarification_question
    assert trace.tool_names == [] and adapter.requests == []
    assert trace.usage["request_count"] == 1
    assert trace.preflight_model_requests == 1
    assert trace.requirements_version == "requirements_v2"


def test_guardrails_v1_passes_requirements_v2_1_to_preflight_without_changing_runtime_mapping():
    requirements = _requirements("MISSING_REQUIRED_CRITERIA", clarification_question="Which definition of preferred supplier should I use?")
    agent, adapter = _guarded_agent([], requirements, "requirements_v2_1")
    try:
        trace = agent.run("Is Acme our preferred supplier?")
    finally:
        agent.close()
    assert adapter.preflight_versions == ["requirements_v2_1"]
    assert trace.requirements_version == "requirements_v2_1"
    assert trace.final_response.response_outcome == "CLARIFICATION_REQUIRED"


def test_task_035_explicit_historical_scope_retrieves_and_abstains_without_evidence():
    adapter = ScriptedModelAdapter([
        ModelTurn(tool_calls=[ModelToolCall(call_id="historical-policy", tool_name="retrieve_procurement_policy", arguments={"query": "What did the 2024 contract policy require?", "target_date": "2024-06-30"})]),
        _final("INSUFFICIENT_EVIDENCE"),
    ], preflights=[_requirements(policy_support_requirement="EXPLAINABLE_POLICY_EVIDENCE")])
    agent = ProcurementAgent(adapter, config=AgentConfig(prompt_version="agent_v2", orchestration_version="guardrails_v1", requirements_version="requirements_v2_1"))
    try:
        trace = agent.run("What did the 2024 contract policy require?", case_id="TASK-035")
    finally:
        agent.close()
    assert trace.request_requirements.decision_definition == "SUFFICIENT"
    assert trace.request_requirements.policy_support_requirement == "EXPLAINABLE_POLICY_EVIDENCE"
    assert trace.tool_names == ["retrieve_procurement_policy"]
    tool_message = next(message for message in adapter.requests[1]["messages"] if message["role"] == "tool")
    assert json.loads(tool_message["content"])["result"]["status"] == "NO_APPLICABLE_POLICY_EVIDENCE"
    assert trace.final_response.response_outcome == "INSUFFICIENT_EVIDENCE"
    assert trace.final_response.citations == []
    assert not trace.guardrail_events and trace.evidence_remediation_count == 0


@pytest.mark.parametrize("decision_definition", ["MISSING_REQUIRED_CRITERIA", "AMBIGUOUS_ENTITY", "MISSING_REQUIRED_SCOPE"])
def test_guardrails_v1_all_insufficient_definition_states_clarify_without_tools(decision_definition: str):
    agent, adapter = _guarded_agent([], _requirements(decision_definition, clarification_question="Please provide the missing decision input."))
    try:
        trace = agent.run("Incomplete procurement request.")
    finally:
        agent.close()
    assert trace.final_response.response_outcome == "CLARIFICATION_REQUIRED"
    assert trace.tool_names == [] and adapter.requests == []


def test_guardrails_v1_preserves_normal_sql_analytics_and_simple_compliance_paths():
    cases = [
        ("SQL", ModelTurn(tool_calls=[ModelToolCall(call_id="sql", tool_name="query_procurement_database", arguments={"sql": "SELECT 1 AS value"})]), ["query_procurement_database"]),
        ("Analytics", ModelTurn(tool_calls=[ModelToolCall(call_id="analytics", tool_name="analyze_procurement_data", arguments={"operation": "supplier_spend_growth", "supplier_code": "SUP-042", "comparison_start": "2025-01-01", "comparison_end": "2025-06-30", "current_start": "2026-01-01", "current_end": "2026-06-30"})]), ["analyze_procurement_data"]),
        ("Compliance", ModelTurn(tool_calls=[ModelToolCall(call_id="compliance", tool_name="check_policy_compliance", arguments={"po_number": "PO-2026-1842"})]), ["check_policy_compliance"]),
    ]
    for label, call, expected in cases:
        policy = "STATUS_ONLY" if label == "Compliance" else "NONE"
        agent, _ = _guarded_agent([call, _final()], _requirements(policy_support_requirement=policy))
        try:
            trace = agent.run(f"{label} request")
        finally:
            agent.close()
        assert trace.tool_names == expected
        assert trace.final_response.response_outcome == "ANSWERED"
        assert trace.guardrail_events == []


def test_guardrails_v1_blocks_explainable_compliance_then_permits_retrieval_remediation():
    citation = AgentCitation(chunk_id="APPROVAL_MATRIX_2026_1:2026.1:p2:s4_2:c1")
    agent, adapter = _guarded_agent([
        ModelTurn(tool_calls=[ModelToolCall(call_id="compliance", tool_name="check_policy_compliance", arguments={"po_number": "PO-2026-1842"})]),
        _final(),
        ModelTurn(tool_calls=[ModelToolCall(call_id="retrieval", tool_name="retrieve_procurement_policy", arguments={"query": "approval requirements above 50000", "target_date": "2026-06-30"})]),
        _final(citations=[citation]),
    ], _requirements(policy_support_requirement="EXPLAINABLE_POLICY_EVIDENCE"))
    try:
        trace = agent.run("Audit the order with policy evidence.")
    finally:
        agent.close()
    assert trace.tool_names == ["check_policy_compliance", "retrieve_procurement_policy"]
    assert trace.final_response.response_outcome == "ANSWERED"
    assert trace.evidence_remediation_count == 1
    assert trace.guardrail_events[0].reason_code == "MISSING_REQUIRED_POLICY_EVIDENCE"
    assert "applicable PDF policy evidence" in adapter.requests[2]["messages"][-1]["content"]
    assert trace.prompt_version == "agent_v2" and trace.orchestration_version == "guardrails_v1"


def test_guardrails_v1_terminates_after_one_missing_evidence_remediation_even_when_retrieval_has_no_evidence():
    agent, _ = _guarded_agent([
        ModelTurn(tool_calls=[ModelToolCall(call_id="compliance", tool_name="check_policy_compliance", arguments={"po_number": "PO-2026-1842"})]),
        _final(),
        ModelTurn(tool_calls=[ModelToolCall(call_id="empty-retrieval", tool_name="retrieve_procurement_policy", arguments={"query": "2024 contract policy", "target_date": "2024-06-30"})]),
        _final(),
    ], _requirements(policy_support_requirement="EXPLAINABLE_POLICY_EVIDENCE"))
    try:
        trace = agent.run("Audit the order with policy evidence.")
    finally:
        agent.close()
    assert trace.tool_names == ["check_policy_compliance", "retrieve_procurement_policy"]
    assert not [item for item in trace.evidence_references if item.source == "retrieval"]
    assert trace.final_response.response_outcome == "INSUFFICIENT_EVIDENCE"
    assert trace.termination_reason == "POLICY_EVIDENCE_GUARD_UNSATISFIED"
    assert trace.evidence_remediation_count == 1
    assert len(trace.guardrail_events) == 2


def test_guardrails_v1_does_not_require_compliance_for_rag_only_policy_evidence():
    citation = AgentCitation(chunk_id="APPROVAL_MATRIX_2026_1:2026.1:p2:s4_2:c1")
    agent, _ = _guarded_agent([
        ModelTurn(tool_calls=[ModelToolCall(call_id="retrieval", tool_name="retrieve_procurement_policy", arguments={"query": "approval requirements above 50000", "target_date": "2026-06-30"})]),
        _final(citations=[citation]),
    ], _requirements(policy_support_requirement="EXPLAINABLE_POLICY_EVIDENCE"))
    try:
        trace = agent.run("What policy requires approval above $50,000?")
    finally:
        agent.close()
    assert trace.tool_names == ["retrieve_procurement_policy"]
    assert trace.final_response.response_outcome == "ANSWERED"
    assert trace.guardrail_events == []


@pytest.mark.live_agent
def test_live_adapter_smoke_is_opt_in():
    if not os.getenv("RUN_LIVE_AGENT_TESTS"):
        pytest.skip("Set RUN_LIVE_AGENT_TESTS=1 with OPENAI_API_KEY to spend credits on live Agent verification.")
    agent = ProcurementAgent(LiveOpenAIModelAdapter())
    try:
        trace = agent.run("What approvals are required for a purchase above $50,000?")
    finally:
        agent.close()
    assert trace.final_response is not None

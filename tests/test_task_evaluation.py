from __future__ import annotations

from pathlib import Path

import pytest

from procurement_agent.data.generator import DEFAULT_SEED, write_dataset
from procurement_agent.database.connection import sqlite_engine
from procurement_agent.database.loader import build_database
from procurement_agent.evaluation.tasks import Citation, GoldenTask, GoldenTaskValidationError, ToolTrace, evaluate_citations, evaluate_trace, load_golden_tasks, task_benchmark_summary, validate_golden_tasks


def _task(case_id: str) -> GoldenTask:
    return next(task for task in load_golden_tasks() if task.case_id == case_id)


@pytest.fixture()
def database(tmp_path: Path):
    source_dir = tmp_path / "generated"
    write_dataset(source_dir, DEFAULT_SEED)
    database_path = tmp_path / "procurement.sqlite"
    build_database(database_path, source_dir)
    engine = sqlite_engine(database_path)
    yield engine
    engine.dispose()


def test_golden_task_dataset_validates_against_current_components(database):
    report = validate_golden_tasks(database)
    assert report["validation"] == "passed"
    assert report["case_count"] == 38
    assert report["by_task_type"] == {
        "rag_only": 6, "reliability": 6, "sql_analytics": 6, "sql_analytics_rag_compliance": 2,
        "sql_compliance": 5, "sql_only": 7, "sql_rag_compliance": 6,
    }
    assert report["response_outcomes"] == {"ANSWERED": 33, "CLARIFICATION_REQUIRED": 2, "INSUFFICIENT_EVIDENCE": 3}


def test_tool_trace_metrics_distinguish_required_optional_and_unnecessary_calls():
    canonical = _task("TASK-025")
    correct = evaluate_trace(canonical, ToolTrace.from_tools("check_policy_compliance", "retrieve_procurement_policy"))
    assert correct.trajectory_success and correct.required_tool_coverage == correct.tool_selection_precision == 1.0

    missing = evaluate_trace(canonical, ToolTrace.from_tools("check_policy_compliance"))
    assert missing.required_tool_coverage == pytest.approx(1 / 2)
    assert "MISSING_REQUIRED_TOOL" in missing.failures

    excessive = evaluate_trace(canonical, ToolTrace.from_tools("check_policy_compliance", "analyze_procurement_data", "retrieve_procurement_policy"))
    assert excessive.tool_selection_precision == pytest.approx(2 / 3)
    assert excessive.unnecessary_tool_call_rate == pytest.approx(1 / 3)
    assert "UNNECESSARY_TOOL_CALL" in excessive.failures

    historical = _task("TASK-037")
    optional_route = evaluate_trace(historical, ToolTrace.from_tools("retrieve_procurement_policy", "check_policy_compliance"))
    assert optional_route.trajectory_success and optional_route.tool_selection_precision == 1.0


def test_ordering_clarification_and_citation_contracts():
    ordered = GoldenTask.from_dict({
        "case_id": "TOY-ORDER", "scenario_family": "unit_test", "user_query": "x", "task_type": "unit_test",
        "required_tools": ["query_procurement_database", "analyze_procurement_data"], "optional_tools": [], "unnecessary_tools": [],
        "allowed_trajectories": [["query_procurement_database", "analyze_procurement_data"]],
        "ordering_constraints": [["query_procurement_database", "analyze_procurement_data"]], "expected_response_outcome": "ANSWERED",
    })
    analytics_first = evaluate_trace(ordered, ToolTrace.from_tools("analyze_procurement_data", "query_procurement_database"))
    assert not analytics_first.trajectory_success and "ORDERING_CONSTRAINT_VIOLATION" in analytics_first.failures

    clarification = evaluate_trace(_task("TASK-033"), ToolTrace.from_tools())
    assert clarification.trajectory_success
    premature_tool = evaluate_trace(_task("TASK-033"), ToolTrace.from_tools("query_procurement_database"))
    assert "UNNECESSARY_TOOL_CALL" in premature_tool.failures

    citations = evaluate_citations(_task("TASK-025"), (
        Citation("APPROVAL_MATRIX_2026_1:2026.1:p2:s4_2:c1"),
        Citation("CONTRACT_COMPLIANCE_2026_1:2026.1:p2:s4_1:c1"),
    ))
    assert citations.passed and citations.citation_correctness == citations.evidence_coverage == 1.0

    outdated = evaluate_citations(_task("TASK-025"), (Citation("APPROVAL_MATRIX_2025_1:2025.1:p2:s4_2:c1"),))
    assert not outdated.passed and outdated.citation_correctness == 0.0


def test_validator_rejects_scope_and_tool_contract_drift(database):
    raw = dict(_task("TASK-001").raw)
    raw["user_query"] = "What invoice payments are overdue?"
    with pytest.raises(GoldenTaskValidationError, match="invoice/payment"):
        validate_golden_tasks(database, [GoldenTask.from_dict(raw)])

    summary = task_benchmark_summary(load_golden_tasks())
    assert "TASK-030" in summary["portfolio_priority_cases"]
    assert summary["compliance_statuses"] == {"FAIL": 6, "PASS": 4, "REVIEW": 4}

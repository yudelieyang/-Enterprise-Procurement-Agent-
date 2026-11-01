from __future__ import annotations

import json
from pathlib import Path

from procurement_agent.analytics.analytics import analyze_spend_growth
from procurement_agent.compliance.engine import ComplianceEngine
from procurement_agent.data.generator import DEFAULT_SEED, write_dataset
from procurement_agent.database.connection import sqlite_engine
from procurement_agent.database.loader import build_database
from procurement_agent.database.query import execute_readonly_query
from procurement_agent.evaluation.tasks import TOOL_VOCABULARY, load_golden_tasks
from procurement_agent.retrieval.policy_retrieval import DenseEncoder, PolicyRetriever, build_policy_chunks
from procurement_agent.tools.analytics_tool import AnalyticsTool
from procurement_agent.tools.compliance_tool import ComplianceTool
from procurement_agent.tools.policy_tool import PolicyRetrievalTool
from procurement_agent.tools.registry import TOOL_REGISTRY, ToolRegistry
from procurement_agent.tools.sql_tool import SqlTool


def _database(tmp_path: Path):
    source_dir = tmp_path / "generated"
    write_dataset(source_dir, DEFAULT_SEED)
    path = tmp_path / "procurement.sqlite"
    build_database(path, source_dir)
    return sqlite_engine(path)


def test_registry_has_exactly_the_frozen_logical_tool_names(tmp_path: Path):
    engine = _database(tmp_path)
    try:
        registry = ToolRegistry({"query_procurement_database": SqlTool(engine), "retrieve_procurement_policy": PolicyRetrievalTool(PolicyRetriever(build_policy_chunks(), DenseEncoder())), "analyze_procurement_data": AnalyticsTool(engine), "check_policy_compliance": ComplianceTool(ComplianceEngine(engine))}, engine)
        assert set(TOOL_REGISTRY) == TOOL_VOCABULARY == set(registry.tools)
        assert all(definition["name"] == name and definition["description"] for name, definition in registry.definitions().items())
        assert registry.execute("query_procurement_database", {"sql": "SELECT 1 AS value"}).result.rows == [{"value": 1}]
    finally:
        engine.dispose()


def test_sql_and_analytics_wrappers_preserve_component_results_and_normalize_errors(tmp_path: Path):
    engine = _database(tmp_path)
    try:
        sql = SqlTool(engine)
        response = sql.execute({"sql": "SELECT COUNT(*) AS count FROM suppliers"})
        assert response.metadata.success and response.result.rows == execute_readonly_query(engine, "SELECT COUNT(*) AS count FROM suppliers").rows
        call_record = response.to_call_record({"sql": "SELECT COUNT(*) AS count FROM suppliers"})
        assert call_record.call_id == response.metadata.call_id and call_record.result_summary == {"result_type": "SqlToolResult"}
        assert not sql.execute({"sql": "DELETE FROM suppliers"}).metadata.success
        assert sql.execute({"sql": "DELETE FROM suppliers"}).error.code == "SQL_SAFETY_VIOLATION"

        analytics = AnalyticsTool(engine)
        args = {"operation": "supplier_spend_growth", "supplier_code": "SUP-042", "comparison_start": "2025-01-01", "comparison_end": "2025-06-30", "current_start": "2026-01-01", "current_end": "2026-06-30"}
        response = analytics.execute(args)
        direct = analyze_spend_growth(engine, "SUP-042", response.result.result.comparison_period_start, response.result.result.comparison_period_end, response.result.result.current_period_start, response.result.result.current_period_end)
        assert response.metadata.success and response.result.result == direct
        assert analytics.execute({"operation": "execute_python"}).error.code == "VALIDATION_ERROR"
        assert analytics.execute({"operation": "supplier_spend_growth", "supplier_code": "SUP-042", "comparison_start": "2025-06-30", "comparison_end": "2025-01-01", "current_start": "2026-01-01", "current_end": "2026-06-30"}).error.code == "VALIDATION_ERROR"
        assert analytics.execute({"operation": "price_outliers", "item_code": "PRICE-OFF-001", "unit_of_measure": "BOX"}).metadata.success
    finally:
        engine.dispose()


def test_policy_and_compliance_wrappers_preserve_evidence_and_statuses(tmp_path: Path):
    engine = _database(tmp_path)
    try:
        retriever = PolicyRetriever(build_policy_chunks(), DenseEncoder())
        policy = PolicyRetrievalTool(retriever)
        response = policy.execute({"query": "What approvals are required for a purchase above $50,000?", "target_date": "2026-06-30"})
        direct = retriever.retrieve("What approvals are required for a purchase above $50,000?", "2026-06-30", 5, "hybrid")
        assert response.metadata.success and [item.chunk_id for item in response.result.evidence] == [item.chunk_id for item in direct]
        assert policy.execute({"query": "2024 contract policy", "target_date": "2024-06-30"}).result.status == "NO_APPLICABLE_POLICY_EVIDENCE"

        compliance_engine = ComplianceEngine(engine)
        compliance = ComplianceTool(compliance_engine)
        response = compliance.execute({"po_number": "PO-2026-1842"})
        assert response.metadata.success and response.result == compliance_engine.audit("PO-2026-1842")
        assert compliance.execute({"po_number": "PO-2026-9999"}).error.code == "ENTITY_NOT_FOUND"
        assert json.dumps(response.to_dict())
    finally:
        engine.dispose()


def test_golden_tasks_match_the_domain_level_tool_interfaces():
    tasks = load_golden_tasks()
    assert all(set(task.required_tools) <= TOOL_VOCABULARY for task in tasks)
    assert all("query_procurement_database" not in task.required_tools for task in tasks if task.task_type in {"sql_analytics", "sql_compliance", "sql_rag_compliance", "sql_analytics_rag_compliance", "reliability"} and task.case_id not in {"TASK-038"})
    assert next(task for task in tasks if task.case_id == "TASK-025").required_tools == ("retrieve_procurement_policy", "check_policy_compliance")
    assert next(task for task in tasks if task.case_id == "TASK-030").required_tools == ("analyze_procurement_data", "retrieve_procurement_policy", "check_policy_compliance")

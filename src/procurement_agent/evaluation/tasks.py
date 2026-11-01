"""Framework-neutral contracts for pre-Agent golden task evaluation."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from procurement_agent.analytics.analytics import analyze_price_outliers, analyze_single_source_risk, analyze_spend_growth
from procurement_agent.compliance.engine import ComplianceEngine
from procurement_agent.database.query import execute_readonly_query
from procurement_agent.database.reference_queries import (
    CANONICAL_PO_FACTS,
    HIGH_VALUE_APPROVAL_FACTS,
    INDIRECT_PARETO,
    OFF_CONTRACT_FACTS,
    PAST_SIX_MONTHS_BY_BUSINESS_UNIT,
    SUP_042_H1_SPEND,
    TOP_Q2_IT_SUPPLIERS,
)
from procurement_agent.retrieval.policy_retrieval import load_chunk_registry


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = PROJECT_ROOT / "evals" / "tasks" / "golden_tasks.json"
EVAL_AS_OF_DATE = date(2026, 6, 30)
TOOL_VOCABULARY = frozenset({
    "query_procurement_database",
    "retrieve_procurement_policy",
    "analyze_procurement_data",
    "check_policy_compliance",
})
RESPONSE_OUTCOMES = frozenset({"ANSWERED", "CLARIFICATION_REQUIRED", "INSUFFICIENT_EVIDENCE"})


class GoldenTaskValidationError(ValueError):
    """Raised when task data no longer matches the deterministic project facts."""


@dataclass(frozen=True)
class GoldenTask:
    case_id: str
    scenario_family: str
    user_query: str
    task_type: str
    required_tools: tuple[str, ...]
    optional_tools: tuple[str, ...]
    unnecessary_tools: tuple[str, ...]
    allowed_trajectories: tuple[tuple[str, ...], ...]
    ordering_constraints: tuple[tuple[str, str], ...]
    expected_response_outcome: str
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GoldenTask":
        return cls(
            case_id=data["case_id"], scenario_family=data["scenario_family"], user_query=data["user_query"],
            task_type=data["task_type"], required_tools=tuple(data.get("required_tools", [])),
            optional_tools=tuple(data.get("optional_tools", [])),
            unnecessary_tools=tuple(data.get("unnecessary_tools", [])),
            allowed_trajectories=tuple(tuple(route) for route in data.get("allowed_trajectories", [[]])),
            ordering_constraints=tuple(tuple(pair) for pair in data.get("ordering_constraints", [])),
            expected_response_outcome=data["expected_response_outcome"], raw=data,
        )


@dataclass(frozen=True)
class ToolCall:
    tool_name: str


@dataclass(frozen=True)
class ToolTrace:
    calls: tuple[ToolCall, ...]

    @classmethod
    def from_tools(cls, *tool_names: str) -> "ToolTrace":
        return cls(tuple(ToolCall(tool_name) for tool_name in tool_names))

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(call.tool_name for call in self.calls)


@dataclass(frozen=True)
class Citation:
    chunk_id: str


@dataclass(frozen=True)
class CitationEvaluation:
    citation_correctness: float
    evidence_coverage: float
    passed: bool
    failures: tuple[str, ...]


@dataclass(frozen=True)
class TaskEvaluationResult:
    case_id: str
    tool_selection_precision: float
    tool_selection_recall: float
    required_tool_coverage: float
    unnecessary_tool_call_rate: float
    trajectory_success: bool
    failures: tuple[str, ...]


def load_golden_tasks(path: Path = CASES_PATH) -> list[GoldenTask]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    overrides = dataset.get("tool_interface_overrides", {})
    return [GoldenTask.from_dict(item | overrides.get(item["case_id"], {})) for item in dataset["cases"]]


def _is_subsequence(expected: tuple[str, ...], actual: tuple[str, ...]) -> bool:
    position = 0
    for tool in actual:
        if position < len(expected) and tool == expected[position]:
            position += 1
    return position == len(expected)


def evaluate_trace(task: GoldenTask, trace: ToolTrace) -> TaskEvaluationResult:
    actual = trace.tool_names
    required = set(task.required_tools)
    present = set(actual)
    required_coverage = len(required & present) / len(required) if required else 1.0
    permitted = required | set(task.optional_tools)
    precision = sum(tool in permitted for tool in actual) / len(actual) if actual else 1.0
    unnecessary_rate = sum(tool in task.unnecessary_tools for tool in actual) / len(actual) if actual else 0.0
    order_ok = all(before in actual and after in actual and actual.index(before) < actual.index(after) for before, after in task.ordering_constraints)
    exact = task.raw.get("exact_trajectory", False)
    routes_ok = any(actual == route if exact else _is_subsequence(route, actual) for route in task.allowed_trajectories)
    failures: list[str] = []
    if required_coverage < 1.0:
        failures.append("MISSING_REQUIRED_TOOL")
    if any(tool in task.unnecessary_tools for tool in actual):
        failures.append("UNNECESSARY_TOOL_CALL")
    if any(tool not in TOOL_VOCABULARY for tool in actual):
        failures.append("UNKNOWN_TOOL_CALL")
    if not order_ok:
        failures.append("ORDERING_CONSTRAINT_VIOLATION")
    if not routes_ok:
        failures.append("UNACCEPTABLE_TRAJECTORY")
    return TaskEvaluationResult(
        case_id=task.case_id, tool_selection_precision=precision, tool_selection_recall=required_coverage,
        required_tool_coverage=required_coverage, unnecessary_tool_call_rate=unnecessary_rate,
        trajectory_success=not failures, failures=tuple(failures),
    )


def evaluate_citations(task: GoldenTask, citations: tuple[Citation, ...]) -> CitationEvaluation:
    expected = task.raw.get("expected_policy_evidence", [])
    if not expected:
        return CitationEvaluation(1.0, 1.0, True, ())
    chunks = {chunk.chunk_id: chunk for chunk in load_chunk_registry()}
    valid, covered, failures = 0, 0, []
    target_date = date.fromisoformat(task.raw.get("target_date", EVAL_AS_OF_DATE.isoformat()))
    for citation in citations:
        chunk = chunks.get(citation.chunk_id)
        if chunk is None:
            failures.append(f"UNKNOWN_CHUNK:{citation.chunk_id}")
            continue
        effective = date.fromisoformat(chunk.effective_date)
        expiration = date.fromisoformat(chunk.expiration_date) if chunk.expiration_date else None
        applies = effective <= target_date and (expiration is None or expiration >= target_date)
        if not applies:
            failures.append(f"TEMPORALLY_INVALID_CITATION:{citation.chunk_id}")
            continue
        valid += 1
    for evidence in expected:
        if any(
            (chunk := chunks.get(citation.chunk_id)) is not None
            and chunk.document_id == evidence["document_id"] and chunk.version == evidence["version"]
            and chunk.section_label == evidence["section_label"] and chunk.page_number == evidence["page_number"]
            for citation in citations
        ):
            covered += 1
        else:
            failures.append(f"MISSING_EXPECTED_EVIDENCE:{evidence['document_id']}:{evidence['section_label']}")
    correctness = valid / len(citations) if citations else 0.0
    coverage = covered / len(expected)
    minimum_families = task.raw.get("citation_requirements", {}).get("minimum_distinct_policy_families")
    if minimum_families and len({chunks[citation.chunk_id].document_id for citation in citations if citation.chunk_id in chunks}) < minimum_families:
        failures.append("INSUFFICIENT_CITATION_DIVERSITY")
    return CitationEvaluation(correctness, coverage, not failures, tuple(failures))


def _rows(engine: Engine, query: str) -> list[dict[str, Any]]:
    return execute_readonly_query(engine, query).rows


def _validate_fact_contract(engine: Engine, task: GoldenTask) -> None:
    expected = task.raw.get("expected_facts")
    if not expected:
        return
    contract, values = expected["contract"], expected["values"]
    if contract == "past_six_months_by_business_unit":
        actual = {row["business_unit_id"]: f"{row['spend_usd']:.2f}" for row in _rows(engine, PAST_SIX_MONTHS_BY_BUSINESS_UNIT)}
    elif contract == "top_q2_it_supplier":
        actual = _rows(engine, TOP_Q2_IT_SUPPLIERS)[0]
        actual = {"supplier_id": actual["supplier_id"], "spend_usd": f"{actual['spend_usd']:.2f}"}
    elif contract == "sup_042_h1_spend":
        actual = {row["period"]: f"{row['spend_usd']:.2f}" for row in _rows(engine, SUP_042_H1_SPEND)}
    elif contract == "indirect_pareto_80":
        supplier_ids = []
        for row in _rows(engine, INDIRECT_PARETO):
            supplier_ids.append(row["supplier_id"])
            if Decimal(str(row["cumulative_share"])) >= Decimal("0.80"):
                break
        actual = {"supplier_ids": supplier_ids}
    elif contract == "po_1842_facts":
        row = _rows(engine, CANONICAL_PO_FACTS)[0]
        actual = {"po_number": row["po_number"], "supplier_id": row["supplier_id"], "category_id": row["category_id"], "total_amount_usd": f"{row['total_amount_usd']:.2f}"}
    elif contract == "off_contract_fact":
        requested = values["po_number"]
        row = next(row for row in _rows(engine, OFF_CONTRACT_FACTS) if row["po_number"] == requested)
        actual = {"po_number": row["po_number"], "contract_reference": row["contract_reference"], "contract_id": row["contract_id"]}
    elif contract == "high_value_approval_fact":
        requested = values["po_number"]
        rows = [row for row in _rows(engine, HIGH_VALUE_APPROVAL_FACTS) if row["po_number"] == requested]
        actual = {"po_number": requested, "approval_roles": sorted(row["approver_role"] for row in rows if row["approver_role"])}
    else:
        raise GoldenTaskValidationError(f"{task.case_id}: unknown fact contract {contract}")
    if actual != values:
        raise GoldenTaskValidationError(f"{task.case_id}: expected facts drifted: expected={values}, actual={actual}")


def _validate_analytics(engine: Engine, task: GoldenTask) -> None:
    expected = task.raw.get("expected_analytics")
    if not expected:
        return
    kind = expected["kind"]
    if kind == "spend_growth":
        result = analyze_spend_growth(engine, expected["supplier_id"], date(2025, 1, 1), date(2025, 6, 30), date(2026, 1, 1), date(2026, 6, 30))
        actual = {"comparison_spend": str(result.comparison_spend), "current_spend": str(result.current_spend), "absolute_change": str(result.absolute_change), "percentage_change": str(result.percentage_change), "comparison_po_count": result.comparison_po_count, "current_po_count": result.current_po_count, "comparison_average_po_amount": str(result.comparison_average_po_amount), "current_average_po_amount": str(result.current_average_po_amount), "category_changes": {item.category_id: str(item.absolute_change) for item in result.category_contributions}, "largest_pos": [item.po_number for item in result.largest_current_period_pos]}
    elif kind == "price_outlier":
        group = next(item for item in analyze_price_outliers(engine, expected["item_code"]) if item.unit_of_measure == expected["unit_of_measure"])
        actual = {"analysis_status": group.analysis_status, "outliers": [item.purchase_order_item_id for item in group.outliers]}
    elif kind == "concentration":
        result = analyze_single_source_risk(engine, expected["category_id"], date(2026, 1, 1), date(2026, 6, 30))
        actual = {"top_supplier_id": result.top_supplier_id, "top_supplier_share": str(result.top_supplier_share), "qualified_supplier_count": result.concentration.qualified_supplier_count, "risk_finding": result.risk_finding}
    else:
        raise GoldenTaskValidationError(f"{task.case_id}: unknown analytics kind {kind}")
    wanted = expected["values"]
    if actual != wanted:
        raise GoldenTaskValidationError(f"{task.case_id}: expected analytics drifted: expected={wanted}, actual={actual}")


def _validate_compliance(engine: Engine, task: GoldenTask) -> None:
    expected = task.raw.get("expected_compliance")
    if not expected:
        return
    for expected_result in (expected, *task.raw.get("expected_related_compliance", [])):
        result = ComplianceEngine(engine).audit(expected_result["po_number"])
        actual = {"overall": result.overall_status}
        actual.update({rule.rule_type: rule.status for rule in result.rule_results})
        wanted = {"overall": expected_result["overall"]}
        wanted.update(expected_result.get("rule_statuses", {}))
        if actual != wanted:
            raise GoldenTaskValidationError(f"{task.case_id}: expected compliance drifted: expected={wanted}, actual={actual}")


def _validate_entities(engine: Engine, task: GoldenTask) -> None:
    for table, identifiers in task.raw.get("expected_entities", {}).items():
        primary_key = {"purchase_orders": "po_number", "suppliers": "supplier_id", "categories": "category_id", "business_units": "business_unit_id"}.get(table)
        if primary_key is None:
            raise GoldenTaskValidationError(f"{task.case_id}: unsupported entity table {table}")
        for identifier in identifiers:
            with engine.connect() as connection:
                found = connection.execute(text(f"SELECT 1 FROM {table} WHERE {primary_key} = :identifier"), {"identifier": identifier}).scalar()
            if found is None:
                raise GoldenTaskValidationError(f"{task.case_id}: missing {table} entity {identifier}")


def _validate_policy_evidence(task: GoldenTask) -> None:
    chunks = load_chunk_registry()
    target_date = date.fromisoformat(task.raw.get("target_date", EVAL_AS_OF_DATE.isoformat()))
    for evidence in task.raw.get("expected_policy_evidence", []):
        matches = [chunk for chunk in chunks if chunk.document_id == evidence["document_id"] and chunk.version == evidence["version"] and chunk.section_label == evidence["section_label"] and chunk.page_number == evidence["page_number"]]
        if not matches:
            raise GoldenTaskValidationError(f"{task.case_id}: policy evidence not in chunk registry: {evidence}")
        if not any(date.fromisoformat(chunk.effective_date) <= target_date and (chunk.expiration_date is None or date.fromisoformat(chunk.expiration_date) >= target_date) for chunk in matches):
            raise GoldenTaskValidationError(f"{task.case_id}: policy evidence is temporally invalid: {evidence}")
    absence = task.raw.get("expected_policy_absence")
    if absence:
        applicable = [chunk for chunk in chunks if date.fromisoformat(chunk.effective_date) <= target_date and (chunk.expiration_date is None or date.fromisoformat(chunk.expiration_date) >= target_date)]
        if absence.get("all_policies") and applicable:
            raise GoldenTaskValidationError(f"{task.case_id}: unexpected policy coverage for {target_date}")
        if policy_type := absence.get("policy_type"):
            if any(chunk.policy_type == policy_type for chunk in applicable):
                raise GoldenTaskValidationError(f"{task.case_id}: unexpected {policy_type} coverage for {target_date}")


def validate_golden_tasks(engine: Engine, tasks: list[GoldenTask] | None = None) -> dict[str, Any]:
    tasks = load_golden_tasks() if tasks is None else tasks
    seen: set[str] = set()
    for task in tasks:
        if task.case_id in seen:
            raise GoldenTaskValidationError(f"Duplicate case ID: {task.case_id}")
        seen.add(task.case_id)
        if task.expected_response_outcome not in RESPONSE_OUTCOMES:
            raise GoldenTaskValidationError(f"{task.case_id}: unknown response outcome")
        if "citation_requirements" not in task.raw:
            raise GoldenTaskValidationError(f"{task.case_id}: citation requirements are missing")
        if task.raw.get("expected_policy_evidence") and not task.raw["citation_requirements"].get("required"):
            raise GoldenTaskValidationError(f"{task.case_id}: policy evidence requires citations")
        if task.expected_response_outcome == "CLARIFICATION_REQUIRED" and task.required_tools:
            raise GoldenTaskValidationError(f"{task.case_id}: clarification must happen before required tool use")
        groups = (set(task.required_tools), set(task.optional_tools), set(task.unnecessary_tools))
        if any(tool not in TOOL_VOCABULARY for group in groups for tool in group):
            raise GoldenTaskValidationError(f"{task.case_id}: unknown tool name")
        if any(left & right for index, left in enumerate(groups) for right in groups[index + 1:]):
            raise GoldenTaskValidationError(f"{task.case_id}: tool groups overlap")
        if not task.allowed_trajectories or not all(set(task.required_tools).issubset(route) for route in task.allowed_trajectories):
            raise GoldenTaskValidationError(f"{task.case_id}: required tools are incompatible with allowed trajectories")
        if any(len(pair) != 2 or any(tool not in TOOL_VOCABULARY for tool in pair) for pair in task.ordering_constraints):
            raise GoldenTaskValidationError(f"{task.case_id}: invalid ordering constraint")
        if "invoice" in task.user_query.lower() or "payment" in task.user_query.lower():
            raise GoldenTaskValidationError(f"{task.case_id}: invoice/payment scope is forbidden")
        if task.raw.get("target_date"):
            date.fromisoformat(task.raw["target_date"])
        _validate_entities(engine, task)
        _validate_fact_contract(engine, task)
        _validate_analytics(engine, task)
        _validate_compliance(engine, task)
        _validate_policy_evidence(task)
    return task_benchmark_summary(tasks) | {"validation": "passed"}


def task_benchmark_summary(tasks: list[GoldenTask]) -> dict[str, Any]:
    return {
        "case_count": len(tasks),
        "by_task_type": dict(sorted(Counter(task.task_type for task in tasks).items())),
        "by_required_tool_combination": dict(sorted(Counter(" + ".join(task.required_tools) or "none" for task in tasks).items())),
        "response_outcomes": dict(sorted(Counter(task.expected_response_outcome for task in tasks).items())),
        "compliance_statuses": dict(sorted(Counter(task.raw["expected_compliance"]["overall"] for task in tasks if task.raw.get("expected_compliance")).items())),
        "portfolio_priority_cases": [task.case_id for task in tasks if task.raw.get("portfolio_priority") in {"highest", "high"}],
    }


def summarize_trace_results(results: list[TaskEvaluationResult]) -> dict[str, float]:
    if not results:
        return {"tool_selection_precision": 0.0, "tool_selection_recall": 0.0, "required_tool_coverage": 0.0, "unnecessary_tool_call_rate": 0.0, "trajectory_success_rate": 0.0}
    return {
        "tool_selection_precision": sum(item.tool_selection_precision for item in results) / len(results),
        "tool_selection_recall": sum(item.tool_selection_recall for item in results) / len(results),
        "required_tool_coverage": sum(item.required_tool_coverage for item in results) / len(results),
        "unnecessary_tool_call_rate": sum(item.unnecessary_tool_call_rate for item in results) / len(results),
        "trajectory_success_rate": sum(item.trajectory_success for item in results) / len(results),
    }

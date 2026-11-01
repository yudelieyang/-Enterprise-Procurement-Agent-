from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from procurement_agent.tools.registry import create_tool_registry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = PROJECT_ROOT / "evals" / "results" / "tool_readiness.json"


def _record(case_id: str, response: Any, passed: bool) -> dict[str, Any]:
    return {"case_id": case_id, "tool_name": response.metadata.tool_name, "success": response.metadata.success, "error_code": response.error.code if response.error else None, "passed": passed}


def evaluate_tool_readiness() -> dict[str, Any]:
    registry = create_tool_registry()
    try:
        sql, policy = registry.get("query_procurement_database"), registry.get("retrieve_procurement_policy")
        analytics, compliance = registry.get("analyze_procurement_data"), registry.get("check_policy_compliance")
        records: list[dict[str, Any]] = []

        response = sql.execute({"sql": "SELECT COUNT(*) AS count FROM suppliers"})
        records.append(_record("TOOL-001", response, response.metadata.success and response.result.rows == [{"count": 25}]))
        response = sql.execute({"sql": "DELETE FROM suppliers"})
        records.append(_record("TOOL-002", response, not response.metadata.success and response.error.code == "SQL_SAFETY_VIOLATION"))
        response = sql.execute({"sql": "SELECT FROM suppliers"})
        records.append(_record("TOOL-003", response, not response.metadata.success and response.error.code == "SQL_EXECUTION_ERROR"))

        response = policy.execute({"query": "What approvals are required for a purchase above $50,000?", "target_date": "2026-06-30"})
        records.append(_record("TOOL-004", response, response.metadata.success and any(item.chunk_id == "APPROVAL_MATRIX_2026_1:2026.1:p2:s4_2:c1" for item in response.result.evidence)))
        response = policy.execute({"query": "What did the 2024 contract policy require?", "target_date": "2024-06-30"})
        records.append(_record("TOOL-005", response, response.metadata.success and response.result.status == "NO_APPLICABLE_POLICY_EVIDENCE"))

        growth_args = {"supplier_code": "SUP-042", "comparison_start": "2025-01-01", "comparison_end": "2025-06-30", "current_start": "2026-01-01", "current_end": "2026-06-30"}
        response = analytics.execute({"operation": "supplier_spend_growth", **growth_args})
        records.append(_record("TOOL-006", response, response.metadata.success and str(response.result.result.absolute_change) == "270000.00"))
        response = analytics.execute({"operation": "supplier_spend_drivers", **growth_args})
        records.append(_record("TOOL-007", response, response.metadata.success and [item.po_number for item in response.result.result.largest_current_period_pos] == ["PO-2026-1843", "PO-2026-1842", "PO-2026-1861"]))
        response = analytics.execute({"operation": "price_outliers", "item_code": "PRICE-OFF-001", "unit_of_measure": "EA"})
        records.append(_record("TOOL-008", response, response.metadata.success and [item.purchase_order_item_id for item in response.result.result[0].outliers] == ["PO-2025-1910-L01"]))
        response = analytics.execute({"operation": "price_outliers", "item_code": "PRICE-OFF-001", "unit_of_measure": "BOX"})
        records.append(_record("TOOL-009", response, response.metadata.success and response.result.result[0].analysis_status == "INSUFFICIENT_PEER_GROUP"))
        response = analytics.execute({"operation": "supplier_concentration", "category_code": "CAT-PRO", "start_date": "2026-01-01", "end_date": "2026-06-30"})
        records.append(_record("TOOL-010", response, response.metadata.success and response.result.result.risk_finding))

        for case_id, po_number, expected in (("TOOL-011", "PO-2026-1846", "PASS"), ("TOOL-012", "PO-2026-1842", "FAIL"), ("TOOL-013", "PO-2026-1847", "REVIEW")):
            response = compliance.execute({"po_number": po_number})
            records.append(_record(case_id, response, response.metadata.success and response.result.overall_status == expected))
        response = compliance.execute({"po_number": "PO-2026-9999"})
        records.append(_record("TOOL-014", response, not response.metadata.success and response.error.code == "ENTITY_NOT_FOUND"))
    finally:
        registry.close()
    return {"case_count": len(records), "passed": sum(record["passed"] for record in records), "failed": sum(not record["passed"] for record in records), "records": records}


def main() -> None:
    report = evaluate_tool_readiness()
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

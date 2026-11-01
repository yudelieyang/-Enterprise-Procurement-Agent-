from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from procurement_agent.analytics.analytics import analyze_price_outliers, analyze_single_source_risk, analyze_spend_growth


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = PROJECT_ROOT / "evals" / "analytics_cases.json"
RESULTS_PATH = PROJECT_ROOT / "evals" / "results" / "analytics_metrics.json"
H1_2025 = (date(2025, 1, 1), date(2025, 6, 30))
H1_2026 = (date(2026, 1, 1), date(2026, 6, 30))


def _spend(engine, supplier_id: str):
    return analyze_spend_growth(engine, supplier_id, *H1_2025, *H1_2026)


def evaluate_analytics(engine, cases_path: Path = CASES_PATH) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for case in json.loads(cases_path.read_text(encoding="utf-8"))["cases"]:
        kind, passed, actual = case["kind"], False, {}
        if kind == "spend":
            result = _spend(engine, case["supplier_id"])
            actual = {key: str(value) if value is not None and not isinstance(value, int) else value for key in case["expected"] for value in [getattr(result, key)]}
            passed = actual == case["expected"]
        elif kind == "zero_base":
            result = _spend(engine, case["supplier_id"])
            actual = {"growth_basis": result.growth_basis, "percentage_change": result.percentage_change}
            passed = result.growth_basis == case["expected_basis"] and result.percentage_change is None
        elif kind == "spend_drivers":
            result = _spend(engine, case["supplier_id"])
            actual = {"categories": {item.category_id: str(item.absolute_change) for item in result.category_contributions}, "largest": [item.po_number for item in result.largest_current_period_pos]}
            passed = actual["categories"] == case["expected_categories"] and actual["largest"] == case["expected_largest"] and sum(item.absolute_change for item in result.category_contributions) == result.absolute_change
        elif kind == "price":
            result = next(item for item in analyze_price_outliers(engine, case["item_code"]) if item.unit_of_measure == case["unit_of_measure"])
            actual = {"analysis_status": result.analysis_status, "outliers": [item.purchase_order_item_id for item in result.outliers]}
            passed = actual["analysis_status"] == case["expected_status"] and actual["outliers"] == case["expected_outliers"]
        elif kind == "concentration":
            result = analyze_single_source_risk(engine, case["category_id"], *H1_2026)
            actual = {"top_supplier_id": result.top_supplier_id, "top_supplier_share": str(result.top_supplier_share), "qualified_supplier_count": result.concentration.qualified_supplier_count, "risk_finding": result.risk_finding}
            passed = actual == {"top_supplier_id": case["expected_top"], "top_supplier_share": case["expected_share"], "qualified_supplier_count": case["expected_qualified"], "risk_finding": case["expected_risk"]}
        else:
            raise ValueError(f"Unknown analytics case type: {kind}")
        records.append({"case_id": case["case_id"], "kind": kind, "actual": actual, "passed": passed})
    by_kind = {kind: {"case_count": len([record for record in records if record["kind"] == kind]), "passed": len([record for record in records if record["kind"] == kind and record["passed"]])} for kind in sorted({record["kind"] for record in records})}
    return {"case_count": len(records), "passed": sum(record["passed"] for record in records), "failed": sum(not record["passed"] for record in records), "by_kind": by_kind, "records": records}


def write_analytics_report(report: dict[str, Any], path: Path = RESULTS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path

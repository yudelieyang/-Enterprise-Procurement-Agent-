from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from procurement_agent.compliance.engine import ComplianceEngine


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = PROJECT_ROOT / "evals" / "compliance_cases.json"
RESULTS_PATH = PROJECT_ROOT / "evals" / "results" / "compliance_metrics.json"


def _rule_status(result: Any, rule_type: str) -> str | None:
    for rule_result in (*result.rule_results, *result.skipped_rules):
        if rule_result.rule_type == rule_type:
            return rule_result.status
    return None


def evaluate_compliance(engine: ComplianceEngine, cases_path: Path = CASES_PATH) -> dict[str, Any]:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    records: list[dict[str, Any]] = []
    for case in cases:
        result = engine.audit(case["po_number"])
        actual = {"approval": _rule_status(result, "approval_requirement"), "contract": _rule_status(result, "contract_requirement"), "overall": result.overall_status}
        records.append({"case_id": case["case_id"], "po_number": case["po_number"], "expected": {key: case[key] for key in actual}, "actual": actual, "passed": actual == {key: case[key] for key in actual}})
    rule_matches = sum(record["actual"][field] == record["expected"][field] for record in records for field in ("approval", "contract"))
    rule_total = 2 * len(records)
    overall_matches = sum(record["actual"]["overall"] == record["expected"]["overall"] for record in records)
    metrics: dict[str, Any] = {"case_count": len(records), "rule_level_accuracy": rule_matches / rule_total, "overall_compliance_accuracy": overall_matches / len(records)}
    for status in ("PASS", "FAIL", "REVIEW"):
        expected = Counter(record["expected"]["overall"] == status for record in records)[True]
        predicted = Counter(record["actual"]["overall"] == status for record in records)[True]
        true_positive = sum(record["expected"]["overall"] == status and record["actual"]["overall"] == status for record in records)
        metrics[status.lower()] = {"precision": true_positive / predicted if predicted else None, "recall": true_positive / expected if expected else None}
    return {"metrics": metrics, "records": records}


def write_compliance_report(report: dict[str, Any], path: Path = RESULTS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path

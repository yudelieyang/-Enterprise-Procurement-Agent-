from __future__ import annotations

import json
from pathlib import Path

from procurement_agent.database.connection import sqlite_engine
from procurement_agent.evaluation.tasks import task_benchmark_summary, validate_golden_tasks


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "generated" / "procurement.sqlite"
RESULTS_PATH = PROJECT_ROOT / "evals" / "results" / "golden_task_validation.json"
SUMMARY_PATH = PROJECT_ROOT / "evals" / "results" / "golden_task_summary.md"


def main() -> None:
    engine = sqlite_engine(DATABASE_PATH)
    try:
        report = validate_golden_tasks(engine)
    finally:
        engine.dispose()
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = ["# Golden Task Benchmark Summary", "", f"Validation: {report['validation']}", f"Cases: {report['case_count']}", "", "## By task type", ""]
    rows.extend(f"- {key}: {value}" for key, value in report["by_task_type"].items())
    rows.extend(["", "## By required tool combination", ""])
    rows.extend(f"- {key}: {value}" for key, value in report["by_required_tool_combination"].items())
    rows.extend(["", "## Response outcomes", ""])
    rows.extend(f"- {key}: {value}" for key, value in report["response_outcomes"].items())
    SUMMARY_PATH.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

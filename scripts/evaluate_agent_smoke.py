"""Run and preserve the fixed Phase 3B.5 live smoke baseline once."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

from procurement_agent.agent.graph import ProcurementAgent
from procurement_agent.agent.model_adapter import LiveOpenAIModelAdapter, ModelAdapterError
from procurement_agent.agent.models import AgentConfig
from procurement_agent.evaluation.tasks import Citation, ToolTrace, evaluate_citations, evaluate_trace, load_golden_tasks, summarize_trace_results
from procurement_agent.tools.models import json_value


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = PROJECT_ROOT / "evals" / "results" / "agent_smoke_v1_live_baseline.json"
V2_RESULT_PATH = PROJECT_ROOT / "evals" / "results" / "agent_smoke_v2_live.json"
SMOKE_CASE_IDS = ("TASK-001", "TASK-002", "TASK-009", "TASK-010", "TASK-014", "TASK-020", "TASK-025", "TASK-033", "TASK-035", "TASK-030")


def _number(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _usage_totals(records: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"model_requests": 0, "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0}
    for record in records:
        usage = record["usage"]
        totals["model_requests"] += _number(usage.get("request_count"))
        for turn in [*usage.get("preflight_turns", []), *usage.get("turns", [])]:
            totals["input_tokens"] += _number(turn.get("prompt_tokens"))
            totals["cached_input_tokens"] += _number(turn.get("prompt_tokens_details", {}).get("cached_tokens"))
            totals["output_tokens"] += _number(turn.get("completion_tokens"))
            totals["reasoning_tokens"] += _number(turn.get("completion_tokens_details", {}).get("reasoning_tokens"))
            totals["total_tokens"] += _number(turn.get("total_tokens"))
    return totals


def _latency_summary(records: list[dict[str, Any]]) -> dict[str, float | None]:
    values = [record["latency_ms"] for record in records if isinstance(record.get("latency_ms"), (int, float))]
    if not values:
        return {"mean_ms": None, "median_ms": None, "min_ms": None, "max_ms": None}
    return {"mean_ms": round(mean(values), 3), "median_ms": round(median(values), 3), "min_ms": min(values), "max_ms": max(values)}


def _failure_category(trace_failures: tuple[str, ...], outcome_match: bool, citation_failures: tuple[str, ...], termination_reason: str | None) -> str | None:
    if termination_reason == "MODEL_EXECUTION_ERROR":
        return "API_ERROR"
    if termination_reason in {"MODEL_TURN_LIMIT", "TOOL_CALL_LIMIT", "REPEATED_TOOL_CALL_LIMIT"}:
        return "LOOP_LIMIT"
    if citation_failures or termination_reason == "INVALID_CITATION_REJECTED":
        return "CITATION_ERROR"
    if not outcome_match:
        return "INCORRECT_RESPONSE_OUTCOME"
    if "UNNECESSARY_TOOL_CALL" in trace_failures:
        return "UNNECESSARY_TOOL_CALL"
    if trace_failures:
        return "TOOL_SELECTION_ERROR"
    return None


def _markdown_report(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    lines = [
        f"# {report['prompt_version']} / {report['orchestration_version']} Live Smoke Evaluation",
        "",
        f"Configuration: `{report['configuration']['model']}`, reasoning effort `{report['configuration']['reasoning_effort']}`, `{report['configuration']['endpoint']}`, orchestration `{report['orchestration_version']}`.",
        "",
        "## Aggregate results",
        "",
        "| Measure | Value |",
        "| --- | ---: |",
        f"| Completed cases | {report['completed_cases']} / {report['case_count']} |",
        f"| Deterministic trace/citation/outcome checks passed | {report['deterministic_task_checks_passed']} / {report['case_count']} |",
    ]
    for name in ("tool_selection_precision", "tool_selection_recall", "required_tool_coverage", "unnecessary_tool_call_rate", "trajectory_success_rate", "response_outcome_accuracy", "citation_correctness", "evidence_coverage"):
        if name in metrics:
            lines.append(f"| {name} | {metrics[name]:.4f} |")
    lines.extend(["", "## Observable trajectories", "", "| Case | Tool trajectory | Outcome | Failure category |", "| --- | --- | --- | --- |"])
    for record in report["records"]:
        trajectory = " → ".join(record["tool_trajectory"]) or "No tool"
        lines.append(f"| {record['case_id']} | {trajectory} | {record['response_outcome']} | {record['failure_category'] or 'None'} |")
    lines.extend(["", "Final-answer fact extraction is `NOT_AUTOMATICALLY_SCORED`; this report records deterministic trace, citation, and outcome checks only.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one fixed ten-case live Agent smoke evaluation.")
    parser.add_argument("--reasoning-effort", default=None, help="Per-run OpenAI reasoning effort override.")
    parser.add_argument("--prompt-version", choices=("agent_v1", "agent_v2"), default="agent_v1")
    parser.add_argument("--orchestration-version", choices=("baseline", "guardrails_v1"), default="baseline")
    parser.add_argument("--output", type=Path, default=None, help="JSON report path; defaults to the preserved v1 baseline or the v2 candidate report.")
    args = parser.parse_args()
    result_path = args.output or (RESULT_PATH if args.prompt_version == "agent_v1" else V2_RESULT_PATH)
    summary_path = result_path.with_suffix(".md")
    if result_path.exists() or summary_path.exists():
        raise SystemExit(f"Refusing to overwrite existing live evaluation artifact: {result_path}")
    if not os.getenv("OPENAI_API_KEY"):
        print(json.dumps({"status": "not_run", "reason": "OPENAI_API_KEY is not configured; no live Agent request was made."}, indent=2))
        return 2

    tasks = {task.case_id: task for task in load_golden_tasks()}
    try:
        agent = ProcurementAgent(LiveOpenAIModelAdapter(reasoning_effort=args.reasoning_effort), config=AgentConfig(prompt_version=args.prompt_version, orchestration_version=args.orchestration_version))
    except ModelAdapterError as error:
        print(json.dumps({"status": "not_run", "reason": str(error)}, indent=2))
        return 2

    records: list[dict[str, Any]] = []
    try:
        for case_id in SMOKE_CASE_IDS:
            task = tasks[case_id]
            trace = agent.run(task.user_query, case_id=case_id)
            final = trace.final_response
            trace_result = evaluate_trace(task, ToolTrace.from_tools(*trace.tool_names))
            citation_result = evaluate_citations(task, tuple(Citation(item.chunk_id) for item in final.citations if item.chunk_id))
            outcome_match = final.response_outcome == task.expected_response_outcome
            category = _failure_category(trace_result.failures, outcome_match, citation_result.failures, trace.termination_reason)
            records.append({
                "case_id": case_id,
                "model": trace.model,
                "response_outcome": final.response_outcome,
                "expected_response_outcome": task.expected_response_outcome,
                "outcome_match": outcome_match,
                "tool_trajectory": trace.tool_names,
                "tool_call_count": len(trace.tool_call_records),
                "tool_durations_ms": [record.duration_ms for record in trace.tool_call_records],
                "model_turn_count": trace.model_turn_count,
                "preflight_model_requests": trace.preflight_model_requests,
                "preflight_duration_ms": trace.preflight_duration_ms,
                "orchestration_version": trace.orchestration_version,
                "requirements_version": trace.requirements_version,
                "request_requirements": trace.request_requirements.model_dump() if trace.request_requirements else None,
                "guardrail_events": [item.model_dump() for item in trace.guardrail_events],
                "evidence_remediation_count": trace.evidence_remediation_count,
                "tool_evaluation": json_value(trace_result),
                "citation_evaluation": json_value(citation_result),
                "citation_validation": [item.model_dump() for item in trace.citation_validation],
                "final_answer_fact_check": "NOT_AUTOMATICALLY_SCORED",
                "latency_ms": trace.duration_ms,
                "usage": trace.usage,
                "termination_reason": trace.termination_reason,
                "failure_category": category,
                "failure_evidence": list(trace_result.failures) + list(citation_result.failures),
            })
    finally:
        agent.close()

    trace_results = [evaluate_trace(tasks[record["case_id"]], ToolTrace.from_tools(*record["tool_trajectory"])) for record in records]
    report = {
        "status": "completed",
        "run_kind": "untouched_first_live_run" if args.prompt_version == "agent_v1" and args.orchestration_version == "baseline" else "candidate",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prompt_version": args.prompt_version,
        "orchestration_version": args.orchestration_version,
        "requirements_version": records[0]["requirements_version"],
        "configuration": {"model": records[0]["model"], "reasoning_effort": agent.model_adapter.reasoning_effort, "endpoint": "chat.completions.parse", "orchestration_version": args.orchestration_version},
        "case_count": len(records),
        "completed_cases": len(records),
        "deterministic_task_checks_passed": sum(record["failure_category"] is None for record in records),
        "metrics": summarize_trace_results(trace_results) | {
            "response_outcome_accuracy": sum(record["outcome_match"] for record in records) / len(records),
            "citation_correctness": mean(record["citation_evaluation"]["citation_correctness"] for record in records),
            "evidence_coverage": mean(record["citation_evaluation"]["evidence_coverage"] for record in records),
        },
        "usage_totals": _usage_totals(records),
        "local_live_smoke_latency_ms": _latency_summary(records),
        "failure_counts": dict(sorted(Counter(record["failure_category"] for record in records if record["failure_category"]).items())),
        "records": records,
    }
    result_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(_markdown_report(report), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

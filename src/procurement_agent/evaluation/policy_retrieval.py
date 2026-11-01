from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any

from procurement_agent.retrieval.policy_retrieval import PolicyRetriever, RetrievalResult, chunk_registry_hash


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = PROJECT_ROOT / "evals" / "policy_retrieval_cases.json"
RESULTS_DIR = PROJECT_ROOT / "evals" / "results"


def hit_at_k(retrieved: list[str], relevant: list[str], k: int) -> float | None:
    if not relevant:
        return None
    return float(bool(set(retrieved[:k]) & set(relevant)))


def recall_at_k(retrieved: list[str], relevant: list[str], k: int) -> float | None:
    if not relevant:
        return None
    return len(set(retrieved[:k]) & set(relevant)) / len(set(relevant))


def reciprocal_rank(retrieved: list[str], relevant: list[str]) -> float | None:
    relevant_set = set(relevant)
    if not relevant_set:
        return None
    return next((1.0 / rank for rank, chunk_id in enumerate(retrieved, start=1) if chunk_id in relevant_set), 0.0)


def _result_snapshot(results: list[RetrievalResult]) -> list[dict[str, Any]]:
    return [
        {"chunk_id": result.chunk_id, "document_id": result.document_id, "version": result.version,
         "section_label": result.section_label, "page_number": result.page_number, "score": round(result.score, 6)}
        for result in results
    ]


def _failure_category(case: dict[str, Any], retrieved: list[str]) -> str:
    if not case["relevant_chunk_ids"]:
        return "TEMPORAL_FILTER_ERROR"
    if len(case["relevant_chunk_ids"]) > 1:
        return "MULTI_EVIDENCE_MISS"
    return "DISTRACTOR_RANKING" if retrieved else "SEMANTIC_MISS"


def evaluate_mode(retriever: PolicyRetriever, cases: list[dict[str, Any]], mode: str, top_k: int = 3) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scored: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    empty_case_passes = 0
    for case in cases:
        results = retriever.retrieve(case["query"], case["target_date"], top_k=top_k, mode=mode)  # type: ignore[arg-type]
        retrieved_ids = [result.chunk_id for result in results]
        relevant = case["relevant_chunk_ids"]
        if not relevant:
            passed = not results
            empty_case_passes += int(passed)
            if not passed:
                failures.append({"case_id": case["case_id"], "query": case["query"], "expected_evidence": [], "actual_top_results": _result_snapshot(results), "failure_category": _failure_category(case, retrieved_ids)})
            continue
        case_metrics = {
            "hit_at_1": hit_at_k(retrieved_ids, relevant, 1),
            "hit_at_3": hit_at_k(retrieved_ids, relevant, 3),
            "recall_at_3": recall_at_k(retrieved_ids, relevant, 3),
            "mrr": reciprocal_rank(retrieved_ids, relevant),
        }
        scored.append(case_metrics)
        if not case_metrics["hit_at_3"] or case_metrics["recall_at_3"] < 1.0:
            failures.append({"case_id": case["case_id"], "query": case["query"], "expected_evidence": case["expected_evidence"], "actual_top_results": _result_snapshot(results), "failure_category": _failure_category(case, retrieved_ids)})
    metrics = {
        "case_count": len(cases),
        "scored_case_count": len(scored),
        "empty_candidate_case_count": len(cases) - len(scored),
        "empty_candidate_pass_count": empty_case_passes,
        "hit_at_1": mean(item["hit_at_1"] for item in scored),
        "hit_at_3": mean(item["hit_at_3"] for item in scored),
        "recall_at_3": mean(item["recall_at_3"] for item in scored),
        "mrr": mean(item["mrr"] for item in scored),
    }
    return metrics, failures


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def evaluate_all_modes(retriever: PolicyRetriever, cases: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cases = load_cases() if cases is None else cases
    report = {"chunk_count": len(retriever.chunks), "chunk_registry_hash": chunk_registry_hash(retriever.chunks), "top_k": 3, "modes": {}}
    failures: list[dict[str, Any]] = []
    for mode in ("lexical", "dense", "hybrid"):
        metrics, mode_failures = evaluate_mode(retriever, cases, mode)
        report["modes"][mode] = metrics
        failures.extend({"mode": mode, **failure} for failure in mode_failures)
    return report, failures


def write_evaluation_report(report: dict[str, Any], failures: list[dict[str, Any]], results_dir: Path = RESULTS_DIR) -> tuple[Path, Path, Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = results_dir / "policy_retrieval_metrics.json"
    failures_path = results_dir / "policy_retrieval_failures.json"
    summary_path = results_dir / "policy_retrieval_summary.md"
    metrics_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    failures_path.write_text(json.dumps(failures, indent=2) + "\n", encoding="utf-8")
    rows = ["# Policy Retrieval Evaluation", "", f"Cases: {report['modes']['lexical']['case_count']} (scored: {report['modes']['lexical']['scored_case_count']}; empty-coverage: {report['modes']['lexical']['empty_candidate_case_count']})", "", "| Mode | Hit@1 | Hit@3 | Recall@3 | MRR |", "|---|---:|---:|---:|---:|"]
    rows.extend(f"| {mode} | {metrics['hit_at_1']:.3f} | {metrics['hit_at_3']:.3f} | {metrics['recall_at_3']:.3f} | {metrics['mrr']:.3f} |" for mode, metrics in report["modes"].items())
    rows.extend(["", f"Recorded failures: {len(failures)}.", "", "Empty-coverage cases are checked separately and excluded from ranking metrics."])
    summary_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return metrics_path, failures_path, summary_path

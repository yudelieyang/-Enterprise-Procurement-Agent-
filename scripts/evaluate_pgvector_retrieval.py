"""Evaluate PostgreSQL exact dense retrieval against the local exact oracle."""

from __future__ import annotations

import json

from procurement_agent.evaluation.policy_retrieval import RESULTS_DIR, evaluate_mode, load_cases
from procurement_agent.retrieval.pgvector_store import PgvectorPolicyRetriever, PgvectorPolicyStore, PostgresConfig
from procurement_agent.retrieval.policy_retrieval import DenseEncoder, PolicyRetriever, chunk_registry_hash, load_chunk_registry


def main() -> None:
    chunks = load_chunk_registry()
    encoder = DenseEncoder()
    local = PolicyRetriever(chunks, encoder)
    cases = load_cases()
    with PgvectorPolicyStore(PostgresConfig.from_environment()) as store:
        pgvector = PgvectorPolicyRetriever(store, encoder)
        local_metrics, _ = evaluate_mode(local, cases, "dense")
        pgvector_metrics, failures = evaluate_mode(pgvector, cases, "dense")
        ranking_differences = []
        for case in cases:
            local_ids = [item.chunk_id for item in local.retrieve(case["query"], case["target_date"], top_k=3, mode="dense")]
            pgvector_ids = [item.chunk_id for item in pgvector.retrieve(case["query"], case["target_date"], top_k=3)]
            if local_ids != pgvector_ids:
                ranking_differences.append({"case_id": case["case_id"], "local_chunk_ids": local_ids, "pgvector_chunk_ids": pgvector_ids})
        report = {
            "chunk_count": len(chunks), "chunk_registry_hash": chunk_registry_hash(chunks), "versions": store.versions(),
            "local_dense_metrics": local_metrics, "pgvector_dense_metrics": pgvector_metrics,
            "ranking_equivalence": {"case_count": len(cases), "identical_case_count": len(cases) - len(ranking_differences), "differences": ranking_differences},
            "failures": failures,
        }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "pgvector_retrieval_metrics.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()

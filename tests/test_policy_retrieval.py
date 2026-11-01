from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from procurement_agent.evaluation.policy_retrieval import hit_at_k, recall_at_k, reciprocal_rank
from procurement_agent.retrieval.policy_retrieval import DenseEncoder, PolicyRetriever, build_policy_chunks, chunk_registry_hash, reciprocal_rank_fusion


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_DIR = PROJECT_ROOT / "data" / "policies"


def test_pdf_ingestion_produces_stable_page_bounded_section_chunks():
    first, second = build_policy_chunks(), build_policy_chunks()
    manifest = json.loads((POLICY_DIR / "policy_manifest.json").read_text(encoding="utf-8"))
    expected_documents = {document["document_id"] for document in manifest["documents"]}
    assert len(first) == 30
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert chunk_registry_hash(first) == chunk_registry_hash(second)
    assert {chunk.document_id for chunk in first} == expected_documents
    for chunk in first:
        document = next(item for item in manifest["documents"] if item["document_id"] == chunk.document_id)
        assert chunk.content and chunk.section_label in chunk.content
        assert (chunk.page_number, chunk.section_label, chunk.section_title) in {
            (section["expected_page"], section["label"], section["title"]) for section in document["sections"]
        }


def test_canonical_rule_passages_remain_in_single_pdf_derived_chunk():
    chunks = build_policy_chunks()
    rules = json.loads((POLICY_DIR / "policy_rules.json").read_text(encoding="utf-8"))["rules"]
    for rule in rules:
        matching = [chunk for chunk in chunks if (chunk.document_id, chunk.section_label, chunk.page_number) == (rule["source_document_id"], rule["source_section"], rule["source_page"])]
        assert len(matching) == 1
        assert " ".join(rule["canonical_source_phrase"].lower().split()) in " ".join(matching[0].content.lower().split())


def test_temporal_filtering_happens_before_lexical_ranking():
    retriever = PolicyRetriever(build_policy_chunks())
    historical = retriever.retrieve("purchase approval threshold", date(2025, 6, 30), top_k=30, mode="lexical")
    current = retriever.retrieve("purchase approval threshold", date(2026, 6, 30), top_k=30, mode="lexical")
    default_current = retriever.retrieve("purchase approval threshold", top_k=30, mode="lexical")
    unsupported = retriever.retrieve("2024 contract policy", date(2024, 6, 30), mode="lexical")
    assert historical and {result.version for result in historical} == {"2025.1"}
    assert current and {result.version for result in current} == {"2026.1"}
    assert [result.chunk_id for result in default_current] == [result.chunk_id for result in current]
    assert unsupported == []


def test_lexical_results_are_structured_and_temporally_valid():
    results = PolicyRetriever(build_policy_chunks()).retrieve("supplier dependency mitigation", "2026-06-30", top_k=3, mode="lexical")
    assert results and all(result.retrieval_method == "lexical_bm25" and result.version == "2026.1" for result in results)


def test_dense_canonical_approval_query_uses_exact_cpu_similarity():
    retriever = PolicyRetriever(build_policy_chunks(), DenseEncoder())
    results = retriever.retrieve("What approvals are required for a purchase above $50,000?", "2026-06-30", top_k=3, mode="dense")
    hybrid = retriever.retrieve("What approvals are required for a purchase above $50,000?", "2026-06-30", top_k=3, mode="hybrid")
    assert "APPROVAL_MATRIX_2026_1:2026.1:p2:s4_2:c1" in {result.chunk_id for result in results}
    assert all(result.retrieval_method == "dense_exact_cosine" and result.version == "2026.1" for result in results)
    assert hybrid and all(result.retrieval_method == "hybrid_rrf" and result.version == "2026.1" for result in hybrid)


def test_rrf_and_retrieval_metrics_are_deterministic():
    fused = reciprocal_rank_fusion([[(0, 0.9), (1, 0.8)], [(1, 0.9), (0, 0.8)]], rrf_k=60)
    assert fused == [(0, 1 / 61 + 1 / 62), (1, 1 / 62 + 1 / 61)]
    retrieved, relevant = ["a", "x", "b"], ["a", "b"]
    assert hit_at_k(retrieved, relevant, 1) == 1.0
    assert recall_at_k(retrieved, relevant, 1) == 0.5
    assert recall_at_k(retrieved, relevant, 3) == 1.0
    assert reciprocal_rank(retrieved, relevant) == 1.0
    assert hit_at_k([], [], 3) is None

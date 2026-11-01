"""Opt-in integration checks; run only against the dedicated local pgvector database."""

from __future__ import annotations

import pytest
import psycopg

from procurement_agent.evaluation.policy_retrieval import evaluate_mode, load_cases
from procurement_agent.retrieval.pgvector_store import PgvectorPolicyRetriever, PgvectorPolicyStore, PostgresConfig, load_persisted_embeddings
from procurement_agent.retrieval.policy_retrieval import DenseEncoder, PolicyRetriever, load_chunk_registry


pytestmark = pytest.mark.integration
try:
    config = PostgresConfig.from_environment()
    with psycopg.connect(host=config.host, port=config.port, dbname=config.database, user=config.user, password=config.password, connect_timeout=5):
        pass
except Exception as error:
    pytest.skip(f"pgvector integration database is unavailable: {error}", allow_module_level=True)


@pytest.fixture(scope="module")
def pgvector_retriever():
    chunks = load_chunk_registry()
    store = PgvectorPolicyStore(PostgresConfig.from_environment())
    store.connect()
    store.rebuild(chunks, load_persisted_embeddings(chunks))
    yield PgvectorPolicyRetriever(store, DenseEncoder())
    store.close()


def test_pgvector_loads_all_canonical_chunks_and_reports_versions(pgvector_retriever):
    versions = pgvector_retriever.store.versions()
    with pgvector_retriever.store.connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*), vector_dims(embedding) FROM policy_chunks_pgvector GROUP BY vector_dims(embedding)")
        row = cursor.fetchone()
    assert row == (30, 384)
    assert versions["postgresql"] and versions["pgvector"]


def test_pgvector_temporal_filtering_precedes_exact_cosine_ranking(pgvector_retriever):
    historical = pgvector_retriever.retrieve("purchase approval threshold", "2025-06-30", top_k=30)
    current = pgvector_retriever.retrieve("purchase approval threshold", "2026-06-30", top_k=30)
    unsupported = pgvector_retriever.retrieve("2024 contract policy", "2024-06-30")
    assert historical and {result.version for result in historical} == {"2025.1"}
    assert current and {result.version for result in current} == {"2026.1"}
    assert unsupported == []


def test_pgvector_rankings_and_metrics_match_the_local_exact_oracle(pgvector_retriever):
    chunks, cases = load_chunk_registry(), load_cases()
    encoder = pgvector_retriever.dense_encoder
    local = PolicyRetriever(chunks, encoder)
    for case in cases:
        local_ids = [result.chunk_id for result in local.retrieve(case["query"], case["target_date"], top_k=3, mode="dense")]
        pgvector_ids = [result.chunk_id for result in pgvector_retriever.retrieve(case["query"], case["target_date"], top_k=3)]
        assert pgvector_ids == local_ids, case["case_id"]
    local_metrics, _ = evaluate_mode(local, cases, "dense")
    pgvector_metrics, _ = evaluate_mode(pgvector_retriever, cases, "dense")
    assert pgvector_metrics == local_metrics

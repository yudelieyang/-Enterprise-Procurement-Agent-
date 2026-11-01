"""Load the canonical Phase 2D registry and persisted embeddings into pgvector."""

from procurement_agent.retrieval.pgvector_store import PgvectorPolicyStore, PostgresConfig, load_persisted_embeddings
from procurement_agent.retrieval.policy_retrieval import load_chunk_registry


def main() -> None:
    chunks = load_chunk_registry()
    persisted = load_persisted_embeddings(chunks)
    with PgvectorPolicyStore(PostgresConfig.from_environment()) as store:
        row_count = store.rebuild(chunks, persisted)
        print({"rows_loaded": row_count, "versions": store.versions(), "chunk_registry_hash": persisted.metadata["chunk_registry_hash"]})


if __name__ == "__main__":
    main()

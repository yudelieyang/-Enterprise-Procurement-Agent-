from procurement_agent.retrieval.pgvector_store import EMBEDDING_DIMENSION, load_persisted_embeddings
from procurement_agent.retrieval.policy_retrieval import DEFAULT_DENSE_MODEL, load_chunk_registry


def test_pgvector_loader_reuses_validated_phase_2d_embedding_artifacts():
    chunks = load_chunk_registry()
    persisted = load_persisted_embeddings(chunks)
    assert persisted.vectors.shape == (len(chunks), EMBEDDING_DIMENSION)
    assert persisted.metadata["model_name"] == DEFAULT_DENSE_MODEL
    assert persisted.metadata["chunk_count"] == len(chunks)

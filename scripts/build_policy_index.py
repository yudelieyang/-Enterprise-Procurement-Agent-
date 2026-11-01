from procurement_agent.retrieval.policy_retrieval import DenseEncoder, PolicyRetriever, build_policy_chunks, write_chunk_registry, write_embedding_artifacts


if __name__ == "__main__":
    chunks = build_policy_chunks()
    write_chunk_registry(chunks)
    metadata = write_embedding_artifacts(PolicyRetriever(chunks, DenseEncoder()))
    print({"chunk_count": len(chunks), **metadata})

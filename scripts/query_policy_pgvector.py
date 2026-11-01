"""Inspect exact pgvector policy retrieval without an Agent or answer-generation layer."""

from __future__ import annotations

import argparse

from procurement_agent.retrieval.pgvector_store import PgvectorPolicyRetriever, PgvectorPolicyStore, PostgresConfig
from procurement_agent.retrieval.policy_retrieval import DenseEncoder


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--target-date", default="2026-06-30")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    with PgvectorPolicyStore(PostgresConfig.from_environment()) as store:
        retriever = PgvectorPolicyRetriever(store, DenseEncoder())
        for result in retriever.retrieve(args.query, args.target_date, args.top_k):
            print(result.to_dict())


if __name__ == "__main__":
    main()

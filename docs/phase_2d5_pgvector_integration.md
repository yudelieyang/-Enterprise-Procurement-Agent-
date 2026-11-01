# Phase 2D.5 — PostgreSQL + pgvector Retrieval Integration

## Purpose and boundary

This phase moves the accepted Phase 2D canonical policy chunks into a real PostgreSQL + pgvector table without changing the SQLite procurement database. It is a retrieval-infrastructure integration only: there is no Agent, LLM call, answer generation, compliance engine, ANN index, or hybrid/lexical database implementation.

The Phase 2D local CPU exact-dense retriever remains the correctness oracle. PostgreSQL must reproduce its eligible-corpus and ranking behavior before it becomes the future retrieval backend.

## Source and load contract

The source corpus remains the generated PDFs. Phase 2D extracted them into `data/retrieval/policy_chunks.jsonl`; this integration reads that canonical registry and does not read Markdown policy sources. `scripts/load_policy_chunks_pgvector.py` also loads the persisted, normalized `policy_embeddings.npz` artifact rather than recomputing vectors.

The loader rejects a mismatched chunk count, registry hash, chunk-ID order, model name, dimension, or non-normalized vector. Its currently accepted configuration is `sentence-transformers/multi-qa-MiniLM-L6-cos-v1`, 384 dimensions, CPU normalization. Embeddings are not written into text registries or committed to Git.

## PostgreSQL model

`policy_chunks_pgvector` has `chunk_id` as its primary key and stores document ID, title, policy type, version, effective/expiration dates, section label/title, page, chunk index, content, and `embedding vector(384)`. It is deliberately a dedicated generated retrieval table; no procurement SQLite table is migrated or queried.

The loader replaces rows in only that generated table in one transaction. It creates `vector` with `CREATE EXTENSION IF NOT EXISTS vector`; the target role must be allowed to do so or the extension must already be installed.

## Exact temporal retrieval

`PgvectorPolicyRetriever` accepts an explicit target date (default `2026-06-30`) and uses the same query encoder as Phase 2D. Its query is intentionally shaped as follows:

```sql
SELECT ..., embedding <=> :query_vector AS cosine_distance
FROM policy_chunks_pgvector
WHERE effective_date <= :target_date
  AND (expiration_date IS NULL OR expiration_date >= :target_date)
ORDER BY cosine_distance ASC, chunk_id ASC
LIMIT :top_k;
```

This makes temporal applicability a hard SQL candidate filter before vector ordering. Scores returned to callers are `1 - cosine_distance`, matching the local normalized dot-product convention. There is no HNSW, IVFFlat, or other ANN index.

## Local setup and commands

Copy `.env.example` to `.env`, set a local-only password, then start the minimal isolated service:

```powershell
docker compose up -d
.\.venv\Scripts\python.exe scripts/load_policy_chunks_pgvector.py
.\.venv\Scripts\python.exe scripts/query_policy_pgvector.py "What approvals are required for a purchase above $50,000?" --target-date 2026-06-30
.\.venv\Scripts\python.exe scripts/evaluate_pgvector_retrieval.py
.\.venv\Scripts\python.exe -m pytest -m integration
```

`docker-compose.yml` uses `pgvector/pgvector:pg18` and exposes the database on the `.env` port (default `5433`) to avoid assuming that an existing local PostgreSQL service on `5432` is usable.

## Evaluation and equivalence

The pgvector evaluation uses the existing 21 retrieval cases and the same deterministic metrics: Hit@1, Hit@3, Recall@3, and MRR. It writes `evals/results/pgvector_retrieval_metrics.json`, including PostgreSQL/pgvector versions, local and database metrics, each top-3 ranking difference, and retrieval failures. The integration test asserts every case's top-3 chunk IDs and aggregate dense metrics match the local exact oracle.

No result is considered measured until the script runs against a live PostgreSQL database with the `vector` extension.

## Runtime verification — 2026-08-27

The isolated Compose container was rebuilt after correcting the PostgreSQL 18 volume mount to `/var/lib/postgresql`. It remained running, `pg_isready` accepted connections on host port 5433, and PostgreSQL startup logs confirmed `database system is ready to accept connections`.

The live database reports PostgreSQL `18.6 (Debian 18.6-1.pgdg12+2)` and pgvector `0.8.6`. `CREATE EXTENSION IF NOT EXISTS vector` succeeded through the loader. The loader accepted the Phase 2D registry hash, model, 384 dimensions, normalization, and stable chunk ordering, then loaded 30 chunks with 30 distinct IDs. The only index is the primary-key B-tree; no HNSW or IVFFlat index exists.

The 21-case exact pgvector evaluation produced:

| Hit@1 | Hit@3 | Recall@3 | MRR |
|---:|---:|---:|---:|
| 0.750 | 0.850 | 0.808 | 0.792 |

All 21 top-3 rankings were identical to the local exact dense oracle, including the zero-candidate 2024 case. The live integration suite passed `3 passed, 35 deselected`; full project pytest passed `38 passed`. The integration test explicitly verified that 2025 results contain only 2025.1 evidence, 2026-06-30 results contain only 2026.1 evidence, and the 2024 query returns no result.

## Limitations and next gate

This phase does not implement PostgreSQL full-text/BM25, RRF, or a database index because the corpus has only 30 chunks and Phase 2D already measures lexical and hybrid baselines.

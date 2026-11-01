# Phase 2D - Policy Retrieval Foundation

## Scope

This phase turns the seven generated policy PDFs into a local retrieval component. It does not implement an Agent, LLM call, answer generation, compliance engine, vector database, ANN index, API, or UI.

## Ingestion and canonical chunks

`build_policy_chunks()` reads the generated PDFs with `pypdf`. It detects `Section N[.N]` headings from each PDF page, removes page header/footer material by beginning at the first section heading, and emits one or more paragraph-bounded chunks for each section. Chunks never cross a PDF page.

The current corpus produces 30 canonical chunks. A chunk includes document ID, title, policy type, version, effective interval, section label/title, page, deterministic chunk index, PDF filename, and content. IDs have the stable form:

```text
DOCUMENT_ID:VERSION:pPAGE:sSECTION:cINDEX
```

`data/retrieval/policy_chunks.jsonl` is the generated canonical registry. `data/retrieval/policy_embeddings.npz` is a separately generated, ignored embedding artifact. Its metadata records model/configuration, dimension, and the hash of the registry.

## Retrieval behavior

Every retrieval call accepts an explicit `target_date`; omitted dates resolve to `2026-06-30`. Validity filtering occurs before any BM25, dense, or RRF ranking. A date in 2024 returns no candidates rather than falling forward to a policy version.

- Lexical: `rank-bm25` BM25 over the deterministic retrieval representation.
- Dense: direct CPU Sentence Transformers encoding with `sentence-transformers/multi-qa-MiniLM-L6-cos-v1`; normalized vectors are ranked by exact dot product, equivalent to cosine similarity.
- Hybrid: reciprocal-rank fusion with the conventional `k=60`; no learned weights or reranker.

The embedding representation preserves document title, human-readable policy type, version, section label/title, and PDF-extracted chunk content. It contains no scenario identifiers, expected answers, or evaluation labels.

## Evaluation

`evals/policy_retrieval_cases.json` has 21 curated PDF-evidence queries: 20 ranked-evidence cases and one unsupported 2024 temporal-coverage case. Multi-policy cases hold multiple relevant chunk IDs. Empty-coverage cases are checked separately and excluded from rank metrics.

Run:

```text
python scripts/build_policy_index.py
python scripts/evaluate_policy_retrieval.py
```

Measured on the current 30-chunk registry with Sentence Transformers 6.0.0 and the 384-dimensional model:

| Mode | Hit@1 | Hit@3 | Recall@3 | MRR |
|---|---:|---:|---:|---:|
| lexical | 0.700 | 0.850 | 0.808 | 0.767 |
| dense | 0.750 | 0.850 | 0.808 | 0.792 |
| hybrid | 0.800 | 0.850 | 0.808 | 0.825 |

The 2024 empty-coverage query passed for every mode. Machine-readable metrics, result summary, and every miss with expected evidence, top results, scores, and a category are written under `evals/results/`.

## Failure analysis and limitations

The benchmark intentionally retains baseline misses instead of rewriting the accepted policy corpus to optimize scores. The failure report shows lexical and dense distractor-ranking misses on broad historical-contract and supplier-dependency phrasing, plus multi-evidence recall misses where a top-3 result surfaces only part of a multi-policy need. These are a useful baseline for a later retrieval-improvement phase; no policy text was altered to fit the queries.

`pgvector` remains the deployment target but is deferred. The corpus is too small for ANN to add value, and this phase establishes chunk/provenance correctness and exact-search rankings that a later PostgreSQL + pgvector integration can compare against.

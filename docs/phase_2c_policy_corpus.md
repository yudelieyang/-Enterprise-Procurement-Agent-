# Phase 2C - Synthetic Policy Corpus

Phase 2C adds seven versioned, synthetic policy PDFs. Each PDF is generated locally from editable Markdown in `data/policies/source/`; no LLM or network is used. The generation command is:

```text
python scripts/generate_policies.py
python scripts/validate_policies.py
pytest
```

## Citation and provenance contract

`data/policies/policy_manifest.json` owns document identifiers, versions, effective intervals, source filenames, PDF filenames, stable section labels, and expected pages. The validator extracts each PDF page and checks its title, version, section labels, and citation locations.

`data/policies/policy_rules.json` contains only the current executable MVP rules. It is not a policy DSL or compliance engine. Every rule cites a document ID, version, section, page, and a canonical phrase on that page. This is the file-level precursor to the later relationship:

```text
PolicyRule -> canonical PolicyChunk -> PolicyDocument -> version / section / page
```

## Version semantics

The controlled Approval Authority Matrix difference is the strict threshold: 2025.1 applies above USD 75,000 and 2026.1 applies above USD 50,000. Both versions require two distinct valid PURCHASE approvals including a DIRECTOR. Contract policy keeps IT Services and Professional Services in scope; 2026.1 makes the timing and unresolved-evidence treatment of an exception explicit.

There is no 2024 policy coverage. Supplier Selection Policy begins at 2026.1, intentionally supporting insufficiency tests for 2025 supplier-selection questions.

## Boundaries

The corpus provides human-readable evidence, retrieval targets, and deterministic rule provenance. It does not add chunking, embeddings, a vector database, RAG, an LLM, a compliance engine, or agent orchestration.

# Phase 2B — Structured Data Access Layer / SQL Foundation

## Backend decision

Phase 2B uses SQLite through SQLAlchemy 2.x. It provides deterministic local relational behavior and fast pytest execution without requiring PostgreSQL, Docker, or external services. This is a development/test backend only; the later infrastructure direction remains PostgreSQL plus pgvector for structured data and policy retrieval.

## Loading flow

```text
Phase 2A generated CSV + ground_truth.json
  → source validation
  → FK-safe SQLAlchemy inserts
  → SQLite schema and row-count validation
  → data/generated/procurement.sqlite
```

The SQLite database is generated and ignored by Git. Rebuild it with:

```text
python scripts/generate_data.py
python scripts/validate_data.py
python scripts/build_database.py
```

The schema has only the Phase 2B business tables: business units, categories, suppliers, purchase orders, purchase-order items, contracts, approvals, and supplier-category eligibility. It has no policy, invoice, receipt, payment, inventory, warehouse, or future-agent table.

## Data semantics preserved

- Monetary columns use SQLAlchemy `NUMERIC(14,2)` and Python `Decimal`; loader tests verify each loaded PO total equals the sum of its loaded line amounts.
- Category contract applicability is an explicit boolean and true only for IT Services and Professional Services.
- PO status and evidence availability fields are retained unchanged.
- Contract dates, supplier, category, and termination date are stored as facts; this SQL layer does not make a compliance decision.
- Approval types, statuses, roles, and timestamps are stored as facts compatible with the later valid-approval rule.

## Schema inspection

`list_tables(engine)` and `describe_table(engine, table_name)` read SQLite metadata directly. They provide table names, columns, primary-key flags, and foreign-key relationships for a future SQL tool's schema-discovery step; no LLM is involved.

## Read-only query interface

`execute_readonly_query(engine, sql, max_rows=100)` returns:

```text
columns
rows
row_count
```

It permits exactly one `SELECT` or `WITH ... SELECT` statement. A small quote/comment-aware scanner rejects multi-statement input and mutation or SQLite-control keywords such as `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `ATTACH`, and `PRAGMA`.

The scanner is intentionally small because Phase 2B has no user-facing LLM or arbitrary external input. `sqlglot` was deferred: adding a full SQL parser is not justified until the future SQL tool accepts model-generated SQL across dialects. Results above 100 rows raise an explicit error rather than being silently truncated.

## SQL / business-logic boundary

Reference SQL retrieves and aggregates facts. It does not compute `PASS`, `FAIL`, or `REVIEW`, infer policy, or produce natural-language explanations. Those remain future Compliance Engine and policy-evidence responsibilities.

Reference query coverage includes:

- past-six-month spend by business unit;
- Q2 2026 IT supplier ranking;
- SUP-042 H1 2025 versus H1 2026 spend;
- SQL-window-function indirect-spend Pareto;
- off-contract fact retrieval;
- high-value approval fact retrieval;
- canonical PO-2026-1842 audit facts; and
- SUP-017 concentration and qualification facts.

## Migration expectation

Models use ordinary relational keys, dates, `NUMERIC` money fields, checks, and foreign keys. No SQLite-specific production design is introduced. Later PostgreSQL migration should primarily be configuration and migration work, followed by dialect-specific query and integration testing.

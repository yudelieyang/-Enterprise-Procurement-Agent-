# Enterprise Procurement Intelligence Agent

A single-agent procurement analyst backed by deterministic data tools. The project combines bounded SQL, policy retrieval with citations, deterministic compliance rules, and procurement analytics. The model selects tools and explains their results; it does not make compliance decisions.

## Architecture

```text
User → LangGraph single-agent loop → typed tool registry
                                 ├─ SQL (read-only SQLite)
                                 ├─ Policy Retrieval (PDF-derived local hybrid search)
                                 ├─ Analytics (bounded deterministic calculations)
                                 └─ Compliance (structured policy rules)
       → run-local evidence/citation validation and guardrails → response + trace
```

The four tool capabilities are `query_procurement_database`, `retrieve_procurement_policy`, `analyze_procurement_data`, and `check_policy_compliance`. The SQL tool accepts one read-only `SELECT`/`WITH` query with a bounded result size. Retrieval filters policy validity by date before ranking and returns document, version, section, and page provenance. Compliance evaluates structured rules deterministically. Analytics covers supplier spend growth and drivers, comparable-item price outliers, and supplier concentration risk.

The local Agent uses `agent_v1` with baseline orchestration by default. `agent_v2`, `guardrails_v1`, and `requirements_v2_1` are versioned candidates and must be selected explicitly in code/configuration. The normal Agent Retrieval backend is local hybrid search. PostgreSQL/pgvector is a separately tested exact dense retrieval integration; it does not replace SQLite or change the Agent default.

## Stack

Python 3.11+, SQLAlchemy, SQLite, LangGraph, Pydantic, OpenAI Python SDK, pypdf, sentence-transformers (CPU exact dense search), rank-bm25, PostgreSQL 18 with pgvector for the optional retrieval integration, and pytest.

## Repository contents

The repository includes deterministic synthetic CSV data, policy Markdown sources and rendered PDFs, the canonical PDF-derived chunk registry, normalized 384-dimensional embedding artifacts, golden task fixtures, component evaluation cases, and preserved evaluation reports. The generated SQLite runtime database, secrets, local environments, caches, and recovery backups are excluded.

## Windows setup

Create and activate an environment, then install the project dependencies from `pyproject.toml`:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

The editable installation in the recovered workstation currently points to an old checkout. Until it is repaired, run from the project root with a process-local source path:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location).Path "src"
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:HF_HUB_OFFLINE = "1" # when using the already cached embedding model offline
```

The project’s generated SQLite database is normally built from the committed CSV source files:

```powershell
python scripts/validate_data.py
python scripts/build_database.py
```

Build the policy artifacts only when they are missing or intentionally regenerated:

```powershell
python scripts/validate_policies.py
python scripts/build_policy_index.py
```

`build_database.py` writes `data/generated/procurement.sqlite`; `build_policy_index.py` writes retrieval artifacts. Keep these commands away from an existing working dataset unless regeneration is intended.

## Running and testing

The CLI makes a live model request and requires `OPENAI_API_KEY` in the process environment. Do not commit that value. The CLI currently starts with `agent_v1` and baseline orchestration:

```powershell
python scripts/run_agent.py "Is PO-2026-1842 compliant with procurement policy?"
```

Run offline tests without the live API or PostgreSQL integration:

```powershell
python -B -m pytest -vv -p no:cacheprovider -m "not live_agent" --ignore=tests/test_pgvector_integration.py
```

The PostgreSQL integration test is destructive to its target database’s dedicated `policy_chunks_pgvector` table: its fixture calls `rebuild()` and replaces the table rows. Use only a verified isolated test database, never the primary database. The separate `scripts/evaluate_pgvector_retrieval.py` writes `evals/results/pgvector_retrieval_metrics.json`; preserve or redirect that historical result before running it.

## Evaluation

Component evaluators cover read-only SQL, policy retrieval (Hit@k, Recall@k, MRR), compliance, analytics, tool selection/trajectory, citation/evidence coverage, response outcomes, and semantic preflight contracts. Golden task expectations use a fixed evaluation date so results do not depend on the workstation clock. Live Agent evaluations spend API credits and are opt-in; they are not part of the offline test command.

## Known limitations

- No Git history is available in the recovered local directory; this repository is being prepared as a new local Git baseline.
- The existing editable installation refers to a former path. `PYTHONPATH=src` is the current workaround.
- Local Retrieval defaults to hybrid lexical/dense ranking. pgvector provides exact dense retrieval only and has no ANN index.
- The current golden suite and historical live samples are evaluation artifacts, not proof of production accuracy. TASK-035’s prompt change has offline/scripted coverage; live model behavior still requires a separately approved calibration run.
- The synthetic corpus is scoped to the domain rules documented in `PROJECT_CONTEXT.md`; the Agent does not implement ERP operations or procurement writes.

## Local PostgreSQL/pgvector

The optional Compose service uses the `pgvector/pgvector:pg18` image and a named volume. Copy `.env.example` to `.env`, set a local-only password, and verify the target database before starting or loading anything. The loader replaces rows in `policy_chunks_pgvector`; only run it against a dedicated local database after backing up any data that must be kept.

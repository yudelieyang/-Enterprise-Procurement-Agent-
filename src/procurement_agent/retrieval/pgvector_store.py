"""Exact PostgreSQL/pgvector retrieval over the canonical policy-chunk registry."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

import numpy as np

from procurement_agent.retrieval.policy_retrieval import (
    DEFAULT_DENSE_MODEL,
    EMBEDDING_METADATA_PATH,
    EMBEDDING_PATH,
    EVAL_AS_OF_DATE,
    PolicyChunk,
    PolicyRetrievalError,
    RetrievalResult,
    chunk_registry_hash,
)


EMBEDDING_DIMENSION = 384
TABLE_NAME = "policy_chunks_pgvector"
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class PgvectorIntegrationError(RuntimeError):
    """Raised when the pgvector integration cannot safely execute."""


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_environment(cls) -> "PostgresConfig":
        _load_local_env()
        values = {name: os.getenv(f"POSTGRES_{name}") for name in ("HOST", "PORT", "DB", "USER", "PASSWORD")}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise PgvectorIntegrationError("Missing PostgreSQL configuration: " + ", ".join(f"POSTGRES_{name}" for name in missing))
        try:
            port = int(values["PORT"] or "")
        except ValueError as error:
            raise PgvectorIntegrationError("POSTGRES_PORT must be an integer") from error
        return cls(values["HOST"] or "", port, values["DB"] or "", values["USER"] or "", values["PASSWORD"] or "")


def _load_local_env(path: Path = PROJECT_ROOT / ".env") -> None:
    """Load the repository's simple local Compose config without another dependency."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        if key.startswith("POSTGRES_"):
            os.environ.setdefault(key, value.strip().strip("'\""))


@dataclass(frozen=True)
class PersistedEmbeddings:
    vectors: np.ndarray
    metadata: dict[str, Any]


def load_persisted_embeddings(
    chunks: list[PolicyChunk],
    embeddings_path: Path = EMBEDDING_PATH,
    metadata_path: Path = EMBEDDING_METADATA_PATH,
) -> PersistedEmbeddings:
    """Load, never recompute, the Phase 2D embeddings after provenance checks."""
    if not embeddings_path.is_file() or not metadata_path.is_file():
        raise PgvectorIntegrationError("Persisted embedding artifacts are required; run scripts/build_policy_index.py first")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected_ids = [chunk.chunk_id for chunk in chunks]
    expected_hash = chunk_registry_hash(chunks)
    if metadata.get("model_name") != DEFAULT_DENSE_MODEL:
        raise PgvectorIntegrationError("Embedding model does not match the approved dense baseline")
    if metadata.get("embedding_dimension") != EMBEDDING_DIMENSION:
        raise PgvectorIntegrationError("Embedding dimension does not match vector(384)")
    if metadata.get("chunk_count") != len(chunks) or metadata.get("chunk_registry_hash") != expected_hash:
        raise PgvectorIntegrationError("Embedding metadata does not match the canonical chunk registry")
    with np.load(embeddings_path, allow_pickle=False) as artifact:
        vectors = np.asarray(artifact["embeddings"], dtype=np.float32)
        artifact_ids = [str(chunk_id) for chunk_id in artifact["chunk_ids"].tolist()]
    if artifact_ids != expected_ids:
        raise PgvectorIntegrationError("Embedding artifact chunk order does not match the canonical registry")
    if vectors.shape != (len(chunks), EMBEDDING_DIMENSION):
        raise PgvectorIntegrationError(f"Unexpected embedding shape: {vectors.shape}")
    if not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-4):
        raise PgvectorIntegrationError("Persisted vectors must be normalized for cosine-equivalent exact search")
    return PersistedEmbeddings(vectors=vectors, metadata=metadata)


class PgvectorPolicyStore:
    """A minimal direct Psycopg store. It intentionally creates no ANN index."""

    def __init__(self, config: PostgresConfig) -> None:
        self.config = config
        self.connection: Any | None = None

    def connect(self) -> None:
        if self.connection is not None:
            return
        try:
            import psycopg
            from pgvector.psycopg import register_vector
        except ImportError as error:
            raise PgvectorIntegrationError("Install the project dependencies with the pgvector extra support") from error
        try:
            self.connection = psycopg.connect(
                host=self.config.host, port=self.config.port, dbname=self.config.database,
                user=self.config.user, password=self.config.password, connect_timeout=5,
            )
            with self.connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            self.connection.commit()
            register_vector(self.connection)
        except Exception as error:
            self.close()
            raise PgvectorIntegrationError(f"Could not initialize PostgreSQL + pgvector: {error}") from error

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __enter__(self) -> "PgvectorPolicyStore":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _connection(self) -> Any:
        self.connect()
        if self.connection is None:  # Defensive: connect either returns or raises.
            raise PgvectorIntegrationError("PostgreSQL connection is unavailable")
        return self.connection

    def ensure_schema(self) -> None:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                        chunk_id TEXT PRIMARY KEY,
                        document_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        policy_type TEXT NOT NULL,
                        version TEXT NOT NULL,
                        effective_date DATE NOT NULL,
                        expiration_date DATE,
                        section_label TEXT NOT NULL,
                        section_title TEXT NOT NULL,
                        page_number INTEGER NOT NULL CHECK (page_number > 0),
                        chunk_index INTEGER NOT NULL CHECK (chunk_index > 0),
                        content TEXT NOT NULL CHECK (content <> ''),
                        embedding vector(384) NOT NULL
                    )
                    """
                )
            connection.commit()
        except Exception as error:
            connection.rollback()
            raise PgvectorIntegrationError(f"Could not create {TABLE_NAME}: {error}") from error

    def rebuild(self, chunks: list[PolicyChunk], persisted: PersistedEmbeddings) -> int:
        """Replace only the dedicated generated index table inside one transaction."""
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise PgvectorIntegrationError("Canonical chunk IDs must be unique")
        if persisted.vectors.shape != (len(chunks), EMBEDDING_DIMENSION):
            raise PgvectorIntegrationError("Embeddings do not align with canonical chunks")
        self.ensure_schema()
        connection = self._connection()
        try:
            from pgvector import Vector

            rows = [
                (
                    chunk.chunk_id, chunk.document_id, chunk.title, chunk.policy_type, chunk.version,
                    date.fromisoformat(chunk.effective_date),
                    date.fromisoformat(chunk.expiration_date) if chunk.expiration_date else None,
                    chunk.section_label, chunk.section_title, chunk.page_number, chunk.chunk_index, chunk.content,
                    Vector(vector),
                )
                for chunk, vector in zip(chunks, persisted.vectors, strict=True)
            ]
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {TABLE_NAME}")
                cursor.executemany(
                    f"""INSERT INTO {TABLE_NAME} (
                        chunk_id, document_id, title, policy_type, version, effective_date, expiration_date,
                        section_label, section_title, page_number, chunk_index, content, embedding
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    rows,
                )
                cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
                count = int(cursor.fetchone()[0])
            if count != len(chunks):
                raise PgvectorIntegrationError(f"Inserted {count} rows for {len(chunks)} canonical chunks")
            connection.commit()
            return count
        except Exception as error:
            connection.rollback()
            raise PgvectorIntegrationError(f"Could not load canonical policy chunks: {error}") from error

    def versions(self) -> dict[str, str]:
        connection = self._connection()
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version")
            postgres_version = str(cursor.fetchone()[0])
            cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            row = cursor.fetchone()
        if row is None:
            raise PgvectorIntegrationError("pgvector extension is not installed in the target database")
        return {"postgresql": postgres_version, "pgvector": str(row[0])}

    def retrieve_exact_cosine(self, query_vector: np.ndarray, target_date: date, top_k: int) -> list[RetrievalResult]:
        if top_k < 1:
            raise PolicyRetrievalError("top_k must be positive")
        if query_vector.shape != (EMBEDDING_DIMENSION,):
            raise PgvectorIntegrationError("Query embedding must have 384 dimensions")
        connection = self._connection()
        try:
            from pgvector import Vector

            with connection.cursor() as cursor:
                # Validity filtering is intentionally part of the SQL candidate set before vector ranking.
                cursor.execute(
                    f"""
                    SELECT chunk_id, document_id, title, version, section_label, section_title, page_number, content,
                           embedding <=> %s AS cosine_distance
                    FROM {TABLE_NAME}
                    WHERE effective_date <= %s
                      AND (expiration_date IS NULL OR expiration_date >= %s)
                    ORDER BY cosine_distance ASC, chunk_id ASC
                    LIMIT %s
                    """,
                    (Vector(query_vector), target_date, target_date, top_k),
                )
                rows = cursor.fetchall()
        except Exception as error:
            raise PgvectorIntegrationError(f"pgvector exact retrieval failed: {error}") from error
        return [
            RetrievalResult(
                chunk_id=row[0], document_id=row[1], title=row[2], version=row[3],
                section_label=row[4], section_title=row[5], page_number=row[6], content=row[7],
                score=1.0 - float(row[8]), retrieval_method="pgvector_exact_cosine",
            )
            for row in rows
        ]


class PgvectorPolicyRetriever:
    """The dense-only PostgreSQL counterpart to the Phase 2D local exact oracle."""

    def __init__(self, store: PgvectorPolicyStore, dense_encoder: Any) -> None:
        self.store = store
        self.dense_encoder = dense_encoder

    def retrieve(
        self,
        query: str,
        target_date: date | str | None = None,
        top_k: int = 5,
        mode: Literal["dense"] = "dense",
    ) -> list[RetrievalResult]:
        if mode != "dense":
            raise PolicyRetrievalError("PgvectorPolicyRetriever supports dense exact retrieval only")
        resolved_date = EVAL_AS_OF_DATE if target_date is None else date.fromisoformat(target_date) if isinstance(target_date, str) else target_date
        return self.store.retrieve_exact_cosine(self.dense_encoder.encode_query(query), resolved_date, top_k)

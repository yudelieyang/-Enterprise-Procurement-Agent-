from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pypdf import PdfReader
from rank_bm25 import BM25Okapi

from procurement_agent.policy.corpus import MANIFEST_PATH, POLICY_DIR, document_applies_on, load_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVAL_AS_OF_DATE = date(2026, 6, 30)
DEFAULT_DENSE_MODEL = "sentence-transformers/multi-qa-MiniLM-L6-cos-v1"
CHUNK_REGISTRY_PATH = POLICY_DIR.parent / "retrieval" / "policy_chunks.jsonl"
EMBEDDING_PATH = POLICY_DIR.parent / "retrieval" / "policy_embeddings.npz"
EMBEDDING_METADATA_PATH = POLICY_DIR.parent / "retrieval" / "policy_embedding_metadata.json"
SECTION_HEADING = re.compile(r"^Section (?P<number>\d+(?:\.\d+)*)\s+(?P<title>.+)$")
TOKEN = re.compile(r"[a-z0-9]+")
RRF_K = 60
MODEL_CACHE_DIR = PROJECT_ROOT / ".cache" / "huggingface"


class PolicyRetrievalError(ValueError):
    """Raised when PDF ingestion or a bounded retrieval request is invalid."""


@dataclass(frozen=True)
class PolicyChunk:
    chunk_id: str
    document_id: str
    title: str
    policy_type: str
    version: str
    effective_date: str
    expiration_date: str | None
    section_label: str
    section_title: str
    page_number: int
    chunk_index: int
    content: str
    source_filename: str
    pdf_filename: str

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "PolicyChunk":
        return cls(**row)


@dataclass(frozen=True)
class RetrievalResult:
    chunk_id: str
    document_id: str
    title: str
    version: str
    section_label: str
    section_title: str
    page_number: int
    content: str
    score: float
    retrieval_method: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _stable_chunk_id(document: dict[str, Any], page_number: int, section_label: str, chunk_index: int) -> str:
    section_number = section_label.removeprefix("Section ").replace(".", "_")
    return f"{document['document_id']}:{document['version']}:p{page_number}:s{section_number}:c{chunk_index}"


def _split_section_content(content: str, max_chars: int = 1800) -> list[str]:
    """Split only unusually large sections at paragraph boundaries; policy PDFs currently need no split."""
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", content) if paragraph.strip()]
    parts: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > max_chars:
            parts.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        parts.append(current)
    return parts


def _page_sections(page_text: str) -> list[tuple[str, str, str]]:
    lines = [line.strip() for line in page_text.splitlines()]
    matches = [(index, SECTION_HEADING.match(line)) for index, line in enumerate(lines)]
    headings = [(index, match) for index, match in matches if match]
    if not headings:
        return []
    sections: list[tuple[str, str, str]] = []
    for position, (start, heading) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        body_lines = [line for line in lines[start + 1:end] if line]
        body = _normalize_space(" ".join(body_lines))
        section_label = f"Section {heading.group('number')}"
        section_title = heading.group("title")
        sections.append((section_label, section_title, f"{section_label} {section_title}\n{body}".strip()))
    return sections


def build_policy_chunks(policy_dir: Path = POLICY_DIR, manifest_path: Path = MANIFEST_PATH) -> list[PolicyChunk]:
    """Extract section-aware chunks from generated PDFs only; Markdown is never read here."""
    manifest = load_manifest(manifest_path)
    chunks: list[PolicyChunk] = []
    for document in manifest["documents"]:
        pdf_path = policy_dir / document["pdf_filename"]
        if not pdf_path.is_file():
            raise PolicyRetrievalError(f"Missing policy PDF: {pdf_path}")
        expected_sections = {(section["expected_page"], section["label"], section["title"]) for section in document["sections"]}
        actual_sections: set[tuple[int, str, str]] = set()
        reader = PdfReader(str(pdf_path))
        for page_number, page in enumerate(reader.pages, start=1):
            for section_label, section_title, content in _page_sections(page.extract_text() or ""):
                actual_sections.add((page_number, section_label, section_title))
                for chunk_index, passage in enumerate(_split_section_content(content), start=1):
                    if not passage.strip():
                        raise PolicyRetrievalError(f"Empty passage in {document['document_id']} page {page_number}")
                    chunks.append(PolicyChunk(
                        chunk_id=_stable_chunk_id(document, page_number, section_label, chunk_index),
                        document_id=document["document_id"], title=document["title"], policy_type=document["document_type"],
                        version=document["version"], effective_date=document["effective_date"], expiration_date=document["expiration_date"],
                        section_label=section_label, section_title=section_title, page_number=page_number, chunk_index=chunk_index,
                        content=passage, source_filename=document["source_filename"], pdf_filename=document["pdf_filename"],
                    ))
        if actual_sections != expected_sections:
            missing = expected_sections - actual_sections
            unexpected = actual_sections - expected_sections
            raise PolicyRetrievalError(f"Section extraction mismatch for {document['document_id']}: missing={missing}, unexpected={unexpected}")
    return sorted(chunks, key=lambda chunk: chunk.chunk_id)


def chunk_registry_hash(chunks: list[PolicyChunk]) -> str:
    serialized = "\n".join(json.dumps(asdict(chunk), sort_keys=True, separators=(",", ":")) for chunk in chunks)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def write_chunk_registry(chunks: list[PolicyChunk], path: Path = CHUNK_REGISTRY_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(asdict(chunk), sort_keys=True) + "\n" for chunk in chunks), encoding="utf-8")
    return path


def load_chunk_registry(path: Path = CHUNK_REGISTRY_PATH) -> list[PolicyChunk]:
    return [PolicyChunk.from_dict(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line]


def retrieval_text(chunk: PolicyChunk) -> str:
    return "\n".join((
        f"Document Title: {chunk.title}",
        f"Policy Type: {chunk.policy_type.replace('_', ' ')}",
        f"Version: {chunk.version}",
        f"{chunk.section_label} - {chunk.section_title}",
        "",
        chunk.content,
    ))


def _tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def _as_date(target_date: date | str | None) -> date:
    if target_date is None:
        return EVAL_AS_OF_DATE
    return date.fromisoformat(target_date) if isinstance(target_date, str) else target_date


def reciprocal_rank_fusion(rankings: list[list[tuple[int, float]]], rrf_k: int = RRF_K) -> list[tuple[int, float]]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, (index, _) in enumerate(ranking, start=1):
            fused[index] = fused.get(index, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(fused.items(), key=lambda item: (-item[1], item[0]))


class DenseEncoder:
    """Small direct Sentence Transformers adapter; no LangChain wrapper or vector store."""

    def __init__(self, model_name: str = DEFAULT_DENSE_MODEL) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model = SentenceTransformer(model_name, device="cpu", cache_folder=str(MODEL_CACHE_DIR))

    def _encode(self, method_name: str, texts: list[str]) -> np.ndarray:
        method = getattr(self.model, method_name, self.model.encode)
        try:
            vectors = method(texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
        except TypeError:
            vectors = self.model.encode(texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vectors, dtype=np.float32)

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode("encode_document", texts)

    def encode_query(self, text: str) -> np.ndarray:
        return self._encode("encode_query", [text])[0]


class PolicyRetriever:
    """Temporal pre-filter followed by deterministic lexical, exact dense, or RRF retrieval."""

    def __init__(self, chunks: list[PolicyChunk], dense_encoder: DenseEncoder | None = None) -> None:
        if not chunks:
            raise PolicyRetrievalError("PolicyRetriever needs at least one chunk")
        self.chunks = chunks
        self._document_by_id = {chunk.document_id: {"effective_date": chunk.effective_date, "expiration_date": chunk.expiration_date} for chunk in chunks}
        self.dense_encoder = dense_encoder
        self._document_embeddings: np.ndarray | None = None

    def _candidate_indexes(self, target_date: date) -> list[int]:
        return [
            index for index, chunk in enumerate(self.chunks)
            if document_applies_on(self._document_by_id[chunk.document_id], target_date)
        ]

    def _rank_lexical(self, query: str, indexes: list[int]) -> list[tuple[int, float]]:
        bm25 = BM25Okapi([_tokens(retrieval_text(self.chunks[index])) for index in indexes])
        scores = bm25.get_scores(_tokens(query))
        return sorted(zip(indexes, map(float, scores)), key=lambda item: (-item[1], self.chunks[item[0]].chunk_id))

    def _rank_dense(self, query: str, indexes: list[int]) -> list[tuple[int, float]]:
        if self.dense_encoder is None:
            raise PolicyRetrievalError("Dense mode requires a DenseEncoder")
        if self._document_embeddings is None:
            self._document_embeddings = self.dense_encoder.encode_documents([retrieval_text(chunk) for chunk in self.chunks])
        query_embedding = self.dense_encoder.encode_query(query)
        scores = self._document_embeddings[indexes] @ query_embedding
        return sorted(zip(indexes, map(float, scores)), key=lambda item: (-item[1], self.chunks[item[0]].chunk_id))

    def retrieve(
        self,
        query: str,
        target_date: date | str | None = None,
        top_k: int = 5,
        mode: Literal["lexical", "dense", "hybrid"] = "dense",
    ) -> list[RetrievalResult]:
        if top_k < 1:
            raise PolicyRetrievalError("top_k must be positive")
        if mode not in {"lexical", "dense", "hybrid"}:
            raise PolicyRetrievalError(f"Unknown retrieval mode: {mode}")
        indexes = self._candidate_indexes(_as_date(target_date))
        if not indexes:
            return []
        if mode == "lexical":
            ranked, method = self._rank_lexical(query, indexes), "lexical_bm25"
        elif mode == "dense":
            ranked, method = self._rank_dense(query, indexes), "dense_exact_cosine"
        else:
            lexical = self._rank_lexical(query, indexes)
            dense = self._rank_dense(query, indexes)
            ranked = reciprocal_rank_fusion([lexical, dense])
            ranked = sorted(ranked, key=lambda item: (-item[1], self.chunks[item[0]].chunk_id))
            method = "hybrid_rrf"
        return [
            RetrievalResult(
                chunk_id=self.chunks[index].chunk_id, document_id=self.chunks[index].document_id,
                title=self.chunks[index].title, version=self.chunks[index].version,
                section_label=self.chunks[index].section_label, section_title=self.chunks[index].section_title,
                page_number=self.chunks[index].page_number, content=self.chunks[index].content,
                score=score, retrieval_method=method,
            )
            for index, score in ranked[:top_k]
        ]

    def embedding_artifacts(self) -> tuple[np.ndarray, dict[str, Any]]:
        if self.dense_encoder is None:
            raise PolicyRetrievalError("Embedding artifacts require a DenseEncoder")
        if self._document_embeddings is None:
            self._document_embeddings = self.dense_encoder.encode_documents([retrieval_text(chunk) for chunk in self.chunks])
        import sentence_transformers

        return self._document_embeddings, {
            "model_name": self.dense_encoder.model_name,
            "embedding_dimension": int(self._document_embeddings.shape[1]),
            "sentence_transformers_version": sentence_transformers.__version__,
            "encoding": {"device": "cpu", "normalize_embeddings": True, "similarity": "exact dot product on normalized vectors (cosine equivalent)"},
            "chunk_count": len(self.chunks),
            "chunk_registry_hash": chunk_registry_hash(self.chunks),
        }


def write_embedding_artifacts(retriever: PolicyRetriever, embeddings_path: Path = EMBEDDING_PATH, metadata_path: Path = EMBEDDING_METADATA_PATH) -> dict[str, Any]:
    embeddings, metadata = retriever.embedding_artifacts()
    embeddings_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(embeddings_path, embeddings=embeddings, chunk_ids=np.array([chunk.chunk_id for chunk in retriever.chunks]))
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metadata

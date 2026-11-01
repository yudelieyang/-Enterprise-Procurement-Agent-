from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from time import perf_counter
from typing import Any, Literal

from procurement_agent.retrieval.policy_retrieval import DenseEncoder, EVAL_AS_OF_DATE, PolicyRetrievalError, PolicyRetriever, load_chunk_registry
from procurement_agent.tools.models import ToolInputError, ToolResponse, failure_response, parse_date, success_response


TOOL_NAME = "retrieve_procurement_policy"
DESCRIPTION = "Retrieve temporally applicable procurement-policy passages with document, version, section, page, and source evidence."


@dataclass(frozen=True)
class PolicyRetrievalToolInput:
    query: str
    target_date: date | str | None = None
    top_k: int = 5
    retrieval_mode: Literal["lexical", "dense", "hybrid"] = "hybrid"

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ToolInputError("query must not be empty")
        if not 1 <= self.top_k <= 10:
            raise ToolInputError("top_k must be between 1 and 10")
        if self.retrieval_mode not in {"lexical", "dense", "hybrid"}:
            raise ToolInputError("retrieval_mode must be lexical, dense, or hybrid")
        object.__setattr__(self, "target_date", parse_date(self.target_date, "target_date", EVAL_AS_OF_DATE))

    @classmethod
    def from_value(cls, value: "PolicyRetrievalToolInput | dict[str, Any]") -> "PolicyRetrievalToolInput":
        return value if isinstance(value, cls) else cls(**value)


@dataclass(frozen=True)
class PolicyEvidence:
    chunk_id: str
    document_id: str
    title: str
    version: str
    effective_date: str
    expiration_date: str | None
    section_label: str
    section_title: str
    page_number: int
    content: str
    score: float
    rank: int
    retrieval_method: str


@dataclass(frozen=True)
class PolicyRetrievalToolResult:
    status: Literal["EVIDENCE_FOUND", "NO_APPLICABLE_POLICY_EVIDENCE"]
    target_date: date
    retrieval_mode: str
    evidence: tuple[PolicyEvidence, ...]
    backend: str


class PolicyRetrievalTool:
    name = TOOL_NAME
    description = DESCRIPTION
    input_type = PolicyRetrievalToolInput

    def __init__(self, retriever: PolicyRetriever | None = None) -> None:
        self._retriever = retriever

    @property
    def retriever(self) -> PolicyRetriever:
        if self._retriever is None:
            self._retriever = PolicyRetriever(load_chunk_registry(), DenseEncoder())
        return self._retriever

    def execute(self, value: PolicyRetrievalToolInput | dict[str, Any]) -> ToolResponse[PolicyRetrievalToolResult]:
        started_at, started_clock = datetime.now(timezone.utc), perf_counter()
        try:
            request = PolicyRetrievalToolInput.from_value(value)
            results = self.retriever.retrieve(request.query, request.target_date, request.top_k, request.retrieval_mode)
        except ToolInputError as error:
            return failure_response(self.name, "local_pdf_chunk_registry", started_at, started_clock, "VALIDATION_ERROR", str(error))
        except PolicyRetrievalError as error:
            return failure_response(self.name, "local_pdf_chunk_registry", started_at, started_clock, "RETRIEVAL_EXECUTION_ERROR", str(error))
        except Exception:
            return failure_response(self.name, "local_pdf_chunk_registry", started_at, started_clock, "RETRIEVAL_EXECUTION_ERROR", "Policy retrieval failed.")
        chunks = {chunk.chunk_id: chunk for chunk in self.retriever.chunks}
        evidence = tuple(
            PolicyEvidence(result.chunk_id, result.document_id, result.title, result.version, chunks[result.chunk_id].effective_date,
                           chunks[result.chunk_id].expiration_date, result.section_label, result.section_title, result.page_number,
                           result.content, result.score, rank, result.retrieval_method)
            for rank, result in enumerate(results, start=1)
        )
        outcome = PolicyRetrievalToolResult("EVIDENCE_FOUND" if evidence else "NO_APPLICABLE_POLICY_EVIDENCE", request.target_date, request.retrieval_mode, evidence, "local_pdf_chunk_registry")
        return success_response(self.name, "local_pdf_chunk_registry", started_at, started_clock, outcome)

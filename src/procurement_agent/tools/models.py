"""Typed, framework-neutral contracts shared by the four Agent-facing tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from time import perf_counter
from typing import Any, Generic, TypeVar
from uuid import uuid4


T = TypeVar("T")


class ToolInputError(ValueError):
    """Raised only while decoding invalid external tool arguments."""


def json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime, Decimal)):
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def parse_date(value: date | str | None, field_name: str, default: date | None = None) -> date:
    if value is None:
        if default is not None:
            return default
        raise ToolInputError(f"{field_name} is required")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ToolInputError(f"{field_name} must be an ISO date") from error


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolExecutionMetadata:
    call_id: str
    tool_name: str
    started_at: datetime
    ended_at: datetime
    duration_ms: float
    success: bool
    backend: str


@dataclass(frozen=True)
class ToolCallRecord:
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    started_at: datetime
    ended_at: datetime
    duration_ms: float
    success: bool
    result_summary: dict[str, Any] | None
    error: ToolError | None


@dataclass(frozen=True)
class ToolResponse(Generic[T]):
    metadata: ToolExecutionMetadata
    result: T | None = None
    error: ToolError | None = None

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))

    def to_call_record(self, arguments: dict[str, Any]) -> ToolCallRecord:
        return ToolCallRecord(
            self.metadata.call_id, self.metadata.tool_name, json_value(arguments), self.metadata.started_at,
            self.metadata.ended_at, self.metadata.duration_ms, self.metadata.success,
            {"result_type": type(self.result).__name__} if self.result is not None else None, self.error,
        )


def _failure(tool_name: str, backend: str, started_at: datetime, started_clock: float, error: ToolError) -> ToolResponse[Any]:
    return ToolResponse(_metadata(tool_name, backend, started_at, started_clock, False), error=error)


def _metadata(tool_name: str, backend: str, started_at: datetime, started_clock: float, success: bool) -> ToolExecutionMetadata:
    ended_at = datetime.now(timezone.utc)
    return ToolExecutionMetadata(str(uuid4()), tool_name, started_at, ended_at, round((perf_counter() - started_clock) * 1000, 3), success, backend)


def failure_response(tool_name: str, backend: str, started_at: datetime, started_clock: float, code: str, message: str, *, retryable: bool = False, details: dict[str, Any] | None = None) -> ToolResponse[Any]:
    return _failure(tool_name, backend, started_at, started_clock, ToolError(code, message, retryable, details))


def success_response(tool_name: str, backend: str, started_at: datetime, started_clock: float, result: T) -> ToolResponse[T]:
    return ToolResponse(_metadata(tool_name, backend, started_at, started_clock, True), result=result)

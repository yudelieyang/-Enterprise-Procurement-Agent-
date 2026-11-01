from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from sqlalchemy.engine import Engine

from procurement_agent.database.query import QueryResult, ReadOnlyQueryError, ResultLimitExceeded, execute_readonly_query
from procurement_agent.tools.models import ToolInputError, ToolResponse, failure_response, success_response


TOOL_NAME = "query_procurement_database"
DESCRIPTION = "Query structured procurement tables using read-only SQL for suppliers, purchase orders, categories, contracts, approvals, and spend facts."


@dataclass(frozen=True)
class SqlToolInput:
    sql: str
    max_rows: int = 100

    def __post_init__(self) -> None:
        if not self.sql.strip():
            raise ToolInputError("sql must not be empty")
        if not 1 <= self.max_rows <= 100:
            raise ToolInputError("max_rows must be between 1 and 100")

    @classmethod
    def from_value(cls, value: "SqlToolInput | dict[str, Any]") -> "SqlToolInput":
        return value if isinstance(value, cls) else cls(**value)


@dataclass(frozen=True)
class SqlToolResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    max_rows: int


class SqlTool:
    name = TOOL_NAME
    description = DESCRIPTION
    input_type = SqlToolInput

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def execute(self, value: SqlToolInput | dict[str, Any]) -> ToolResponse[SqlToolResult]:
        started_at, started_clock = datetime.now(timezone.utc), perf_counter()
        try:
            request = SqlToolInput.from_value(value)
            result: QueryResult = execute_readonly_query(self.engine, request.sql, request.max_rows)
        except ToolInputError as error:
            return failure_response(self.name, "sqlite", started_at, started_clock, "VALIDATION_ERROR", str(error))
        except ReadOnlyQueryError as error:
            return failure_response(self.name, "sqlite", started_at, started_clock, "SQL_SAFETY_VIOLATION", str(error))
        except ResultLimitExceeded as error:
            return failure_response(self.name, "sqlite", started_at, started_clock, "ROW_LIMIT_EXCEEDED", str(error))
        except Exception:
            return failure_response(self.name, "sqlite", started_at, started_clock, "SQL_EXECUTION_ERROR", "Read-only SQL execution failed.")
        return success_response(self.name, "sqlite", started_at, started_clock, SqlToolResult(result.columns, result.rows, result.row_count, False, request.max_rows))

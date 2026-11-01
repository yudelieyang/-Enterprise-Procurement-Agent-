from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from time import perf_counter
from typing import Any, Literal

from sqlalchemy.engine import Engine

from procurement_agent.analytics.analytics import analyze_price_outliers, analyze_single_source_risk, analyze_spend_growth
from procurement_agent.analytics.models import PriceGroupResult, SingleSourceRiskResult, SpendGrowthResult
from procurement_agent.tools.models import ToolInputError, ToolResponse, failure_response, parse_date, success_response


TOOL_NAME = "analyze_procurement_data"
DESCRIPTION = "Run predefined deterministic procurement analyses such as spend drivers, comparable-item price outliers, and supplier concentration."
AnalyticsOperation = Literal["supplier_spend_growth", "supplier_spend_drivers", "price_outliers", "supplier_concentration"]


@dataclass(frozen=True)
class AnalyticsToolInput:
    operation: AnalyticsOperation
    supplier_code: str | None = None
    comparison_start: date | str | None = None
    comparison_end: date | str | None = None
    current_start: date | str | None = None
    current_end: date | str | None = None
    item_code: str | None = None
    unit_of_measure: str | None = None
    category_code: str | None = None
    start_date: date | str | None = None
    end_date: date | str | None = None

    def __post_init__(self) -> None:
        if self.operation not in {"supplier_spend_growth", "supplier_spend_drivers", "price_outliers", "supplier_concentration"}:
            raise ToolInputError("operation is unsupported")
        if self.operation in {"supplier_spend_growth", "supplier_spend_drivers"}:
            if not self.supplier_code:
                raise ToolInputError("supplier_code is required for spend analysis")
            for field in ("comparison_start", "comparison_end", "current_start", "current_end"):
                object.__setattr__(self, field, parse_date(getattr(self, field), field))
            if self.comparison_start > self.comparison_end or self.current_start > self.current_end:
                raise ToolInputError("analysis period start must not be after end")
        elif self.operation == "price_outliers":
            if not self.item_code:
                raise ToolInputError("item_code is required for price_outliers")
        else:
            if not self.category_code:
                raise ToolInputError("category_code is required for supplier_concentration")
            object.__setattr__(self, "start_date", parse_date(self.start_date, "start_date"))
            object.__setattr__(self, "end_date", parse_date(self.end_date, "end_date"))
            if self.start_date > self.end_date:
                raise ToolInputError("analysis period start must not be after end")

    @classmethod
    def from_value(cls, value: "AnalyticsToolInput | dict[str, Any]") -> "AnalyticsToolInput":
        return value if isinstance(value, cls) else cls(**value)


@dataclass(frozen=True)
class AnalyticsToolResult:
    operation: AnalyticsOperation
    result: SpendGrowthResult | tuple[PriceGroupResult, ...] | SingleSourceRiskResult


class AnalyticsTool:
    name = TOOL_NAME
    description = DESCRIPTION
    input_type = AnalyticsToolInput

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def execute(self, value: AnalyticsToolInput | dict[str, Any]) -> ToolResponse[AnalyticsToolResult]:
        started_at, started_clock = datetime.now(timezone.utc), perf_counter()
        try:
            request = AnalyticsToolInput.from_value(value)
            if request.operation in {"supplier_spend_growth", "supplier_spend_drivers"}:
                result = analyze_spend_growth(self.engine, request.supplier_code or "", request.comparison_start, request.comparison_end, request.current_start, request.current_end)
            elif request.operation == "price_outliers":
                groups = analyze_price_outliers(self.engine, request.item_code)
                result = tuple(group for group in groups if request.unit_of_measure is None or group.unit_of_measure == request.unit_of_measure)
            else:
                result = analyze_single_source_risk(self.engine, request.category_code or "", request.start_date, request.end_date)
        except ToolInputError as error:
            return failure_response(self.name, "sqlite", started_at, started_clock, "VALIDATION_ERROR", str(error))
        except ValueError as error:
            return failure_response(self.name, "sqlite", started_at, started_clock, "ENTITY_NOT_FOUND", str(error))
        except Exception:
            return failure_response(self.name, "sqlite", started_at, started_clock, "ANALYTICS_EXECUTION_ERROR", "Deterministic analytics execution failed.")
        return success_response(self.name, "sqlite", started_at, started_clock, AnalyticsToolResult(request.operation, result))

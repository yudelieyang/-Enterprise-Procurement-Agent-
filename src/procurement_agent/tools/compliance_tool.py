from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from procurement_agent.compliance.engine import ComplianceAuditError, ComplianceEngine
from procurement_agent.compliance.models import ComplianceResult
from procurement_agent.tools.models import ToolInputError, ToolResponse, failure_response, success_response


TOOL_NAME = "check_policy_compliance"
DESCRIPTION = "Evaluate a specific PO against structured executable approval and contract rules and return PASS, FAIL, or REVIEW with provenance."


@dataclass(frozen=True)
class ComplianceToolInput:
    po_number: str

    def __post_init__(self) -> None:
        if not self.po_number.strip():
            raise ToolInputError("po_number must not be empty")

    @classmethod
    def from_value(cls, value: "ComplianceToolInput | dict[str, Any]") -> "ComplianceToolInput":
        return value if isinstance(value, cls) else cls(**value)


class ComplianceTool:
    name = TOOL_NAME
    description = DESCRIPTION
    input_type = ComplianceToolInput

    def __init__(self, engine: ComplianceEngine) -> None:
        self.engine = engine

    def execute(self, value: ComplianceToolInput | dict[str, Any]) -> ToolResponse[ComplianceResult]:
        started_at, started_clock = datetime.now(timezone.utc), perf_counter()
        try:
            request = ComplianceToolInput.from_value(value)
            result = self.engine.audit(request.po_number)
        except ToolInputError as error:
            return failure_response(self.name, "sqlite_policy_rules", started_at, started_clock, "VALIDATION_ERROR", str(error))
        except ComplianceAuditError as error:
            code = "ENTITY_NOT_FOUND" if str(error).startswith("Unknown purchase order:") else "COMPLIANCE_AUDIT_ERROR"
            return failure_response(self.name, "sqlite_policy_rules", started_at, started_clock, code, str(error))
        except Exception:
            return failure_response(self.name, "sqlite_policy_rules", started_at, started_clock, "COMPLIANCE_EXECUTION_ERROR", "Deterministic compliance evaluation failed.")
        return success_response(self.name, "sqlite_policy_rules", started_at, started_clock, result)

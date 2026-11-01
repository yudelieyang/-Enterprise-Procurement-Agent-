"""Plain-Python registry; framework adapters belong in a later phase."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from procurement_agent.compliance.engine import ComplianceEngine, DEFAULT_DATABASE_PATH
from procurement_agent.database.connection import sqlite_engine
from procurement_agent.tools.analytics_tool import AnalyticsTool
from procurement_agent.tools.compliance_tool import ComplianceTool
from procurement_agent.tools.policy_tool import PolicyRetrievalTool
from procurement_agent.tools.sql_tool import SqlTool


TOOL_REGISTRY = {
    "query_procurement_database": SqlTool,
    "retrieve_procurement_policy": PolicyRetrievalTool,
    "analyze_procurement_data": AnalyticsTool,
    "check_policy_compliance": ComplianceTool,
}


@dataclass
class ToolRegistry:
    tools: dict[str, Any]
    database_engine: Any

    def get(self, tool_name: str) -> Any:
        return self.tools[tool_name]

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        return self.get(tool_name).execute(arguments)

    def definitions(self) -> dict[str, dict[str, Any]]:
        return {name: {"name": tool.name, "description": tool.description, "input_type": tool.input_type} for name, tool in self.tools.items()}

    def close(self) -> None:
        self.database_engine.dispose()


def create_tool_registry(database_path: Path = DEFAULT_DATABASE_PATH) -> ToolRegistry:
    database_engine = sqlite_engine(database_path)
    tools = {
        "query_procurement_database": SqlTool(database_engine),
        "retrieve_procurement_policy": PolicyRetrievalTool(),
        "analyze_procurement_data": AnalyticsTool(database_engine),
        "check_policy_compliance": ComplianceTool(ComplianceEngine(database_engine)),
    }
    return ToolRegistry(tools, database_engine)

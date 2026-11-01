"""OpenAI function schemas for the four frozen Phase 3A tool contracts."""

from __future__ import annotations

from typing import Any

from procurement_agent.tools.registry import TOOL_REGISTRY


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """Represent optional Phase 3A arguments in OpenAI strict-schema form."""

    return {"anyOf": [schema, {"type": "null"}]}


def _function(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    """Emit strict function schemas accepted by ``chat.completions.parse``.

    OpenAI strict schemas require every object property to be listed in
    ``required``. Values that are optional at the Phase 3A boundary are made
    nullable instead; the canonical dataclass input models already accept None
    and apply their existing defaults/validation.
    """

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "strict": True,
            "parameters": {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)},
        },
    }


def openai_tool_schemas() -> list[dict[str, Any]]:
    """Return schemas without wrapping or changing the canonical Python tools."""

    definitions = {
        "query_procurement_database": _function(
            "query_procurement_database", TOOL_REGISTRY["query_procurement_database"].description,
            {"sql": {"type": "string", "description": "One read-only SELECT or WITH ... SELECT statement."}, "max_rows": {"type": "integer", "minimum": 1, "maximum": 100}},
        ),
        "retrieve_procurement_policy": _function(
            "retrieve_procurement_policy", TOOL_REGISTRY["retrieve_procurement_policy"].description,
            {"query": {"type": "string"}, "target_date": _nullable({"type": "string", "format": "date", "description": "ISO policy applicability date; null applies the fixed 2026-06-30 default."}), "top_k": {"type": "integer", "minimum": 1, "maximum": 10}, "retrieval_mode": {"type": "string", "enum": ["lexical", "dense", "hybrid"]}},
        ),
        "analyze_procurement_data": _function(
            "analyze_procurement_data", TOOL_REGISTRY["analyze_procurement_data"].description,
            {"operation": {"type": "string", "enum": ["supplier_spend_growth", "supplier_spend_drivers", "price_outliers", "supplier_concentration"]}, "supplier_code": _nullable({"type": "string"}), "comparison_start": _nullable({"type": "string", "format": "date"}), "comparison_end": _nullable({"type": "string", "format": "date"}), "current_start": _nullable({"type": "string", "format": "date"}), "current_end": _nullable({"type": "string", "format": "date"}), "item_code": _nullable({"type": "string"}), "unit_of_measure": _nullable({"type": "string"}), "category_code": _nullable({"type": "string"}), "start_date": _nullable({"type": "string", "format": "date"}), "end_date": _nullable({"type": "string", "format": "date"})},
        ),
        "check_policy_compliance": _function(
            "check_policy_compliance", TOOL_REGISTRY["check_policy_compliance"].description,
            {"po_number": {"type": "string", "description": "Purchase-order number, for example PO-2026-1842."}},
        ),
    }
    assert set(definitions) == set(TOOL_REGISTRY)
    return [definitions[name] for name in TOOL_REGISTRY]

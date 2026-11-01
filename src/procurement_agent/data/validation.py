from __future__ import annotations

import csv
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from .generator import END_DATE, START_DATE, compliance_results, ground_truth, money, outlier_summary, parse_day


def validate_dataset(data: dict[str, list[dict[str, str]]], seed: int | None = None) -> dict[str, Any]:
    for table in ("business_units", "categories", "suppliers", "purchase_orders", "purchase_order_items", "contracts", "approvals", "supplier_category_eligibility"):
        assert table in data and data[table], f"Missing or empty table: {table}"
    assert len(data["business_units"]) == 4
    assert len(data["categories"]) == 6
    assert len(data["suppliers"]) == 25
    assert 460 <= len(data["purchase_orders"]) <= 500
    assert 820 <= len(data["purchase_order_items"]) <= 900

    suppliers = {row["supplier_id"] for row in data["suppliers"]}
    business_units = {row["business_unit_id"] for row in data["business_units"]}
    categories = {row["category_id"]: row for row in data["categories"]}
    contracts = {row["contract_id"]: row for row in data["contracts"]}
    po_by_number = {row["po_number"]: row for row in data["purchase_orders"]}
    assert len(po_by_number) == len(data["purchase_orders"])
    assert {"CAT-IT", "CAT-PRO"} == {row["category_id"] for row in data["categories"] if row["contract_required"] == "true"}

    items_by_po: dict[str, list[dict[str, str]]] = defaultdict(list)
    for item in data["purchase_order_items"]:
        assert item["po_number"] in po_by_number, f"Unknown item PO: {item['po_number']}"
        assert Decimal(item["quantity"]) > 0
        assert money(item["line_amount_usd"]) >= 0
        items_by_po[item["po_number"]].append(item)
    for po in data["purchase_orders"]:
        assert po["supplier_id"] in suppliers
        assert po["business_unit_id"] in business_units
        assert po["category_id"] in categories
        assert po["currency"] == "USD"
        assert po["status"] in {"ISSUED", "CLOSED", "CANCELLED"}
        assert po["approval_evidence_status"] in {"COMPLETE", "UNAVAILABLE"}
        assert po["contract_evidence_status"] in {"COMPLETE", "UNAVAILABLE"}
        assert START_DATE <= parse_day(po["order_date"]) <= END_DATE
        assert money(po["total_amount_usd"]) == sum((money(item["line_amount_usd"]) for item in items_by_po[po["po_number"]]), Decimal("0.00"))
        if po["contract_id"]:
            assert po["contract_id"] in contracts
            contract = contracts[po["contract_id"]]
            assert po["contract_reference"] == contract["contract_number"]

    for contract in data["contracts"]:
        assert contract["supplier_id"] in suppliers
        assert contract["category_id"] in categories
        assert parse_day(contract["effective_date"]) <= parse_day(contract["expiration_date"])
        assert contract["status"] in {"EXECUTED", "TERMINATED"}
        if contract["status"] == "TERMINATED":
            assert contract["termination_date"]

    approval_keys: set[tuple[str, str, str]] = set()
    for approval in data["approvals"]:
        assert approval["po_number"] in po_by_number
        assert approval["approval_type"] in {"PURCHASE", "CONTRACT_EXCEPTION"}
        assert approval["status"] in {"APPROVED", "REJECTED", "PENDING", "WITHDRAWN"}
        key = (approval["po_number"], approval["approval_type"], approval["approver_id"])
        assert key not in approval_keys, f"Duplicate approval identity: {key}"
        approval_keys.add(key)
        if approval["status"] == "APPROVED":
            assert approval["approved_at"]
        else:
            assert not approval["approved_at"]

    for po, expected in {
        "PO-2026-1842": {"approval": "FAIL", "contract": "PASS", "overall": "FAIL"},
        "PO-2026-1846": {"approval": "PASS", "contract": "PASS", "overall": "PASS"},
        "PO-2026-1847": {"approval": "REVIEW", "contract": "PASS", "overall": "REVIEW"},
    }.items():
        assert compliance_results(data, po) == expected
    assert {po: compliance_results(data, po)["contract"] for po in ("PO-2026-1837", "PO-2026-1838", "PO-2026-1839", "PO-2026-1840")} == {
        "PO-2026-1837": "FAIL", "PO-2026-1838": "REVIEW", "PO-2026-1839": "FAIL", "PO-2026-1840": "PASS"
    }

    manifest = ground_truth(data, seed or 0)
    growth = manifest["sup_042_growth"]
    assert growth["h1_2025_spend_usd"] == "120000.00"
    assert growth["h1_2026_spend_usd"] == "390000.00"
    assert growth["growth_pct"] == "225.00"
    positive = manifest["single_source"]["positive"]
    assert Decimal(positive["spend_share"]) >= Decimal("0.80") and positive["qualified_supplier_count"] <= 1
    assert manifest["single_source"]["noncritical_counterexample"]["qualified_supplier_count"] >= 1
    assert manifest["single_source"]["multiple_qualified_counterexample"]["qualified_supplier_count"] > 1
    outliers = outlier_summary(data)
    assert any(item_id.startswith("PO-2025-1910") for item_id in outliers["outlier_item_ids"])
    assert any(item_id.startswith("PO-2025-2009") for item_id in outliers["outlier_item_ids"])
    assert any(group["item_code"] == "PRICE-PRD-001" for group in outliers["insufficient_groups"])
    assert not any(name in data for name in ("invoices", "payments", "receipts"))
    return manifest


def load_generated_dataset(input_dir: Path) -> tuple[dict[str, list[dict[str, str]]], dict[str, Any]]:
    table_names = ("business_units", "categories", "suppliers", "purchase_orders", "purchase_order_items", "contracts", "approvals", "supplier_category_eligibility")
    data = {}
    for table in table_names:
        with (input_dir / f"{table}.csv").open(newline="", encoding="utf-8") as handle:
            data[table] = list(csv.DictReader(handle))
    manifest = json.loads((input_dir / "ground_truth.json").read_text(encoding="utf-8"))
    return data, manifest


def main() -> None:
    data, manifest = load_generated_dataset(Path("data/generated"))
    validated = validate_dataset(data, int(manifest["seed"]))
    assert validated["row_counts"] == manifest["row_counts"]
    print("dataset validation passed")


if __name__ == "__main__":
    main()

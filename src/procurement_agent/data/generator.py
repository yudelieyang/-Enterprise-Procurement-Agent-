from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import median
from typing import Any


DEFAULT_SEED = 20260630
EVAL_AS_OF_DATE = "2026-06-30"
START_DATE = date(2025, 1, 1)
END_DATE = date(2026, 6, 30)
CENT = Decimal("0.01")
TABLES = (
    "business_units",
    "categories",
    "suppliers",
    "purchase_orders",
    "purchase_order_items",
    "contracts",
    "approvals",
    "supplier_category_eligibility",
)
GENERIC_ITEM_CODES = {"SWL-001", "ITS-001", "PRO-001", "OFF-001", "FAC-001", "PRD-001"}


def money(value: Decimal | str | int | float) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def money_text(value: Decimal | str | int | float) -> str:
    return f"{money(value):.2f}"


def iso_day(value: date) -> str:
    return value.isoformat()


def parse_day(value: str) -> date:
    return date.fromisoformat(value[:10])


def build_dataset(seed: int = DEFAULT_SEED) -> dict[str, list[dict[str, str]]]:
    rng = random.Random(seed)
    data = master_data()
    contracts_by_id = {row["contract_id"]: row for row in data["contracts"]}
    protected_po_ids: set[str] = set()

    def add_po(
        po_number: str,
        supplier_id: str,
        business_unit_id: str,
        category_id: str,
        order_date: str,
        item_specs: list[tuple[str, str, Decimal | str | int]],
        *,
        status: str = "ISSUED",
        contract_reference: str = "",
        contract_id: str = "",
        approval_evidence_status: str = "COMPLETE",
        contract_evidence_status: str = "COMPLETE",
        protected: bool = False,
    ) -> None:
        if any(row["po_number"] == po_number for row in data["purchase_orders"]):
            raise ValueError(f"Duplicate PO number: {po_number}")
        line_total = Decimal("0.00")
        for line_number, (item_code, uom, line_amount) in enumerate(item_specs, start=1):
            amount = money(line_amount)
            line_total += amount
            resolved_item_code = f"{item_code}-{po_number[-4:]}" if item_code in GENERIC_ITEM_CODES else item_code
            data["purchase_order_items"].append(
                {
                    "purchase_order_item_id": f"{po_number}-L{line_number:02d}",
                    "po_number": po_number,
                    "line_number": str(line_number),
                    "item_code": resolved_item_code,
                    "quantity": "1.00",
                    "unit_of_measure": uom,
                    "unit_price_usd": money_text(amount),
                    "line_amount_usd": money_text(amount),
                }
            )
        data["purchase_orders"].append(
            {
                "po_number": po_number,
                "supplier_id": supplier_id,
                "business_unit_id": business_unit_id,
                "category_id": category_id,
                "order_date": order_date,
                "status": status,
                "total_amount_usd": money_text(line_total),
                "currency": "USD",
                "contract_reference": contract_reference,
                "contract_id": contract_id,
                "approval_evidence_status": approval_evidence_status,
                "contract_evidence_status": contract_evidence_status,
            }
        )
        if protected:
            protected_po_ids.add(po_number)

    def add_approval(
        po_number: str,
        approval_type: str,
        status: str,
        approver_id: str,
        approver_role: str,
        approved_at: str = "",
    ) -> None:
        key = (po_number, approval_type, approver_id)
        if any((row["po_number"], row["approval_type"], row["approver_id"]) == key for row in data["approvals"]):
            raise ValueError(f"Duplicate approval identity: {key}")
        data["approvals"].append(
            {
                "approval_id": f"APR-{len(data['approvals']) + 1:04d}",
                "po_number": po_number,
                "approval_type": approval_type,
                "status": status,
                "approver_id": approver_id,
                "approver_role": approver_role,
                "approved_at": approved_at,
            }
        )

    def valid_purchase_approvals(po_number: str, order_day: str, prefix: str = "APP") -> None:
        approved_at = f"{order_day}T09:00:00"
        add_approval(po_number, "PURCHASE", "APPROVED", f"{prefix}-MGR", "MANAGER", approved_at)
        add_approval(po_number, "PURCHASE", "APPROVED", f"{prefix}-DIR", "DIRECTOR", f"{order_day}T10:00:00")

    # SUP-042 protected H1 comparison: $120k in 2025 versus $390k in 2026.
    for po, category, amount, day, contract_id, contract_ref in (
        ("PO-2025-0421", "CAT-IT", "35000", "2025-02-12", "CON-IT-042", "CON-IT-042"),
        ("PO-2025-0422", "CAT-IT", "35000", "2025-04-18", "CON-IT-042", "CON-IT-042"),
        ("PO-2025-0423", "CAT-SW", "50000", "2025-06-09", "", ""),
        ("PO-2026-1842", "CAT-IT", "72000", "2026-01-16", "CON-IT-042", "CON-IT-042"),
        ("PO-2026-1843", "CAT-IT", "95000", "2026-02-20", "CON-IT-042", "CON-IT-042"),
        ("PO-2026-1844", "CAT-IT", "40000", "2026-03-11", "CON-IT-042", "CON-IT-042"),
        ("PO-2026-1845", "CAT-IT", "33000", "2026-04-07", "", "LEGACY-UNRESOLVED-042"),
        ("PO-2026-1861", "CAT-SW", "60000", "2026-04-28", "", ""),
        ("PO-2026-1862", "CAT-SW", "50000", "2026-05-14", "", ""),
        ("PO-2026-1863", "CAT-SW", "40000", "2026-06-18", "", ""),
    ):
        item = "ITS-001" if category == "CAT-IT" else "SWL-001"
        add_po(po, "SUP-042", "BU-CORP-IT", category, day, [(item, "EA", amount)], contract_id=contract_id, contract_reference=contract_ref, protected=True)
    add_approval("PO-2026-1842", "PURCHASE", "APPROVED", "APP-042-MGR", "MANAGER", "2026-01-15T10:00:00")
    valid_purchase_approvals("PO-2026-1843", "2026-02-20", "APP-043")
    valid_purchase_approvals("PO-2026-1861", "2026-04-28", "APP-061")

    # Explicit contract cases and canonical PASS/REVIEW controls.
    cases = (
        ("PO-2026-1837", "SUP-003", "2026-01-21", "", "", "COMPLETE", "COMPLETE"),
        ("PO-2026-1838", "SUP-004", "2026-02-02", "UNRESOLVED-1838", "", "COMPLETE", "COMPLETE"),
        ("PO-2026-1839", "SUP-003", "2026-02-15", "CON-IT-EXPIRED", "CON-IT-EXPIRED", "COMPLETE", "COMPLETE"),
        ("PO-2026-1840", "SUP-003", "2026-03-03", "", "", "COMPLETE", "COMPLETE"),
        ("PO-2026-1846", "SUP-005", "2026-04-14", "CON-IT-005", "CON-IT-005", "COMPLETE", "COMPLETE"),
        ("PO-2026-1847", "SUP-005", "2026-05-08", "CON-IT-005", "CON-IT-005", "UNAVAILABLE", "COMPLETE"),
    )
    for po, supplier, day, ref, contract_id, approval_status, contract_status in cases:
        add_po(po, supplier, "BU-OPERATIONS", "CAT-IT", day, [("ITS-001", "EA", "60000")], contract_reference=ref, contract_id=contract_id, approval_evidence_status=approval_status, contract_evidence_status=contract_status, protected=True)
    for po, day, prefix in (("PO-2026-1837", "2026-01-21", "APP-837"), ("PO-2026-1838", "2026-02-02", "APP-838"), ("PO-2026-1839", "2026-02-15", "APP-839"), ("PO-2026-1840", "2026-03-03", "APP-840"), ("PO-2026-1846", "2026-04-14", "APP-846")):
        valid_purchase_approvals(po, day, prefix)
    add_approval("PO-2026-1840", "CONTRACT_EXCEPTION", "APPROVED", "EXC-840-DIR", "DIRECTOR", "2026-03-02T14:00:00")

    # Approval variants: all use a valid IT Services contract so they do not dilute the SUP-017 Professional Services pattern.
    approval_cases = (
        ("PO-2026-1848", "2026-01-28", "two_no_director"),
        ("PO-2026-1849", "2026-02-25", "rejected"),
        ("PO-2026-1850", "2026-03-24", "pending"),
        ("PO-2026-1851", "2026-04-22", "withdrawn"),
        ("PO-2026-1852", "2026-05-20", "late"),
        ("PO-2026-1853", "2026-06-11", "zero"),
    )
    for po, day, variant in approval_cases:
        add_po(po, "SUP-005", "BU-R_AND_D", "CAT-IT", day, [("ITS-001", "EA", "60000")], contract_reference="CON-IT-005", contract_id="CON-IT-005", protected=True)
        if variant == "two_no_director":
            add_approval(po, "PURCHASE", "APPROVED", "APP-848-M1", "MANAGER", f"{day}T08:00:00")
            add_approval(po, "PURCHASE", "APPROVED", "APP-848-M2", "MANAGER", f"{day}T09:00:00")
        elif variant in {"rejected", "pending", "withdrawn"}:
            status = variant.upper()
            add_approval(po, "PURCHASE", "APPROVED", f"APP-{po[-2:]}-M", "MANAGER", f"{day}T08:00:00")
            add_approval(po, "PURCHASE", status, f"APP-{po[-2:]}-D", "DIRECTOR", "")
        elif variant == "late":
            add_approval(po, "PURCHASE", "APPROVED", "APP-852-M", "MANAGER", "2026-05-21T08:00:00")
            add_approval(po, "PURCHASE", "APPROVED", "APP-852-D", "DIRECTOR", "2026-05-21T09:00:00")

    # Price groups are 2025-only so they do not disturb H1 2026 concentration cases.
    for index, price in enumerate(("98", "100", "101", "99", "102", "100", "97", "103", "99", "250"), start=1):
        add_po(f"PO-2025-19{index:02d}", f"SUP-{index:03d}", "BU-FACILITIES", "CAT-OFF", f"2025-0{1 + (index % 6)}-15", [("PRICE-OFF-001", "EA", price)], protected=True)
    for index, price in enumerate(("198", "200", "201", "199", "202", "200", "197", "203", "40"), start=1):
        add_po(f"PO-2025-20{index:02d}", f"SUP-{index + 10:03d}", "BU-FACILITIES", "CAT-FAC", f"2025-0{1 + (index % 6)}-17", [("PRICE-FAC-001", "EA", price)], protected=True)
    add_po("PO-2025-2010", "SUP-001", "BU-FACILITIES", "CAT-OFF", "2025-05-17", [("PRICE-OFF-001", "BOX", "1000")], protected=True)
    for index, price in enumerate(("500", "505", "498", "502", "501"), start=1):
        add_po(f"PO-2025-21{index:02d}", f"SUP-{index + 4:03d}", "BU-OPERATIONS", "CAT-PRD", f"2025-0{index + 1}-19", [("PRICE-PRD-001", "EA", price)], protected=True)

    # Supplier-concentration cases: H1 2026 background generation excludes these categories.
    for index, amount in enumerate(("90000", "70000", "70000", "70000"), start=1):
        po = f"PO-2026-22{index:02d}"
        day = f"2026-0{index + 1}-12"
        add_po(po, "SUP-017", "BU-R_AND_D", "CAT-PRO", day, [("PRO-001", "DAY", amount)], contract_reference="CON-PRO-017", contract_id="CON-PRO-017", protected=True)
        valid_purchase_approvals(po, day, f"APP-22{index}")
    add_po("PO-2026-2205", "SUP-004", "BU-R_AND_D", "CAT-PRO", "2026-06-10", [("PRO-001", "DAY", "30000")], contract_reference="CON-PRO-004", contract_id="CON-PRO-004", protected=True)
    for index in range(1, 5):
        add_po(f"PO-2026-23{index:02d}", "SUP-006", "BU-FACILITIES", "CAT-OFF", f"2026-0{index + 1}-16", [("OFF-001", "EA", "35000")], protected=True)
    add_po("PO-2026-2305", "SUP-007", "BU-FACILITIES", "CAT-OFF", "2026-06-16", [("OFF-001", "EA", "10000")], protected=True)
    for index in range(1, 4):
        po = f"PO-2026-24{index:02d}"
        day = f"2026-0{index + 1}-21"
        add_po(po, "SUP-008", "BU-OPERATIONS", "CAT-PRD", day, [("PRD-001", "EA", "70000")], protected=True)
        valid_purchase_approvals(po, day, f"APP-24{index}")
    add_po("PO-2026-2404", "SUP-009", "BU-OPERATIONS", "CAT-PRD", "2026-06-21", [("PRD-001", "EA", "20000")], protected=True)

    add_background_records(data, rng, protected_po_ids)
    assert len(data["purchase_orders"]) == 480
    assert 820 <= len(data["purchase_order_items"]) <= 900
    _ = contracts_by_id  # Kept for readability: planted references are validated below.
    return data


def master_data() -> dict[str, list[dict[str, str]]]:
    suppliers = [
        {"supplier_id": f"SUP-{index:03d}", "supplier_code": f"SUP-{index:03d}", "name": f"Supplier {index:03d}"}
        for index in range(1, 25)
    ]
    suppliers.append({"supplier_id": "SUP-042", "supplier_code": "SUP-042", "name": "Apex Digital Services"})
    contracts = [
        contract("CON-IT-042", "SUP-042", "CAT-IT", "EXECUTED", "2025-01-01", "2026-12-31"),
        contract("CON-IT-005", "SUP-005", "CAT-IT", "EXECUTED", "2025-01-01", "2026-12-31"),
        contract("CON-IT-001", "SUP-001", "CAT-IT", "EXECUTED", "2025-01-01", "2026-12-31"),
        contract("CON-IT-002", "SUP-002", "CAT-IT", "EXECUTED", "2025-06-01", "2026-12-31"),
        contract("CON-IT-EXPIRED", "SUP-003", "CAT-IT", "EXECUTED", "2025-01-01", "2025-12-31"),
        contract("CON-PRO-003", "SUP-003", "CAT-PRO", "EXECUTED", "2025-01-01", "2026-12-31"),
        contract("CON-PRO-017", "SUP-017", "CAT-PRO", "EXECUTED", "2025-01-01", "2026-12-31"),
        contract("CON-PRO-004", "SUP-004", "CAT-PRO", "EXECUTED", "2025-03-01", "2026-12-31"),
        contract("CON-IT-009", "SUP-009", "CAT-IT", "TERMINATED", "2025-01-01", "2026-12-31", "2026-05-01"),
        contract("CON-PRO-010", "SUP-010", "CAT-PRO", "EXECUTED", "2025-01-01", "2025-12-31"),
        contract("CON-IT-011", "SUP-011", "CAT-IT", "EXECUTED", "2026-01-01", "2026-12-31"),
        contract("CON-PRO-012", "SUP-012", "CAT-PRO", "EXECUTED", "2026-01-01", "2026-12-31"),
        contract("CON-IT-013", "SUP-013", "CAT-IT", "EXECUTED", "2025-01-01", "2026-06-30"),
    ]
    data = {
        "business_units": [
            {"business_unit_id": "BU-CORP-IT", "business_unit_code": "CORP_IT", "name": "Corporate IT"},
            {"business_unit_id": "BU-OPERATIONS", "business_unit_code": "OPERATIONS", "name": "Operations"},
            {"business_unit_id": "BU-FACILITIES", "business_unit_code": "FACILITIES", "name": "Facilities"},
            {"business_unit_id": "BU-R_AND_D", "business_unit_code": "R_AND_D", "name": "Research and Development"},
        ],
        "categories": [
            category("CAT-SW", "SOFTWARE_LICENSES", "Software Licenses", True, True, False),
            category("CAT-IT", "IT_SERVICES", "IT Services", True, True, True),
            category("CAT-PRO", "PROFESSIONAL_SERVICES", "Professional Services", True, True, True),
            category("CAT-OFF", "OFFICE_SUPPLIES", "Office Supplies", True, False, False),
            category("CAT-FAC", "FACILITIES_MAINTENANCE", "Facilities Maintenance", True, False, False),
            category("CAT-PRD", "PRODUCTION_MATERIALS", "Production Materials", False, True, False),
        ],
        "suppliers": suppliers,
        "purchase_orders": [],
        "purchase_order_items": [],
        "contracts": contracts,
        "approvals": [],
        "supplier_category_eligibility": eligibility_records(),
    }
    return data


def category(category_id: str, code: str, name: str, indirect: bool, critical: bool, contract_required: bool) -> dict[str, str]:
    return {
        "category_id": category_id,
        "category_code": code,
        "name": name,
        "procurement_class": "INDIRECT" if indirect else "DIRECT",
        "is_critical": str(critical).lower(),
        "contract_required": str(contract_required).lower(),
    }


def contract(contract_id: str, supplier_id: str, category_id: str, status: str, effective_date: str, expiration_date: str, termination_date: str = "") -> dict[str, str]:
    return {
        "contract_id": contract_id,
        "contract_number": contract_id,
        "supplier_id": supplier_id,
        "category_id": category_id,
        "status": status,
        "effective_date": effective_date,
        "expiration_date": expiration_date,
        "termination_date": termination_date,
    }


def eligibility_records() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    qualified = {
        "CAT-PRO": {"SUP-017"},
        "CAT-IT": {"SUP-002", "SUP-005", "SUP-042"},
        "CAT-PRD": {"SUP-008", "SUP-009", "SUP-010"},
        "CAT-OFF": {"SUP-006", "SUP-007", "SUP-011", "SUP-012"},
        "CAT-FAC": {"SUP-013", "SUP-014", "SUP-015", "SUP-016"},
        "CAT-SW": {"SUP-001", "SUP-003", "SUP-042"},
    }
    for category_id, supplier_ids in qualified.items():
        for supplier_id in sorted(supplier_ids):
            records.append({"supplier_id": supplier_id, "category_id": category_id, "qualification_status": "QUALIFIED"})
    for supplier_id, category_id in (("SUP-018", "CAT-PRO"), ("SUP-019", "CAT-PRO"), ("SUP-020", "CAT-IT"), ("SUP-021", "CAT-PRD"), ("SUP-022", "CAT-OFF"), ("SUP-023", "CAT-FAC"), ("SUP-024", "CAT-SW"), ("SUP-004", "CAT-IT"), ("SUP-003", "CAT-IT"), ("SUP-001", "CAT-PRO"), ("SUP-002", "CAT-FAC"), ("SUP-005", "CAT-OFF"), ("SUP-006", "CAT-SW"), ("SUP-007", "CAT-PRD"), ("SUP-008", "CAT-IT"), ("SUP-009", "CAT-PRO"), ("SUP-010", "CAT-SW"), ("SUP-011", "CAT-IT"), ("SUP-012", "CAT-PRD"), ("SUP-013", "CAT-SW"), ("SUP-014", "CAT-OFF"), ("SUP-015", "CAT-PRD"), ("SUP-016", "CAT-IT"), ("SUP-017", "CAT-FAC"), ("SUP-018", "CAT-OFF")):
        records.append({"supplier_id": supplier_id, "category_id": category_id, "qualification_status": "NOT_QUALIFIED"})
    return records


def add_background_records(data: dict[str, list[dict[str, str]]], rng: random.Random, protected_po_ids: set[str]) -> None:
    target_items = 860
    remaining_pos = 480 - len(data["purchase_orders"])
    remaining_items = target_items - len(data["purchase_order_items"])
    if not (remaining_pos <= remaining_items <= 3 * remaining_pos):
        raise AssertionError("Planted records cannot reach the target item range")
    extra_lines = remaining_items - remaining_pos
    line_counts = [1] * remaining_pos
    indices = list(range(remaining_pos))
    rng.shuffle(indices)
    for index in indices[: min(extra_lines, remaining_pos)]:
        line_counts[index] += 1
    for index in indices[remaining_pos : remaining_pos + max(0, extra_lines - remaining_pos)]:
        line_counts[index] += 1

    po_numbers = iter_background_numbers(protected_po_ids)
    supplier_ids = [row["supplier_id"] for row in data["suppliers"] if row["supplier_id"] not in {"SUP-017", "SUP-042"}]
    top_suppliers = ["SUP-001", "SUP-002", "SUP-003", "SUP-004", "SUP-005"]
    business_units = [row["business_unit_id"] for row in data["business_units"]]
    category_meta = {row["category_id"]: row for row in data["categories"]}
    item_by_category = {
        "CAT-SW": ("SWL-001", "EA"),
        "CAT-IT": ("ITS-001", "EA"),
        "CAT-PRO": ("PRO-001", "DAY"),
        "CAT-OFF": ("OFF-001", "EA"),
        "CAT-FAC": ("FAC-001", "EA"),
        "CAT-PRD": ("PRD-001", "EA"),
    }

    def append_po(po_number: str, supplier_id: str, category_id: str, order_day: date, amounts: list[Decimal]) -> None:
        line_total = sum(amounts, Decimal("0.00"))
        item_code, uom = item_by_category[category_id]
        for line_number, amount in enumerate(amounts, start=1):
            data["purchase_order_items"].append(
                {
                    "purchase_order_item_id": f"{po_number}-L{line_number:02d}",
                    "po_number": po_number,
                    "line_number": str(line_number),
            "item_code": f"{item_code}-BG-{po_number[-4:]}",
                    "quantity": "1.00",
                    "unit_of_measure": uom,
                    "unit_price_usd": money_text(amount),
                    "line_amount_usd": money_text(amount),
                }
            )
        data["purchase_orders"].append(
            {
                "po_number": po_number,
                "supplier_id": supplier_id,
                "business_unit_id": rng.choice(business_units),
                "category_id": category_id,
                "order_date": iso_day(order_day),
                "status": "CANCELLED" if rng.random() < 0.06 else rng.choice(["ISSUED", "CLOSED"]),
                "total_amount_usd": money_text(line_total),
                "currency": "USD",
                "contract_reference": "",
                "contract_id": "",
                "approval_evidence_status": "COMPLETE",
                "contract_evidence_status": "COMPLETE",
            }
        )

    for position, line_count in enumerate(line_counts):
        order_day = START_DATE + timedelta(days=rng.randrange((END_DATE - START_DATE).days + 1))
        h1_2026 = date(2026, 1, 1) <= order_day <= END_DATE
        if h1_2026:
            category_id = rng.choice(["CAT-SW", "CAT-FAC", "CAT-IT"])
            supplier_id = rng.choice(top_suppliers) if rng.random() < 0.84 else rng.choice(supplier_ids)
        else:
            category_id = rng.choice(list(category_meta))
            supplier_id = rng.choice(supplier_ids)
        total = money(rng.randint(1500, 45000))
        shares = [Decimal(rng.randint(1, 9)) for _ in range(line_count)]
        denominator = sum(shares)
        amounts = [money(total * share / denominator) for share in shares[:-1]]
        amounts.append(total - sum(amounts, Decimal("0.00")))
        append_po(next(po_numbers), supplier_id, category_id, order_day, amounts)

    # Background approvals make the data shape realistic without affecting protected compliance cases.
    for position, po in enumerate(data["purchase_orders"]):
        if po["po_number"] not in protected_po_ids and position % 3 == 0:
            data["approvals"].append(
                {
                    "approval_id": f"APR-{len(data['approvals']) + 1:04d}",
                    "po_number": po["po_number"],
                    "approval_type": "PURCHASE",
                    "status": "APPROVED",
                    "approver_id": f"BG-{position:03d}",
                    "approver_role": "MANAGER",
                    "approved_at": f"{po['order_date']}T08:00:00",
                }
            )


def iter_background_numbers(protected_po_ids: set[str]):
    number = 1000
    while True:
        candidate = f"PO-{2025 if number < 1500 else 2026}-{number:04d}"
        number += 1
        if candidate not in protected_po_ids:
            yield candidate


def compliance_results(data: dict[str, list[dict[str, str]]], po_number: str) -> dict[str, str]:
    po = next(row for row in data["purchase_orders"] if row["po_number"] == po_number)
    categories = {row["category_id"]: row for row in data["categories"]}
    contracts = {row["contract_id"]: row for row in data["contracts"]}
    approvals = [row for row in data["approvals"] if row["po_number"] == po_number]
    order_day = parse_day(po["order_date"])
    amount = money(po["total_amount_usd"])
    threshold = Decimal("75000") if order_day.year == 2025 else Decimal("50000")

    if amount <= threshold:
        approval_result = "PASS"
    elif po["approval_evidence_status"] == "UNAVAILABLE":
        approval_result = "REVIEW"
    else:
        valid = [
            row
            for row in approvals
            if row["approval_type"] == "PURCHASE"
            and row["status"] == "APPROVED"
            and row["approved_at"]
            and parse_day(row["approved_at"]) <= order_day
        ]
        approval_result = "PASS" if len({row["approver_id"] for row in valid}) >= 2 and any(row["approver_role"] == "DIRECTOR" for row in valid) else "FAIL"

    if categories[po["category_id"]]["contract_required"] != "true":
        contract_result = "PASS"
    elif po["contract_evidence_status"] == "UNAVAILABLE":
        contract_result = "REVIEW"
    elif po["contract_reference"] and not po["contract_id"]:
        contract_result = "REVIEW"
    else:
        contract_row = contracts.get(po["contract_id"])
        valid_contract = bool(contract_row) and contract_row["supplier_id"] == po["supplier_id"] and contract_row["category_id"] == po["category_id"] and parse_day(contract_row["effective_date"]) <= order_day <= parse_day(contract_row["expiration_date"]) and (contract_row["status"] == "EXECUTED" or (contract_row["status"] == "TERMINATED" and contract_row["termination_date"] and parse_day(contract_row["termination_date"]) > order_day))
        valid_exception = any(
            row["approval_type"] == "CONTRACT_EXCEPTION"
            and row["status"] == "APPROVED"
            and row["approver_role"] == "DIRECTOR"
            and row["approved_at"]
            and parse_day(row["approved_at"]) <= order_day
            for row in approvals
        )
        contract_result = "PASS" if valid_contract or valid_exception else "FAIL"

    overall = "FAIL" if "FAIL" in {approval_result, contract_result} else "REVIEW" if "REVIEW" in {approval_result, contract_result} else "PASS"
    return {"approval": approval_result, "contract": contract_result, "overall": overall}


def outlier_summary(data: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    po_by_number = {row["po_number"]: row for row in data["purchase_orders"]}
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for item in data["purchase_order_items"]:
        po = po_by_number[item["po_number"]]
        if po["status"] in {"ISSUED", "CLOSED"} and po["currency"] == "USD":
            groups[(item["item_code"], item["unit_of_measure"])].append(item)
    outliers: list[str] = []
    insufficient: list[dict[str, str | int]] = []
    for (item_code, uom), rows in sorted(groups.items()):
        prices = [money(row["unit_price_usd"]) for row in rows]
        if len(rows) < 8:
            insufficient.append({"item_code": item_code, "unit_of_measure": uom, "reason": "peer_group_lt_8", "count": len(rows)})
            continue
        center = median(prices)
        mad = median([abs(price - center) for price in prices])
        if mad == 0:
            insufficient.append({"item_code": item_code, "unit_of_measure": uom, "reason": "mad_zero", "count": len(rows)})
            continue
        for row, price in zip(rows, prices):
            robust_z = Decimal("0.6745") * (price - center) / mad
            if abs(robust_z) > Decimal("3.5"):
                outliers.append(row["purchase_order_item_id"])
    return {"outlier_item_ids": sorted(outliers), "insufficient_groups": insufficient}


def ground_truth(data: dict[str, list[dict[str, str]]], seed: int) -> dict[str, Any]:
    po_by_number = {row["po_number"]: row for row in data["purchase_orders"]}
    items_by_po: dict[str, list[dict[str, str]]] = defaultdict(list)
    for item in data["purchase_order_items"]:
        items_by_po[item["po_number"]].append(item)

    def spend_for(supplier_id: str, start: str, end: str) -> list[dict[str, str]]:
        return [row for row in data["purchase_orders"] if row["supplier_id"] == supplier_id and row["status"] in {"ISSUED", "CLOSED"} and start <= row["order_date"] <= end]

    h1_2025 = spend_for("SUP-042", "2025-01-01", "2025-06-30")
    h1_2026 = spend_for("SUP-042", "2026-01-01", "2026-06-30")
    sum_money = lambda rows: sum((money(row["total_amount_usd"]) for row in rows), Decimal("0.00"))
    spend_2025, spend_2026 = sum_money(h1_2025), sum_money(h1_2026)
    category_contribution: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for row in h1_2026:
        category_contribution[row["category_id"]] += money(row["total_amount_usd"])
    top_pos = sorted(h1_2026, key=lambda row: money(row["total_amount_usd"]), reverse=True)[:3]

    indirect_categories = {row["category_id"] for row in data["categories"] if row["procurement_class"] == "INDIRECT"}
    indirect_spend: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for row in data["purchase_orders"]:
        if row["status"] in {"ISSUED", "CLOSED"} and "2026-01-01" <= row["order_date"] <= "2026-06-30" and row["category_id"] in indirect_categories:
            indirect_spend[row["supplier_id"]] += money(row["total_amount_usd"])
    cumulative = Decimal("0.00")
    total_indirect = sum(indirect_spend.values(), Decimal("0.00"))
    pareto_suppliers: list[str] = []
    for supplier_id, amount in sorted(indirect_spend.items(), key=lambda pair: pair[1], reverse=True):
        cumulative += amount
        pareto_suppliers.append(supplier_id)
        if cumulative / total_indirect >= Decimal("0.80"):
            break

    def concentration(category_id: str, supplier_id: str) -> dict[str, Any]:
        amounts: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        for row in data["purchase_orders"]:
            if row["status"] in {"ISSUED", "CLOSED"} and row["category_id"] == category_id and "2026-01-01" <= row["order_date"] <= "2026-06-30":
                amounts[row["supplier_id"]] += money(row["total_amount_usd"])
        total = sum(amounts.values(), Decimal("0.00"))
        qualified = sum(1 for row in data["supplier_category_eligibility"] if row["category_id"] == category_id and row["qualification_status"] == "QUALIFIED")
        return {"category_id": category_id, "supplier_id": supplier_id, "spend_share": str((amounts[supplier_id] / total).quantize(Decimal("0.0001"))), "qualified_supplier_count": qualified}

    price_results = outlier_summary(data)
    return {
        "seed": seed,
        "evaluation_as_of_date": EVAL_AS_OF_DATE,
        "row_counts": {table: len(rows) for table, rows in data.items()},
        "sup_042_growth": {
            "h1_2025_spend_usd": money_text(spend_2025),
            "h1_2026_spend_usd": money_text(spend_2026),
            "absolute_increase_usd": money_text(spend_2026 - spend_2025),
            "growth_pct": str(((spend_2026 - spend_2025) / spend_2025 * Decimal("100")).quantize(Decimal("0.01"))),
            "h1_2025_po_count": len(h1_2025),
            "h1_2026_po_count": len(h1_2026),
            "h1_2025_average_po_usd": money_text(spend_2025 / len(h1_2025)),
            "h1_2026_average_po_usd": money_text(spend_2026 / len(h1_2026)),
            "h1_2026_category_contribution_usd": {key: money_text(value) for key, value in sorted(category_contribution.items())},
            "largest_h1_2026_pos": [{"po_number": row["po_number"], "amount_usd": row["total_amount_usd"]} for row in top_pos],
        },
        "pareto_indirect_h1_2026": {"supplier_set_to_80pct": pareto_suppliers, "share_at_threshold": str((cumulative / total_indirect).quantize(Decimal("0.0001")))},
        "canonical_compliance": {po: compliance_results(data, po) for po in ("PO-2026-1842", "PO-2026-1846", "PO-2026-1847")},
        "off_contract_cases": {po: compliance_results(data, po)["contract"] for po in ("PO-2026-1837", "PO-2026-1838", "PO-2026-1839", "PO-2026-1840")},
        "single_source": {
            "positive": concentration("CAT-PRO", "SUP-017"),
            "noncritical_counterexample": concentration("CAT-OFF", "SUP-006"),
            "multiple_qualified_counterexample": concentration("CAT-PRD", "SUP-008"),
        },
        "price_outliers": {
            "outlier_item_ids": price_results["outlier_item_ids"],
            "insufficient_groups": [group for group in price_results["insufficient_groups"] if str(group["item_code"]).startswith("PRICE-")],
        },
        "duplicate_purchase_approval_behavior": "rejected_by_identity_constraint",
        "protected_po_count": len([po for po in po_by_number if po.startswith("PO-2026-18") or po.startswith("PO-2026-2") or po.startswith("PO-2025-19") or po.startswith("PO-2025-20") or po.startswith("PO-2025-21")]),
    }


def write_dataset(output_dir: Path, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    data = build_dataset(seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    for table, rows in data.items():
        path = output_dir / f"{table}.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
            writer.writeheader()
            writer.writerows(rows)
    manifest = ground_truth(data, seed)
    (output_dir / "ground_truth.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    manifest = write_dataset(Path("data/generated"))
    print(json.dumps(manifest["row_counts"], sort_keys=True))


if __name__ == "__main__":
    main()

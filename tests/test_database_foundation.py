from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from procurement_agent.data.generator import DEFAULT_SEED, write_dataset
from procurement_agent.database.connection import sqlite_engine
from procurement_agent.database.loader import build_database
from procurement_agent.database.query import ReadOnlyQueryError, ResultLimitExceeded, execute_readonly_query
from procurement_agent.database.reference_queries import CANONICAL_PO_FACTS, HIGH_VALUE_APPROVAL_FACTS, INDIRECT_PARETO, OFF_CONTRACT_FACTS, PAST_SIX_MONTHS_BY_BUSINESS_UNIT, SINGLE_SOURCE_FACTS, SUP_042_H1_SPEND, TOP_Q2_IT_SUPPLIERS
from procurement_agent.database.schema import describe_table, list_tables


@pytest.fixture()
def database(tmp_path: Path):
    source_dir = tmp_path / "generated"
    manifest = write_dataset(source_dir, DEFAULT_SEED)
    database_path = tmp_path / "procurement.sqlite"
    assert build_database(database_path, source_dir) == manifest["row_counts"]
    engine = sqlite_engine(database_path)
    yield engine, manifest
    engine.dispose()


def decimal_value(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def test_schema_introspection_exposes_only_mvp_tables(database):
    engine, _ = database
    expected = {"approvals", "business_units", "categories", "contracts", "purchase_order_items", "purchase_orders", "supplier_category_eligibility", "suppliers"}
    assert set(list_tables(engine)) == expected
    description = describe_table(engine, "purchase_orders")
    assert {column["name"] for column in description["columns"]} >= {"approval_evidence_status", "contract_evidence_status", "total_amount_usd", "contract_id"}
    assert {foreign_key["referred_table"] for foreign_key in description["foreign_keys"]} >= {"business_units", "categories", "contracts", "suppliers"}


def test_loader_preserves_row_counts_and_money_totals(database):
    engine, manifest = database
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT po.po_number, po.total_amount_usd, SUM(item.line_amount_usd) AS item_total
            FROM purchase_orders AS po
            JOIN purchase_order_items AS item ON item.po_number = po.po_number
            GROUP BY po.po_number, po.total_amount_usd
        """)).mappings().all()
    assert len(rows) == manifest["row_counts"]["purchase_orders"]
    assert all(decimal_value(row["total_amount_usd"]) == decimal_value(row["item_total"]) for row in rows)


def test_readonly_query_allows_select_and_cte(database):
    engine, _ = database
    assert execute_readonly_query(engine, "SELECT COUNT(*) AS count FROM suppliers").rows == [{"count": 25}]
    assert execute_readonly_query(engine, "WITH x AS (SELECT 7 AS n) SELECT n FROM x").rows == [{"n": 7}]


@pytest.mark.parametrize("sql", [
    "INSERT INTO suppliers VALUES ('X', 'X', 'X')",
    "UPDATE suppliers SET name = 'changed'",
    "DELETE FROM suppliers",
    "DROP TABLE suppliers",
    "ALTER TABLE suppliers ADD COLUMN unsafe TEXT",
    "CREATE TABLE unsafe (id INTEGER)",
    "ATTACH DATABASE 'other.sqlite' AS other",
    "PRAGMA foreign_keys=OFF",
    "SELECT 1; SELECT 2",
    "WITH x AS (SELECT 1) INSERT INTO suppliers VALUES ('X', 'X', 'X')",
])
def test_readonly_query_rejects_mutations_without_state_change(database, sql):
    engine, _ = database
    before = execute_readonly_query(engine, "SELECT COUNT(*) AS count FROM suppliers").rows
    with pytest.raises(ReadOnlyQueryError):
        execute_readonly_query(engine, sql)
    assert execute_readonly_query(engine, "SELECT COUNT(*) AS count FROM suppliers").rows == before


def test_readonly_query_reports_row_limit_explicitly(database):
    engine, _ = database
    with pytest.raises(ResultLimitExceeded):
        execute_readonly_query(engine, "SELECT po_number FROM purchase_orders", max_rows=100)


def test_reference_sql_spend_and_ranking_scenarios(database):
    engine, manifest = database
    assert execute_readonly_query(engine, PAST_SIX_MONTHS_BY_BUSINESS_UNIT).row_count == 4
    assert execute_readonly_query(engine, TOP_Q2_IT_SUPPLIERS).row_count <= 10
    growth_rows = {row["period"]: decimal_value(row["spend_usd"]) for row in execute_readonly_query(engine, SUP_042_H1_SPEND).rows}
    growth = manifest["sup_042_growth"]
    assert growth_rows == {"H1_2025": Decimal(growth["h1_2025_spend_usd"]), "H1_2026": Decimal(growth["h1_2026_spend_usd"])}
    assert growth_rows["H1_2026"] - growth_rows["H1_2025"] == Decimal(growth["absolute_increase_usd"])


def test_reference_sql_pareto_contract_approval_and_canonical_facts(database):
    engine, manifest = database
    pareto_rows = execute_readonly_query(engine, INDIRECT_PARETO).rows
    reaching_80: list[str] = []
    for row in pareto_rows:
        reaching_80.append(row["supplier_id"])
        if Decimal(str(row["cumulative_share"])) >= Decimal("0.80"):
            break
    assert reaching_80 == manifest["pareto_indirect_h1_2026"]["supplier_set_to_80pct"]
    off_contract = {row["po_number"]: row for row in execute_readonly_query(engine, OFF_CONTRACT_FACTS).rows}
    assert off_contract["PO-2026-1837"]["contract_id"] is None
    assert off_contract["PO-2026-1838"]["contract_reference"] == "UNRESOLVED-1838"
    assert str(off_contract["PO-2026-1839"]["expiration_date"]) == "2025-12-31"
    assert off_contract["PO-2026-1847"]["contract_evidence_status"] == "COMPLETE"
    high_value = execute_readonly_query(engine, HIGH_VALUE_APPROVAL_FACTS).rows
    assert any(row["po_number"] == "PO-2026-1842" and row["approver_role"] == "MANAGER" for row in high_value)
    canonical = execute_readonly_query(engine, CANONICAL_PO_FACTS).rows
    assert canonical[0]["po_number"] == "PO-2026-1842"
    assert decimal_value(canonical[0]["total_amount_usd"]) == Decimal("72000.00")
    assert canonical[0]["supplier_id"] == "SUP-042"
    assert canonical[0]["category_name"] == "IT Services"
    assert canonical[0]["approval_evidence_status"] == "COMPLETE"


def test_reference_sql_single_source_facts_are_not_compliance_status(database):
    engine, manifest = database
    row = execute_readonly_query(engine, SINGLE_SOURCE_FACTS).rows[0]
    expected = manifest["single_source"]["positive"]
    assert row["category_id"] == expected["category_id"]
    assert row["supplier_id"] == expected["supplier_id"]
    assert bool(row["is_critical"])
    assert Decimal(str(row["supplier_spend_share"])).quantize(Decimal("0.0001")) == Decimal(expected["spend_share"])
    assert row["qualified_supplier_count"] == expected["qualified_supplier_count"]
    assert "PASS" not in row and "FAIL" not in row and "REVIEW" not in row

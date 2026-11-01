from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from procurement_agent.analytics.analytics import analyze_price_observations, analyze_price_outliers, analyze_single_source_risk, analyze_spend_growth, analyze_supplier_concentration
from procurement_agent.analytics.models import PriceObservation
from procurement_agent.data.generator import DEFAULT_SEED, write_dataset
from procurement_agent.database.connection import sqlite_engine
from procurement_agent.database.loader import build_database
from procurement_agent.evaluation.analytics import evaluate_analytics


PROJECT_ROOT = Path(__file__).resolve().parents[1]
H1_2025 = (date(2025, 1, 1), date(2025, 6, 30))
H1_2026 = (date(2026, 1, 1), date(2026, 6, 30))


@pytest.fixture()
def database(tmp_path: Path):
    source = tmp_path / "generated"
    write_dataset(source, DEFAULT_SEED)
    path = tmp_path / "procurement.sqlite"
    build_database(path, source)
    engine = sqlite_engine(path)
    yield engine
    engine.dispose()


def test_sup_042_growth_and_observable_driver_decomposition(database):
    result = analyze_spend_growth(database, "SUP-042", *H1_2025, *H1_2026)
    expected = json.loads((PROJECT_ROOT / "data" / "generated" / "ground_truth.json").read_text(encoding="utf-8"))["sup_042_growth"]
    assert result.comparison_spend == Decimal(expected["h1_2025_spend_usd"])
    assert result.current_spend == Decimal(expected["h1_2026_spend_usd"])
    assert result.absolute_change == Decimal(expected["absolute_increase_usd"])
    assert result.percentage_change == Decimal(expected["growth_pct"])
    assert (result.comparison_po_count, result.current_po_count) == (3, 7)
    assert (result.comparison_average_po_amount, result.current_average_po_amount) == (Decimal("40000.00"), Decimal("55714.29"))
    assert sum(item.absolute_change for item in result.category_contributions) == result.absolute_change
    assert {item.category_id: item.absolute_change for item in result.category_contributions} == {"CAT-IT": Decimal("170000.00"), "CAT-SW": Decimal("100000.00")}
    assert [item.po_number for item in result.largest_current_period_pos] == ["PO-2026-1843", "PO-2026-1842", "PO-2026-1861"]


def test_zero_base_spend_has_explicit_non_infinite_semantics(database):
    result = analyze_spend_growth(database, "SUP-NONE", *H1_2025, *H1_2026)
    assert result.comparison_spend == result.current_spend == Decimal("0.00")
    assert result.percentage_change is None and result.growth_basis == "ZERO_BASE_NO_SPEND"


def test_price_outliers_are_grouped_by_item_and_uom(database):
    groups = {(item.item_code, item.unit_of_measure): item for item in analyze_price_outliers(database) if item.item_code.startswith("PRICE-")}
    assert [item.purchase_order_item_id for item in groups[("PRICE-OFF-001", "EA")].outliers] == ["PO-2025-1910-L01"]
    assert [item.purchase_order_item_id for item in groups[("PRICE-FAC-001", "EA")].outliers] == ["PO-2025-2009-L01"]
    assert groups[("PRICE-OFF-001", "BOX")].analysis_status == "INSUFFICIENT_PEER_GROUP"
    assert groups[("PRICE-PRD-001", "EA")].analysis_status == "INSUFFICIENT_PEER_GROUP"


def test_zero_mad_is_safe_and_never_manufactures_an_outlier():
    observations = [PriceObservation(f"I-{index}", f"PO-{index}", "SUP-1", "FIXED", "EA", Decimal("100.00")) for index in range(8)]
    result = analyze_price_observations(observations)[0]
    assert result.analysis_status == "ZERO_VARIANCE" and result.mad == Decimal("0.00") and result.outliers == ()


def test_concentration_positive_and_counterexamples(database):
    positive = analyze_single_source_risk(database, "CAT-PRO", *H1_2026)
    noncritical = analyze_single_source_risk(database, "CAT-OFF", *H1_2026)
    alternatives = analyze_single_source_risk(database, "CAT-PRD", *H1_2026)
    assert (positive.top_supplier_id, positive.top_supplier_share, positive.concentration.qualified_supplier_count, positive.risk_finding) == ("SUP-017", Decimal("0.9091"), 1, True)
    assert noncritical.concentration.is_critical is False and noncritical.risk_finding is False
    assert alternatives.concentration.qualified_supplier_count == 3 and alternatives.risk_finding is False
    concentration = analyze_supplier_concentration(database, "CAT-PRO", *H1_2026)
    assert sum(item.spend_share for item in concentration.supplier_spend) == Decimal("1.0000")


def test_analytics_benchmark_is_deterministic_and_database_backed(database):
    report = evaluate_analytics(database)
    assert report["case_count"] == 10 and report["passed"] == 10 and report["failed"] == 0
    assert all(record["passed"] for record in report["records"])

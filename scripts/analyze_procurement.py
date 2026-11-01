from __future__ import annotations

import argparse
import json
from datetime import date

from procurement_agent.analytics.analytics import analyze_price_outliers, analyze_single_source_risk, analyze_spend_growth
from procurement_agent.compliance.engine import DEFAULT_DATABASE_PATH
from procurement_agent.database.connection import sqlite_engine


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    spend = commands.add_parser("spend")
    spend.add_argument("supplier_id")
    price = commands.add_parser("price")
    price.add_argument("item_code")
    concentration = commands.add_parser("concentration")
    concentration.add_argument("category_id")
    args = parser.parse_args()
    engine = sqlite_engine(DEFAULT_DATABASE_PATH)
    try:
        if args.command == "spend":
            result = analyze_spend_growth(engine, args.supplier_id, date(2025, 1, 1), date(2025, 6, 30), date(2026, 1, 1), date(2026, 6, 30))
            output = result.to_dict()
        elif args.command == "price":
            output = [result.to_dict() for result in analyze_price_outliers(engine, args.item_code)]
        else:
            output = analyze_single_source_risk(engine, args.category_id, date(2026, 1, 1), date(2026, 6, 30)).to_dict()
    finally:
        engine.dispose()
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

from procurement_agent.compliance.engine import ComplianceEngine
from procurement_agent.compliance.engine import DEFAULT_DATABASE_PATH
from procurement_agent.database.connection import sqlite_engine
from procurement_agent.evaluation.compliance import evaluate_compliance, write_compliance_report


def main() -> None:
    engine = sqlite_engine(DEFAULT_DATABASE_PATH)
    try:
        report = evaluate_compliance(ComplianceEngine(engine))
    finally:
        engine.dispose()
    print(write_compliance_report(report))


if __name__ == "__main__":
    main()

from procurement_agent.compliance.engine import DEFAULT_DATABASE_PATH
from procurement_agent.database.connection import sqlite_engine
from procurement_agent.evaluation.analytics import evaluate_analytics, write_analytics_report


def main() -> None:
    engine = sqlite_engine(DEFAULT_DATABASE_PATH)
    try:
        report = evaluate_analytics(engine)
    finally:
        engine.dispose()
    print(write_analytics_report(report))


if __name__ == "__main__":
    main()

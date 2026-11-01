"""Run the live Phase 3B Agent once from the command line."""

from __future__ import annotations

import argparse
import json
import sys

from procurement_agent.agent.graph import ProcurementAgent
from procurement_agent.agent.model_adapter import LiveOpenAIModelAdapter, ModelAdapterError
from procurement_agent.tools.models import json_value


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the live Enterprise Procurement Intelligence Agent.")
    parser.add_argument("query", help="Procurement question to analyze")
    args = parser.parse_args()
    try:
        agent = ProcurementAgent(LiveOpenAIModelAdapter())
    except ModelAdapterError as error:
        print(json.dumps({"status": "not_run", "reason": str(error)}))
        return 2
    try:
        trace = agent.run(args.query)
    finally:
        agent.close()
    print(json.dumps(json_value(trace.model_dump()), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Validate the offline requirements_v2 fixture and metric calculations without model calls."""

from __future__ import annotations

import argparse
import json

from procurement_agent.evaluation.requirements import evaluate_requirements, fixture_distribution, fixture_oracle_predictions, load_requirements_fixture


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a requirements fixture and metric calculations without model calls.")
    parser.add_argument("--requirements-version", choices=("requirements_v2", "requirements_v2_1"), default="requirements_v2")
    args = parser.parse_args()
    cases = load_requirements_fixture(args.requirements_version)
    print(json.dumps({
        "evaluation_mode": "fixture_oracle_self_check",
        "requirements_version": args.requirements_version,
        "distribution": fixture_distribution(cases),
        "metrics": evaluate_requirements(cases, fixture_oracle_predictions(cases)),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

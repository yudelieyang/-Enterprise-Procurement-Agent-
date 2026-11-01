from __future__ import annotations

import argparse
import json

from procurement_agent.compliance.engine import audit_purchase_order


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("po_number")
    args = parser.parse_args()
    print(json.dumps(audit_purchase_order(args.po_number).to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

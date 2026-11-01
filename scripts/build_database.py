from pathlib import Path

from procurement_agent.database.loader import build_database


if __name__ == "__main__":
    counts = build_database(Path("data/generated/procurement.sqlite"), Path("data/generated"))
    print(counts)

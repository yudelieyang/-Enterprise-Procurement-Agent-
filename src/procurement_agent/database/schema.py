from __future__ import annotations

from sqlalchemy import Engine, inspect


def list_tables(engine: Engine) -> list[str]:
    return sorted(inspect(engine).get_table_names())


def describe_table(engine: Engine, table_name: str) -> dict[str, object]:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        raise ValueError(f"Unknown table: {table_name}")
    return {
        "table": table_name,
        "columns": [{"name": column["name"], "type": str(column["type"]), "nullable": column["nullable"], "primary_key": column["primary_key"]} for column in inspector.get_columns(table_name)],
        "foreign_keys": [{"constrained_columns": foreign_key["constrained_columns"], "referred_table": foreign_key["referred_table"], "referred_columns": foreign_key["referred_columns"]} for foreign_key in inspector.get_foreign_keys(table_name)],
    }

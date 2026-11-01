from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event


def sqlite_engine(database_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{database_path.resolve().as_posix()}", future=True)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine

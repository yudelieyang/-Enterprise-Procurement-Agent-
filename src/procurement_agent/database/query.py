from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, text


class ReadOnlyQueryError(ValueError):
    pass


class ResultLimitExceeded(ValueError):
    pass


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int


FORBIDDEN_KEYWORDS = {"ALTER", "ANALYZE", "ATTACH", "CREATE", "DELETE", "DETACH", "DROP", "INSERT", "PRAGMA", "REINDEX", "REPLACE", "UPDATE", "VACUUM"}


def sql_keywords_and_statement_count(sql: str) -> tuple[list[str], int]:
    keywords: list[str] = []
    statement_count = 0
    word: list[str] = []
    index = 0
    has_content = False
    while index < len(sql):
        character = sql[index]
        if character in "'\"`":
            quote = character
            index += 1
            while index < len(sql):
                if sql[index] == quote:
                    if quote == "'" and index + 1 < len(sql) and sql[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            has_content = True
            continue
        if sql[index:index + 2] == "--":
            index = sql.find("\n", index)
            if index == -1:
                break
            continue
        if sql[index:index + 2] == "/*":
            end = sql.find("*/", index + 2)
            if end == -1:
                raise ReadOnlyQueryError("Unterminated SQL comment")
            index = end + 2
            continue
        if character == ";":
            if word:
                keywords.append("".join(word).upper())
                word = []
            if has_content:
                statement_count += 1
                has_content = False
            index += 1
            continue
        if character.isalpha() or character == "_":
            word.append(character)
            has_content = True
        else:
            if word:
                keywords.append("".join(word).upper())
                word = []
            if not character.isspace():
                has_content = True
        index += 1
    if word:
        keywords.append("".join(word).upper())
    if has_content:
        statement_count += 1
    return keywords, statement_count


def validate_readonly_sql(sql: str) -> None:
    keywords, statement_count = sql_keywords_and_statement_count(sql)
    if statement_count != 1:
        raise ReadOnlyQueryError("Exactly one SQL statement is required")
    if not keywords or keywords[0] not in {"SELECT", "WITH"}:
        raise ReadOnlyQueryError("Only SELECT or WITH ... SELECT statements are allowed")
    forbidden = sorted(set(keywords) & FORBIDDEN_KEYWORDS)
    if forbidden:
        raise ReadOnlyQueryError(f"Forbidden SQL keyword(s): {', '.join(forbidden)}")


def execute_readonly_query(engine: Engine, sql: str, max_rows: int = 100) -> QueryResult:
    validate_readonly_sql(sql)
    with engine.connect() as connection:
        result = connection.execute(text(sql))
        columns = list(result.keys())
        rows = [dict(row) for row in result.mappings().fetchmany(max_rows + 1)]
    if len(rows) > max_rows:
        raise ResultLimitExceeded(f"Query returned more than the {max_rows}-row limit")
    return QueryResult(columns=columns, rows=rows, row_count=len(rows))

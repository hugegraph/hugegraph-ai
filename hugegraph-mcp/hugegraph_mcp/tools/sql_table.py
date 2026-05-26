# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import re
import sqlite3
from typing import Any

from hugegraph_mcp.config import config
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok

_UNSAFE_SQL_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH)\b",
    re.IGNORECASE,
)

_READONLY_PRAGMAS = frozenset({
    "table_info", "table_xinfo", "index_list", "index_info", "index_xinfo",
    "foreign_key_list", "foreign_key_check", "collation_list", "compile_options",
    "data_version", "database_list", "function_list", "module_list",
    "page_count", "page_size", "quick_check", "schema_version", "user_version",
    "wal_checkpoint",
})


def validate_sqlite_source(sql_source: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(sql_source, dict) or sql_source.get("type") != "sqlite":
        return envelope_err(
            ErrorType.UNSUPPORTED_SQL_SOURCE,
            "Only sqlite source type is supported in Phase 1.",
            suggestion="Set sql_source.type to 'sqlite' and provide a local SQLite file path.",
            details={"supported_types": ["sqlite"]},
        )

    if not config.sql_enabled:
        return envelope_err(
            ErrorType.AUTHORIZATION_FAILED,
            "SQL capability is not enabled.",
            suggestion=(
                "Set HUGEGRAPH_MCP_SQL_ENABLED=true to enable SQL data source access."
            ),
            details={"sql_enabled": False},
        )

    source_path = sql_source.get("path", "")
    if not isinstance(source_path, str) or not source_path:
        return envelope_err(
            ErrorType.SQL_SOURCE_NOT_FOUND,
            "sql_source.path is required and must be a non-empty string.",
            suggestion="Provide the absolute path to the SQLite file in sql_source.path.",
        )

    allowlist = config.sqlite_allowlist
    if allowlist and not any(
        os.path.normpath(source_path) == os.path.normpath(allowed)
        for allowed in allowlist
    ):
        return envelope_err(
            ErrorType.AUTHORIZATION_FAILED,
            f"SQLite file path is not in the allowlist: {source_path}",
            suggestion=(
                "Add the file path to HUGEGRAPH_MCP_SQLITE_ALLOWLIST "
                "(semicolon-separated) or check the path spelling."
            ),
            details={"path": source_path, "allowlist": list(allowlist)},
        )

    if not os.path.isfile(source_path):
        return envelope_err(
            ErrorType.SQL_SOURCE_NOT_FOUND,
            f"SQLite file not found: {source_path}",
            suggestion=(
                "Check the file path, allowlist, and that the file is readable."
            ),
            details={"path": source_path},
        )

    return None


def validate_readonly_sql(sql_query: str) -> dict[str, Any] | None:
    if not isinstance(sql_query, str) or not sql_query.strip():
        return envelope_err(
            ErrorType.UNSAFE_SQL,
            "SQL query must be a non-empty string.",
            suggestion="Provide a SELECT or WITH ... SELECT query.",
        )

    stripped = sql_query.strip()
    statements = _split_sql_statements(stripped)
    select_statements = [s for s in statements if s.strip()]

    if len(select_statements) > 1:
        return envelope_err(
            ErrorType.UNSAFE_SQL,
            "Multiple SQL statements are not allowed.",
            suggestion="Provide a single SELECT or WITH ... SELECT query.",
            details={"statement_count": len(select_statements)},
        )

    if not select_statements:
        return envelope_err(
            ErrorType.UNSAFE_SQL,
            "No valid SQL statement found.",
            suggestion="Provide a SELECT or WITH ... SELECT query.",
        )

    query = select_statements[0].strip()

    if _UNSAFE_SQL_KEYWORDS.search(query):
        return envelope_err(
            ErrorType.UNSAFE_SQL,
            "Only read-only SELECT queries are allowed.",
            suggestion=(
                "Use a SELECT or WITH ... SELECT query. "
                "INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, REPLACE, "
                "ATTACH, and DETACH are not permitted."
            ),
        )

    if re.search(r"\bPRAGMA\b", query, re.IGNORECASE):
        pragma_match = re.search(
            r"\bPRAGMA\s+(\w+)", query, re.IGNORECASE
        )
        if pragma_match:
            pragma_name = pragma_match.group(1).lower()
            if pragma_name not in _READONLY_PRAGMAS:
                return envelope_err(
                    ErrorType.UNSAFE_SQL,
                    f"PRAGMA '{pragma_name}' is not permitted.",
                    suggestion=(
                        "Only informational PRAGMAs are allowed "
                        "in read-only mode."
                    ),
                    details={"pragma": pragma_name},
                )
        return None

    upper = query.upper()
    if not (
        upper.startswith("SELECT")
        or upper.startswith("WITH ")
        or upper.startswith("EXPLAIN ")
    ):
        return envelope_err(
            ErrorType.UNSAFE_SQL,
            "Only SELECT, WITH ... SELECT, EXPLAIN, and informational PRAGMA queries are allowed.",
            suggestion="Rewrite the query as a read-only SELECT statement.",
        )

    return None


def normalize_sql_query(sql_query: str) -> str:
    normalized = " ".join(sql_query.strip().split())
    if not normalized.endswith(";"):
        normalized += ";"
    return normalized


def preview_sql(
    sql_source: dict[str, Any],
    table_name: str | None = None,
    sql_query: str | None = None,
) -> dict[str, Any]:
    source_err = validate_sqlite_source(sql_source)
    if source_err is not None:
        return source_err

    source_path = sql_source["path"]
    if table_name is not None:
        return _preview_table(source_path, table_name)
    if sql_query is not None:
        return _preview_query(source_path, sql_query)

    return envelope_err(
        ErrorType.UNSAFE_SQL,
        "Either table_name or sql_query must be provided for sql_preview.",
        suggestion="Provide table_name to inspect a table, or sql_query to run a SELECT.",
    )


def execute_select_to_table_data(
    sql_source: dict[str, Any],
    sql_query: str,
    table_name: str | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    source_err = validate_sqlite_source(sql_source)
    if source_err is not None:
        return source_err

    sql_err = validate_readonly_sql(sql_query)
    if sql_err is not None:
        return sql_err

    source_path = sql_source["path"]
    limit = (
        max_rows
        if max_rows is not None
        else config.sql_max_import_rows
    )

    try:
        conn = _open_readonly_connection(source_path)
    except sqlite3.Error as exc:
        return envelope_err(
            ErrorType.SQL_SOURCE_NOT_FOUND,
            f"Failed to open SQLite database: {exc}",
            suggestion="Check that the file is a valid SQLite database and is readable.",
            details={"path": source_path, "error": str(exc)},
        )

    warnings: list[str] = []
    try:
        normalized = normalize_sql_query(sql_query)
        limited = _add_limit(normalized, limit)
        cursor = conn.execute(limited)
        columns = _column_info(cursor)

        if not columns:
            return envelope_err(
                ErrorType.UNSAFE_SQL,
                "Query returned zero columns.",
                suggestion="Check the SQL query and try again.",
            )

        _validate_column_names(columns, warnings)

        rows, truncated, blob_warnings = _fetch_rows(cursor, limit)
        warnings.extend(blob_warnings)

        inferred_table_name = table_name or _derive_table_name(sql_query)
        result_table_data = {
            "table_name": inferred_table_name,
            "columns": [col["name"] for col in columns],
            "rows": rows,
        }

        row_count = len(rows)
        if row_count == 0:
            warnings.append(
                "SQL query returned zero rows; import will be skipped."
            )

        return envelope_ok(
            {
                "table_data": result_table_data,
                "row_count": row_count,
                "truncated": truncated,
            },
            warnings=warnings,
        )
    except (sqlite3.Error, ValueError) as exc:
        return envelope_err(
            ErrorType.UNSAFE_SQL,
            f"SQL execution failed: {exc}",
            suggestion="Check the SQL query syntax and try again.",
            details={"error": str(exc)},
        )
    finally:
        conn.close()


def _preview_table(source_path: str, table_name: str) -> dict[str, Any]:
    try:
        conn = _open_readonly_connection(source_path)
    except sqlite3.Error as exc:
        return envelope_err(
            ErrorType.SQL_SOURCE_NOT_FOUND,
            f"Failed to open SQLite database: {exc}",
            suggestion="Check that the file is a valid SQLite database.",
            details={"path": source_path, "error": str(exc)},
        )

    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()

        if exists is None:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            ]
            return envelope_err(
                ErrorType.SQL_SOURCE_NOT_FOUND,
                f"Table '{table_name}' does not exist in the SQLite database.",
                suggestion=(
                    "Check the table name or use sql_preview without table_name "
                    "to list available tables."
                ),
                details={"available_tables": tables},
            )

        columns = []
        for row in conn.execute(f"PRAGMA table_info('{table_name}')"):
            columns.append({"name": row[1], "type": row[2]})

        count_row = conn.execute(
            f"SELECT COUNT(*) FROM \"{table_name}\""
        ).fetchone()
        estimated_rows = count_row[0] if count_row else 0

        limit = config.sql_max_preview_rows
        cursor = conn.execute(
            f"SELECT * FROM \"{table_name}\" LIMIT {limit}"
        )
        rows, truncated, blob_warnings = _fetch_rows(cursor, limit)

        return envelope_ok(
            {
                "source_ref": {
                    "type": "sqlite",
                    "path": source_path,
                },
                "columns": columns,
                "rows": rows,
                "row_count": estimated_rows,
                "truncated": truncated or estimated_rows > limit,
            },
            warnings=blob_warnings,
        )
    except (sqlite3.Error, ValueError) as exc:
        return envelope_err(
            ErrorType.UNSAFE_SQL,
            f"Failed to preview table '{table_name}': {exc}",
            suggestion="Check the table name and try again.",
            details={"table_name": table_name, "error": str(exc)},
        )
    finally:
        conn.close()


def _preview_query(source_path: str, sql_query: str) -> dict[str, Any]:
    sql_err = validate_readonly_sql(sql_query)
    if sql_err is not None:
        return sql_err

    warnings: list[str] = []
    try:
        conn = _open_readonly_connection(source_path)
    except sqlite3.Error as exc:
        return envelope_err(
            ErrorType.SQL_SOURCE_NOT_FOUND,
            f"Failed to open SQLite database: {exc}",
            suggestion="Check the file is a valid SQLite database.",
            details={"path": source_path, "error": str(exc)},
        )

    try:
        normalized = normalize_sql_query(sql_query)
        limit = config.sql_max_preview_rows
        limited = _add_limit(normalized, limit)
        cursor = conn.execute(limited)
        columns = _column_info(cursor)

        if not columns:
            return envelope_err(
                ErrorType.UNSAFE_SQL,
                "Query returned zero columns.",
                suggestion="Check the SQL query and try again.",
            )

        _validate_column_names(columns, warnings)
        rows, truncated, blob_warnings = _fetch_rows(cursor, limit)
        warnings.extend(blob_warnings)

        return envelope_ok(
            {
                "source_ref": {
                    "type": "sqlite",
                    "path": source_path,
                },
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "truncated": truncated,
            },
            warnings=warnings,
        )
    except (sqlite3.Error, ValueError) as exc:
        return envelope_err(
            ErrorType.UNSAFE_SQL,
            f"SQL execution failed: {exc}",
            suggestion="Check the query syntax and try again.",
            details={"error": str(exc)},
        )
    finally:
        conn.close()


def _open_readonly_connection(path: str) -> sqlite3.Connection:
    uri = f"file:///{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=config.sql_timeout_seconds)
    conn.execute("PRAGMA query_only = ON")
    conn.set_authorizer(_readonly_authorizer)
    conn.row_factory = sqlite3.Row
    return conn


def _readonly_authorizer(action: int, *args: Any) -> int:
    readonly_actions = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_PRAGMA,
        sqlite3.SQLITE_RECURSIVE,
    }
    if action in readonly_actions:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _column_info(cursor: sqlite3.Cursor) -> list[dict[str, str]]:
    return [
        {"name": desc[0], "type": ""}
        for desc in cursor.description or []
    ]


def _fetch_rows(
    cursor: sqlite3.Cursor, limit: int
) -> tuple[list[list[Any]], bool, list[str]]:
    rows: list[list[Any]] = []
    truncated = False
    warnings: list[str] = []
    blob_columns: set[int] = set()

    for idx, row in enumerate(cursor):
        if idx >= limit:
            truncated = True
            break
        converted = []
        for col_idx, value in enumerate(tuple(row)):
            if isinstance(value, bytes):
                blob_columns.add(col_idx)
                converted.append(f"<BLOB {len(value)} bytes>")
            elif isinstance(value, memoryview):
                blob_columns.add(col_idx)
                converted.append(f"<BLOB {len(value)} bytes>")
            else:
                try:
                    json.dumps(value)
                    converted.append(value)
                except (TypeError, ValueError):
                    blob_columns.add(col_idx)
                    converted.append(f"<UNSERIALIZABLE: {type(value).__name__}>")
        rows.append(converted)

    if blob_columns and cursor.description:
        col_names = [
            cursor.description[col_idx][0]
            for col_idx in sorted(blob_columns)
            if col_idx < len(cursor.description)
        ]
        warnings.append(
            f"BLOB or non-serializable values in columns {col_names} "
            "were replaced with human-readable summaries."
        )

    return rows, truncated, warnings


def _split_sql_statements(sql: str) -> list[str]:
    result: list[str] = []
    current: list[str] = []
    in_single_quote = False
    in_double_quote = False
    i = 0

    while i < len(sql):
        char = sql[i]
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current.append(char)
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(char)
        elif char == ";" and not in_single_quote and not in_double_quote:
            current.append(char)
            result.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        i += 1

    remaining = "".join(current).strip()
    if remaining:
        result.append(remaining)

    return result


def _add_limit(normalized_sql: str, limit: int) -> str:
    upper = normalized_sql.upper().rstrip(";")
    if "LIMIT" in upper:
        return normalized_sql

    without_semicolon = normalized_sql.rstrip(";").rstrip()
    return f"{without_semicolon} LIMIT {limit + 1};"


def _derive_table_name(sql_query: str) -> str:
    match = re.search(
        r"\bFROM\s+(\w+)",
        sql_query,
        re.IGNORECASE,
    )
    if match:
        return f"{match.group(1)}_preview"
    return "sql_preview"


def _validate_column_names(
    columns: list[dict[str, str]], warnings: list[str]
) -> None:
    names = [col["name"] for col in columns]
    if any(not name for name in names):
        raise ValueError(
            "SQL result contains empty column names. "
            "Use AS to alias computed columns."
        )
    if len(names) != len(set(names)):
        seen: set[str] = set()
        duplicates = {name for name in names if name in seen or seen.add(name)}  # type: ignore[func-returns-value]
        raise ValueError(
            f"SQL result contains duplicate column names: {sorted(duplicates)}. "
            "Use AS to alias columns with unique names."
        )

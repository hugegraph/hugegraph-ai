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

import os
import sqlite3
import tempfile
from unittest import mock

import pytest

from hugegraph_mcp.envelope import ErrorType
from hugegraph_mcp.tools.sql_table import (
    execute_select_to_table_data,
    normalize_sql_query,
    preview_sql,
    validate_readonly_sql,
    validate_sqlite_source,
)


@pytest.fixture
def temp_sqlite_db():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE chunks ("
        "  chunk_id INTEGER PRIMARY KEY,"
        "  source_path TEXT,"
        "  section_title TEXT,"
        "  content TEXT,"
        "  embedding BLOB"
        ")"
    )
    conn.execute(
        "INSERT INTO chunks VALUES (1,'doc1.md','Introduction','Hello world',NULL)"
    )
    conn.execute(
        "INSERT INTO chunks VALUES (2,'doc2.md','Methods','Some content',x'DEADBEEF')"
    )
    conn.execute("INSERT INTO chunks VALUES (3,'doc3.md','Results','Result text',NULL)")
    conn.commit()
    conn.close()
    yield path
    os.unlink(path)


@pytest.fixture
def sql_config(temp_sqlite_db):
    with mock.patch("hugegraph_mcp.tools.sql_table.config") as cfg:
        cfg.sql_enabled = True
        cfg.sqlite_allowlist = (temp_sqlite_db,)
        cfg.sql_max_preview_rows = 20
        cfg.sql_max_import_rows = 1000
        cfg.sql_timeout_seconds = 5
        yield cfg


# -- validate_sqlite_source --------------------------------------------------


class TestValidateSqliteSource:
    def test_valid_sqlite_source_passes(self, sql_config):
        path = sql_config.sqlite_allowlist[0]
        result = validate_sqlite_source({"type": "sqlite", "path": path})
        assert result is None

    def test_rejects_non_sqlite_type(self, sql_config):
        result = validate_sqlite_source({"type": "mysql", "path": "/x"})
        assert result is not None
        assert result["ok"] is False
        assert result["error"]["type"] == ErrorType.UNSUPPORTED_SQL_SOURCE.value

    def test_rejects_when_sql_disabled(self, sql_config):
        sql_config.sql_enabled = False
        result = validate_sqlite_source(
            {
                "type": "sqlite",
                "path": sql_config.sqlite_allowlist[0],
            }
        )
        assert result is not None
        assert result["error"]["type"] == ErrorType.AUTHORIZATION_FAILED.value
        assert "not enabled" in result["error"]["message"].lower()

    def test_rejects_path_not_in_allowlist(self, sql_config):
        result = validate_sqlite_source(
            {
                "type": "sqlite",
                "path": "/not/allowed/path.sqlite3",
            }
        )
        assert result is not None
        assert result["error"]["type"] == ErrorType.AUTHORIZATION_FAILED.value

    def test_rejects_missing_file(self, sql_config):
        nonexistent = sql_config.sqlite_allowlist[0] + ".nonexistent"
        sql_config.sqlite_allowlist = (nonexistent,)
        result = validate_sqlite_source(
            {
                "type": "sqlite",
                "path": nonexistent,
            }
        )
        assert result is not None
        assert result["error"]["type"] == ErrorType.SQL_SOURCE_NOT_FOUND.value

    def test_rejects_empty_path(self, sql_config):
        result = validate_sqlite_source({"type": "sqlite", "path": ""})
        assert result is not None
        assert result["error"]["type"] == ErrorType.SQL_SOURCE_NOT_FOUND.value

    def test_allowlist_normalized_path(self, sql_config, temp_sqlite_db):
        normalized = os.path.normpath(temp_sqlite_db)
        sql_config.sqlite_allowlist = (normalized,)
        result = validate_sqlite_source({"type": "sqlite", "path": temp_sqlite_db})
        assert result is None


# -- validate_readonly_sql ---------------------------------------------------


class TestValidateReadonlySql:
    def test_select_passes(self):
        result = validate_readonly_sql("SELECT * FROM chunks;")
        assert result is None

    def test_with_select_passes(self):
        result = validate_readonly_sql(
            "WITH cte AS (SELECT * FROM chunks) SELECT * FROM cte;"
        )
        assert result is None

    def test_explain_passes(self):
        result = validate_readonly_sql("EXPLAIN SELECT * FROM chunks;")
        assert result is None

    def test_insert_rejected(self):
        result = validate_readonly_sql("INSERT INTO chunks VALUES (1);")
        assert result is not None
        assert result["error"]["type"] == ErrorType.UNSAFE_SQL.value

    def test_update_rejected(self):
        result = validate_readonly_sql("UPDATE chunks SET x=1;")
        assert result is not None
        assert result["error"]["type"] == ErrorType.UNSAFE_SQL.value

    def test_delete_rejected(self):
        result = validate_readonly_sql("DELETE FROM chunks;")
        assert result is not None
        assert result["error"]["type"] == ErrorType.UNSAFE_SQL.value

    def test_drop_rejected(self):
        result = validate_readonly_sql("DROP TABLE chunks;")
        assert result is not None
        assert result["error"]["type"] == ErrorType.UNSAFE_SQL.value

    def test_alter_rejected(self):
        result = validate_readonly_sql("ALTER TABLE chunks ADD COLUMN x;")
        assert result is not None
        assert result["error"]["type"] == ErrorType.UNSAFE_SQL.value

    def test_create_rejected(self):
        result = validate_readonly_sql("CREATE TABLE t (a INTEGER);")
        assert result is not None
        assert result["error"]["type"] == ErrorType.UNSAFE_SQL.value

    def test_replace_rejected(self):
        result = validate_readonly_sql("REPLACE INTO chunks VALUES (1);")
        assert result is not None
        assert result["error"]["type"] == ErrorType.UNSAFE_SQL.value

    def test_attach_rejected(self):
        result = validate_readonly_sql("ATTACH 'other.db' AS other;")
        assert result is not None
        assert result["error"]["type"] == ErrorType.UNSAFE_SQL.value

    def test_detach_rejected(self):
        result = validate_readonly_sql("DETACH other;")
        assert result is not None
        assert result["error"]["type"] == ErrorType.UNSAFE_SQL.value

    def test_multiple_statements_rejected(self):
        result = validate_readonly_sql("SELECT * FROM chunks; SELECT * FROM chunks;")
        assert result is not None
        assert result["error"]["type"] == ErrorType.UNSAFE_SQL.value

    def test_empty_string_rejected(self):
        result = validate_readonly_sql("")
        assert result is not None
        assert result["error"]["type"] == ErrorType.UNSAFE_SQL.value

    def test_select_with_readonly_pragma_passes(self):
        result = validate_readonly_sql("PRAGMA table_info('chunks');")
        assert result is None

    def test_dangerous_pragma_rejected(self):
        result = validate_readonly_sql("PRAGMA integrity_check;")
        assert result is not None
        assert result["error"]["type"] == ErrorType.UNSAFE_SQL.value


# -- normalize_sql_query -----------------------------------------------------


class TestNormalizeSqlQuery:
    def test_adds_semicolon(self):
        assert normalize_sql_query("SELECT 1") == "SELECT 1;"

    def test_strips_whitespace(self):
        assert normalize_sql_query("  SELECT 1  ") == "SELECT 1;"

    def test_normalizes_internal_whitespace(self):
        assert normalize_sql_query("SELECT   1  FROM   t") == "SELECT 1 FROM t;"

    def test_keeps_existing_semicolon(self):
        assert normalize_sql_query("SELECT 1;") == "SELECT 1;"


# -- preview_sql -------------------------------------------------------------


class TestPreviewSql:
    def test_preview_table_returns_columns_and_rows(self, sql_config):
        path = sql_config.sqlite_allowlist[0]
        result = preview_sql(
            sql_source={"type": "sqlite", "path": path},
            table_name="chunks",
        )
        assert result["ok"] is True
        data = result["data"]
        assert data["source_ref"]["type"] == "sqlite"
        columns = data["columns"]
        col_names = [col["name"] for col in columns]
        assert "chunk_id" in col_names
        assert "source_path" in col_names
        assert "section_title" in col_names
        assert data["row_count"] == 3
        assert isinstance(data["rows"], list)

    def test_preview_table_nonexistent_returns_error(self, sql_config):
        path = sql_config.sqlite_allowlist[0]
        result = preview_sql(
            sql_source={"type": "sqlite", "path": path},
            table_name="nonexistent",
        )
        assert result["ok"] is False
        assert result["error"]["type"] == ErrorType.SQL_SOURCE_NOT_FOUND.value
        assert "available_tables" in result["error"]["details"]

    def test_preview_query_returns_results(self, sql_config):
        path = sql_config.sqlite_allowlist[0]
        result = preview_sql(
            sql_source={"type": "sqlite", "path": path},
            sql_query="SELECT source_path, section_title FROM chunks LIMIT 2",
        )
        assert result["ok"] is True
        data = result["data"]
        assert len(data["rows"]) == 2

    def test_preview_query_duplicate_columns_returns_envelope_error(self, sql_config):
        path = sql_config.sqlite_allowlist[0]
        result = preview_sql(
            sql_source={"type": "sqlite", "path": path},
            sql_query="SELECT 1 AS x, 2 AS x",
        )

        assert result["ok"] is False
        assert result["error"]["type"] == ErrorType.UNSAFE_SQL.value
        assert "duplicate column names" in result["error"]["message"]

    def test_preview_query_auto_limits(self, sql_config):
        sql_config.sql_max_preview_rows = 1
        path = sql_config.sqlite_allowlist[0]
        result = preview_sql(
            sql_source={"type": "sqlite", "path": path},
            sql_query="SELECT * FROM chunks",
        )
        assert result["ok"] is True
        assert len(result["data"]["rows"]) <= 1
        assert result["data"]["truncated"] is True

    def test_preview_requires_table_or_query(self, sql_config):
        path = sql_config.sqlite_allowlist[0]
        result = preview_sql(sql_source={"type": "sqlite", "path": path})
        assert result["ok"] is False

    def test_blob_handling_in_preview(self, sql_config):
        path = sql_config.sqlite_allowlist[0]
        result = preview_sql(
            sql_source={"type": "sqlite", "path": path},
            sql_query="SELECT * FROM chunks WHERE chunk_id = 2",
        )
        assert result["ok"] is True
        if result.get("warnings"):
            assert any("BLOB" in w for w in result["warnings"])


# -- execute_select_to_table_data --------------------------------------------


class TestExecuteSelectToTableData:
    def test_converts_to_table_data_format(self, sql_config):
        path = sql_config.sqlite_allowlist[0]
        result = execute_select_to_table_data(
            sql_source={"type": "sqlite", "path": path},
            sql_query="SELECT source_path, section_title FROM chunks LIMIT 2",
        )
        assert result["ok"] is True
        td = result["data"]["table_data"]
        assert td["table_name"] is not None
        assert isinstance(td["columns"], list)
        assert len(td["columns"]) == 2
        assert isinstance(td["rows"], list)
        assert len(td["rows"]) == 2
        assert result["data"]["truncated"] is False

    def test_empty_result_warns(self, sql_config):
        path = sql_config.sqlite_allowlist[0]
        result = execute_select_to_table_data(
            sql_source={"type": "sqlite", "path": path},
            sql_query="SELECT * FROM chunks WHERE 1=0",
        )
        assert result["ok"] is True
        assert result["data"]["row_count"] == 0
        assert any("zero rows" in w.lower() for w in result.get("warnings", []))

    def test_duplicate_columns_returns_envelope_error(self, sql_config):
        path = sql_config.sqlite_allowlist[0]
        result = execute_select_to_table_data(
            sql_source={"type": "sqlite", "path": path},
            sql_query="SELECT 1 AS x, 2 AS x",
        )

        assert result["ok"] is False
        assert result["error"]["type"] == ErrorType.UNSAFE_SQL.value
        assert "duplicate column names" in result["error"]["message"]

    def test_custom_table_name(self, sql_config):
        path = sql_config.sqlite_allowlist[0]
        result = execute_select_to_table_data(
            sql_source={"type": "sqlite", "path": path},
            sql_query="SELECT source_path FROM chunks LIMIT 1",
            table_name="my_table",
        )
        assert result["data"]["table_data"]["table_name"] == "my_table"

    def test_respects_max_rows(self, sql_config):
        path = sql_config.sqlite_allowlist[0]
        result = execute_select_to_table_data(
            sql_source={"type": "sqlite", "path": path},
            sql_query="SELECT * FROM chunks",
            max_rows=1,
        )
        assert result["ok"] is True
        assert len(result["data"]["table_data"]["rows"]) <= 1

    def test_rejects_unsafe_sql(self, sql_config):
        path = sql_config.sqlite_allowlist[0]
        result = execute_select_to_table_data(
            sql_source={"type": "sqlite", "path": path},
            sql_query="DROP TABLE chunks;",
        )
        assert result["ok"] is False
        assert result["error"]["type"] == ErrorType.UNSAFE_SQL.value

    def test_rejects_invalid_source(self, sql_config):
        nonexistent = sql_config.sqlite_allowlist[0] + ".noexist"
        sql_config.sqlite_allowlist = (nonexistent,)
        result = execute_select_to_table_data(
            sql_source={"type": "sqlite", "path": nonexistent},
            sql_query="SELECT 1",
        )
        assert result["ok"] is False
        assert result["error"]["type"] == ErrorType.SQL_SOURCE_NOT_FOUND.value

    def test_readonly_connection_denies_writes(self, sql_config):
        path = sql_config.sqlite_allowlist[0]
        with mock.patch(
            "hugegraph_mcp.tools.sql_table.validate_readonly_sql",
            return_value=None,
        ):
            result = execute_select_to_table_data(
                sql_source={"type": "sqlite", "path": path},
                sql_query="INSERT INTO chunks VALUES (99,'test','t','',NULL)",
            )
            assert result["ok"] is False


class TestNestedQuotedSemicolon:
    def test_semicolon_inside_quotes_not_split(self):
        result = validate_readonly_sql("SELECT 'hello;world' AS greeting")
        assert result is None

    def test_semicolon_inside_double_quotes_not_split(self):
        result = validate_readonly_sql('SELECT "col;name" FROM chunks')
        assert result is None

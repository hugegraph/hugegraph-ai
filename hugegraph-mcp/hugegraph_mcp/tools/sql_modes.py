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

from hugegraph_mcp.envelope import envelope_err, envelope_ok
from hugegraph_mcp.tools.import_table import import_table_data, suggest_table_mapping
from hugegraph_mcp.tools.manage_graph_data import (
    graph_data_to_change_plan,
    manage_graph_data,
)
from hugegraph_mcp.tools.sql_table import (
    execute_select_to_table_data,
    preview_sql,
)


def _handle_sql_mode(
    mode: str,
    sql_source: dict | None,
    sql_query: str | None,
    table_name: str | None,
    mapping: dict | None,
    dry_run: bool,
    confirm: bool,
    plan_hash: str | None,
) -> dict:
    if sql_source is None:
        return envelope_err(
            "VALIDATION_ERROR",
            f"sql_source is required for mode='{mode}'",
            suggestion=(
                "Provide sql_source with type='sqlite' and path to the SQLite file."
            ),
        )

    if mode == "sql_preview":
        return preview_sql(
            sql_source=sql_source,
            table_name=table_name,
            sql_query=sql_query,
        )

    if mode == "sql_mapping_suggest":
        if sql_query is None and table_name is None:
            return envelope_err(
                "VALIDATION_ERROR",
                "sql_query or table_name is required for mode='sql_mapping_suggest'",
                suggestion="Provide a SELECT query or table name to generate a mapping suggestion.",
            )
        preview_result = preview_sql(
            sql_source=sql_source,
            table_name=table_name,
            sql_query=sql_query,
        )
        if not preview_result.get("ok"):
            return preview_result

        preview_data = preview_result.get("data") or {}
        columns = preview_data.get("columns", [])
        rows = preview_data.get("rows", [])
        derived_table_name = (
            table_name or f"{preview_data.get('source_ref', {}).get('path', 'sql')}_preview"
        )

        mock_table_data = {
            "table_name": derived_table_name,
            "columns": [col["name"] for col in columns] if columns else [],
            "rows": rows,
        }
        suggestion = suggest_table_mapping(mock_table_data, mapping)
        return envelope_ok(
            {
                "mapping_suggestion": suggestion,
                "source_ref": preview_data.get("source_ref"),
                "columns": columns,
            },
            warnings=preview_result.get("warnings", []),
        )

    if mode == "sql_import":
        if not sql_query:
            return envelope_err(
                "VALIDATION_ERROR",
                "sql_query is required for mode='sql_import'",
                suggestion="Provide a SELECT query to import rows as graph data.",
            )

        table_result = execute_select_to_table_data(
            sql_source=sql_source,
            sql_query=sql_query,
            table_name=table_name,
        )
        if not table_result.get("ok"):
            return table_result

        table_data_output = (table_result.get("data") or {}).get("table_data")
        if table_data_output is None:
            return table_result

        mapped = import_table_data(table_data=table_data_output, mapping=mapping)
        if not mapped.get("ok"):
            return mapped

        mapped_graph_data = (mapped.get("data") or {}).get("graph_data")
        if mapped_graph_data is None:
            return mapped

        change_plan = graph_data_to_change_plan(mapped_graph_data)
        sql_hash_context = {
            "sql_source": sql_source,
            "sql_query": sql_query,
            "mapping": mapping,
        }
        import_result = manage_graph_data(
            mode="import",
            graph_data=mapped_graph_data,
            change_plan=change_plan,
            dry_run=dry_run,
            confirm=confirm,
            plan_hash=plan_hash,
            extra_hash_context=sql_hash_context,
        )

        return import_result

    return envelope_err(
        "VALIDATION_ERROR",
        f"Unknown SQL mode: {mode!r}.",
        details={"mode": mode},
    )

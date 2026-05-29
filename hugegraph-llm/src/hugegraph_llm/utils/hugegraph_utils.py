# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import asyncio
import json
import os
import shutil
from datetime import datetime

import httpx
from pyhugegraph.client import PyHugeClient

from hugegraph_llm import runtime
from hugegraph_llm.config import huge_settings, resource_path
from hugegraph_llm.utils.log import log

MAX_BACKUP_DIRS = 7
MAX_VERTICES = 100000
MAX_EDGES = 200000
BACKUP_DIR = str(os.path.join(resource_path, "backup-graph-data-4020", huge_settings.graph_name))


def run_gremlin_query(query, fmt=True):
    """Sync entry — used by Gradio buttons, admin API, and pycgraph nodes
    (already on a worker thread via `await asyncio.to_thread(pipeline.run)`).
    PyHugeClient is sync, so we just call it directly here."""
    res = get_hg_client().gremlin().exec(query)
    return json.dumps(res, indent=4, ensure_ascii=False) if fmt else res


async def arun_gremlin_query(query, fmt=True):
    """Async entry — for HTTP routes that want to call Gremlin without going
    through the pipeline. Pushes the sync PyHugeClient call to a worker thread
    so the event loop is not blocked."""
    return await asyncio.to_thread(run_gremlin_query, query, fmt)


def get_hg_client():
    return PyHugeClient(
        url=huge_settings.graph_url,
        graph=huge_settings.graph_name,
        user=huge_settings.graph_user,
        pwd=huge_settings.graph_pwd,
        graphspace=huge_settings.graph_space,
    )


def init_hg_test_data():
    client = get_hg_client()
    client.graphs().clear_graph_all_data()
    schema = client.schema()
    schema.propertyKey("name").asText().ifNotExist().create()
    schema.propertyKey("birthDate").asText().ifNotExist().create()
    schema.vertexLabel("Person").properties("name", "birthDate").useCustomizeStringId().ifNotExist().create()
    schema.vertexLabel("Movie").properties("name").useCustomizeStringId().ifNotExist().create()
    schema.edgeLabel("ActedIn").sourceLabel("Person").targetLabel("Movie").ifNotExist().create()

    schema.indexLabel("PersonByName").onV("Person").by("name").secondary().ifNotExist().create()
    schema.indexLabel("MovieByName").onV("Movie").by("name").secondary().ifNotExist().create()

    graph = client.graph()
    graph.addVertex("Person", {"name": "Al Pacino", "birthDate": "1940-04-25"}, id="Al Pacino")
    graph.addVertex(
        "Person",
        {"name": "Robert De Niro", "birthDate": "1943-08-17"},
        id="Robert De Niro",
    )
    graph.addVertex("Movie", {"name": "The Godfather"}, id="The Godfather")
    graph.addVertex("Movie", {"name": "The Godfather Part II"}, id="The Godfather Part II")
    graph.addVertex(
        "Movie",
        {"name": "The Godfather Coda The Death of Michael Corleone"},
        id="The Godfather Coda The Death of Michael Corleone",
    )

    graph.addEdge("ActedIn", "Al Pacino", "The Godfather", {})
    graph.addEdge("ActedIn", "Al Pacino", "The Godfather Part II", {})
    graph.addEdge("ActedIn", "Al Pacino", "The Godfather Coda The Death of Michael Corleone", {})
    graph.addEdge("ActedIn", "Robert De Niro", "The Godfather Part II", {})
    schema.getSchema()
    graph.close()
    return {
        "vertex": ["Person", "Movie"],
        "edge": ["ActedIn"],
        "property": ["name", "birthDate"],
        "index": ["PersonByName", "MovieByName"],
    }


def clean_hg_data():
    client = get_hg_client()
    client.graphs().clear_graph_all_data()


def create_dir_safely(path):
    if not os.path.exists(path):
        os.makedirs(path)


def backup_data():
    try:
        client = get_hg_client()
        create_dir_safely(BACKUP_DIR)

        date_str = datetime.now().strftime("%Y%m%d")
        backup_subdir = os.path.join(BACKUP_DIR, f"{date_str}")
        create_dir_safely(backup_subdir)

        files = {
            "vertices.json": f"g.V().limit({MAX_VERTICES})"
            f".aggregate('vertices').count().as('count').select('count','vertices')",
            "edges.json": f"g.E().limit({MAX_EDGES}).aggregate('edges').count().as('count').select('count','edges')",
            "schema.json": client.schema().getSchema(_format="groovy"),
        }

        vertexlabels = client.schema().getSchema()["vertexlabels"]
        all_pk_flag = all(data.get("id_strategy") == "PRIMARY_KEY" for data in vertexlabels)

        for filename, query in files.items():
            write_backup_file(client, backup_subdir, filename, query, all_pk_flag)

        log.info("Backup successfully in %s.", backup_subdir)
        relative_backup_subdir = os.path.relpath(backup_subdir, start=resource_path)
        del_info = manage_backup_retention()
        return f"Backup successfully in '{relative_backup_subdir}' \n{del_info}"
    except Exception as e:  # pylint: disable=W0718
        log.critical("Backup failed: %s", e, exc_info=True)
        raise Exception("Failed to execute backup") from e


def write_backup_file(client, backup_subdir, filename, query, all_pk_flag):
    with open(os.path.join(backup_subdir, filename), "w", encoding="utf-8") as f:
        if filename == "edges.json":
            data = client.gremlin().exec(query)["data"][0]["edges"]
            json.dump(data, f, ensure_ascii=False)
        elif filename == "vertices.json":
            data_full = client.gremlin().exec(query)["data"][0]["vertices"]
            data = (
                [{key: value for key, value in vertex.items() if key != "id"} for vertex in data_full]
                if all_pk_flag
                else data_full
            )
            json.dump(data, f, ensure_ascii=False)
        elif filename == "schema.json":
            data_full = query
            if isinstance(data_full, dict) and "schema" in data_full:
                groovy_filename = filename.replace(".json", ".groovy")
                with open(os.path.join(backup_subdir, groovy_filename), "w", encoding="utf-8") as groovy_file:
                    groovy_file.write(str(data_full["schema"]))
            else:
                data = data_full
                json.dump(data, f, ensure_ascii=False)


def manage_backup_retention():
    try:
        backup_dirs = [
            os.path.join(BACKUP_DIR, d) for d in os.listdir(BACKUP_DIR) if os.path.isdir(os.path.join(BACKUP_DIR, d))
        ]
        backup_dirs.sort(key=os.path.getctime)
        if len(backup_dirs) > MAX_BACKUP_DIRS:
            old_backup = backup_dirs.pop(0)
            shutil.rmtree(old_backup)
            log.info("Deleted old backup: %s", old_backup)
            relative_old_backup = os.path.relpath(old_backup, start=resource_path)
            return f"Deleted old backup: {relative_old_backup}"
        return f"The current number of backup files <= {MAX_BACKUP_DIRS}, so no files are deleted"
    except Exception as e:  # pylint: disable=W0718
        log.error("Failed to manage backup retention: %s", e, exc_info=True)
        raise Exception("Failed to manage backup retention") from e


# TODO: In the path demo/rag_demo/configs_block.py,
# there is a function test_api_connection that is similar to this function,
# but it is not straightforward to reuse
def _build_db_check_url(url: str, name: str, graph_space: str) -> str:
    if graph_space and graph_space.strip():
        return f"{url}/graphspaces/{graph_space}/graphs/{name}/schema"
    return f"{url}/graphs/{name}/schema"


_DB_CHECK_TIMEOUT = httpx.Timeout(connect=1.0, read=5.0, write=5.0, pool=2.0)


async def acheck_graph_db_connection(url: str, name: str, user: str, pwd: str, graph_space: str) -> bool:
    try:
        client = runtime.get_http_client()
        response = await client.get(
            _build_db_check_url(url, name, graph_space),
            timeout=_DB_CHECK_TIMEOUT,
            auth=(user, pwd),
        )
        return response.status_code == 200
    except (httpx.RequestError, httpx.HTTPStatusError, httpx.TimeoutException) as e:
        log.warning("GraphDB connection error: %s", str(e))
        return False
    except Exception as e:
        log.error("Unexpected connection error: %s", e, exc_info=True)
        raise Exception("Failed to execute update_vid_embedding") from e


def check_graph_db_connection(url: str, name: str, user: str, pwd: str, graph_space: str) -> bool:
    """Sync entry used by Gradio configs_block (often invoked at startup before
    lifespan registers a shared httpx client). Uses a one-shot httpx.Client."""
    try:
        with httpx.Client(timeout=_DB_CHECK_TIMEOUT) as client:
            response = client.get(_build_db_check_url(url, name, graph_space), auth=(user, pwd))
        return response.status_code == 200
    except (httpx.RequestError, httpx.HTTPStatusError, httpx.TimeoutException) as e:
        log.warning("GraphDB connection error: %s", str(e))
        return False
    except Exception as e:
        log.error("Unexpected connection error: %s", e, exc_info=True)
        raise Exception("Failed to execute update_vid_embedding") from e

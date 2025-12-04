# HugeGraph MCP

FastMCP-based Model Context Protocol server that enables AI assistants to directly query and manipulate HugeGraph databases through schema inspection and Gremlin operations.

**Why HugeGraph MCP?**

- 🧠 **AI-Native Graph Queries**: Let Claude, GPT, and other assistants directly query your graph data using natural language
- 🔒 **Secure & Controlled**: Built-in read-only mode for write operation protection
- ⚡ **Zero-Copy Integration**: No data export needed - AI works with your live HugeGraph instance
- 🛠️ **Full Graph Operations**: Schema inspection, Gremlin reads/writes, and multi-graph space support

**Architecture:**

```
IDE/Claude Desktop → MCP Protocol → HugeGraph MCP Server → HugeGraph Database
```

## Quick Start

Get HugeGraph MCP running in your IDE in 30 seconds without any installation:

### Prerequisites

- HugeGraph instance (e.g., `http://127.0.0.1:8080`) >= 1.7.0
- Python 3.10+ (handled automatically by uvx)
- Git in system PATH

### MCP Configuration

Add an MCP server entry to your IDE or assistant MCP configuration file. Example:

```json
{
  "mcpServers": {
    "hugegraph-mcp": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/hugegraph/hugegraph-ai.git@graph-mcp#subdirectory=hugegraph-mcp",
        "hugegraph-mcp"
      ],
      "env": {
        "HUGEGRAPH_MCP_READONLY": "true"
      }
    }
  }
}
```

Restart your IDE or assistant after adding the configuration.

#### Optional environment variables

The HugeGraph MCP server also respects the following environment variables. All of them are **optional**; if not set, the defaults below are used:

- `HUGEGRAPH_URL` (default: `http://127.0.0.1:8080`)
- `HUGEGRAPH_GRAPH_PATH` (default: `DEFAULT/hugegraph`)
- `HUGEGRAPH_USER` (default: `admin`)
- `HUGEGRAPH_PASSWORD` (default: empty string)

`HUGEGRAPH_GRAPH_PATH` uses the format `GRAPH_SPACE/GRAPH_NAME`, for example `DEFAULT/hugegraph`.

Note: uvx installs dependencies on first run. If dependency installation is slow or times out, some IDEs or assistants may report MCP load failure. To avoid this, pre-install the MCP locally by running:

```bash
uvx --from git+https://github.com/hugegraph/hugegraph-ai.git@graph-mcp#subdirectory=hugegraph-mcp hugegraph-mcp
```

After the command completes, restart your IDE or assistant.

## Features

- **📊 Live Schema Inspection**: Real-time vertex labels, edge labels, properties, and indexes
- **🔍 Gremlin Read Queries**: Execute read-only Gremlin traversals safely
- **✏️ Schema Operations**: Create/modify vertex labels, edge labels, and property keys
- **📝 Gremlin Writes**: Execute data modification queries
- **🔐 Security Controls**: Read-only mode protection

## License

Apache License 2.0

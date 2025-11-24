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

- HugeGraph instance (e.g., `http://127.0.0.1:8080`)
- Python 3.10+ (handled automatically by uvx)
- Git in system PATH

### Windsurf Configuration

Add this to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "hugegraph": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/hugegraph/hugegraph-ai.git#subdirectory=hugegraph-mcp",
        "hugegraph-mcp"
      ],
      "env": {
        "HUGEGRAPH_URL": "http://127.0.0.1:8080",
        "HUGEGRAPH_GRAPH_NAME": "hugegraph",
        "HUGEGRAPH_USER": "admin",
        "HUGEGRAPH_PASSWORD": "secret",
        "HUGEGRAPH_MCP_READONLY": "true"
      }
    }
  }
}
```

### Claude Desktop Configuration

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or equivalent:

```json
{
  "mcpServers": {
    "hugegraph": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/hugegraph/hugegraph-ai.git#subdirectory=hugegraph-mcp",
        "hugegraph-mcp"
      ],
      "env": {
        "HUGEGRAPH_URL": "http://127.0.0.1:8080",
        "HUGEGRAPH_GRAPH_NAME": "hugegraph",
        "HUGEGRAPH_USER": "admin",
        "HUGEGRAPH_PASSWORD": "secret",
        "HUGEGRAPH_MCP_READONLY": "true"
      }
    }
  }
}
```

**Restart your IDE** - you're done! The AI assistant can now query your HugeGraph database.

## Features

- **📊 Live Schema Inspection**: Real-time vertex labels, edge labels, properties, and indexes
- **🔍 Gremlin Read Queries**: Execute read-only Gremlin traversals safely
- **✏️ Schema Operations**: Create/modify vertex labels, edge labels, and property keys
- **📝 Gremlin Writes**: Execute data modification queries
- **🔐 Security Controls**: Read-only mode protection

## License

Apache License 2.0

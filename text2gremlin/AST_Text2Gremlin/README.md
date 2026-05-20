# Text2Gremlin Corpus Generalization

[English](README.md) | [中文](./README_zh.md)

Generate a large and diverse set of Gremlin queries and their corresponding natural language descriptions based on ASTs and templates, and perform multi-stage data augmentation and preference data synthesis using LLMs for training and evaluating text-to-Gremlin models.

## Quick Start

### 1. Environment Setup
Python version: 3.12.10
```bash
pip install -r requirements.txt
```

### 2. Configuration
Copy the example config and fill in your settings:
```bash
cp config_example.json config.json
```

Edit `config.json` with your LLM API configuration:
```json
"llm": {
    "base_url": "http://your-llm-server:port/v1",
    "api_key": "your-api-key",
    "model": "your-model-name",
    "temperature": 1.0,
    "max_retries": 3,
    "max_concurrency": 5,
    "save_interval": 50,
    "timeout": 40
}
```

> ⚠️ `config.json` contains sensitive information and is excluded via `.gitignore`. Do not commit it.

### 3. Running

#### Stage 1: AST Generalization
```bash
python generate_corpus.py
```

#### Stages 2–5: LLM Augmentation Pipeline
```bash
# Run all LLM augmentation stages (translate → migrate → merge → DPO)
python run_llm_pipeline.py

# Start from a specific stage
python run_llm_pipeline.py --stage migrate

# Run a single stage
python run_llm_pipeline.py --stage merge --stop merge
```

Each stage can also be run independently:
```bash
# Multi-style translation
python -m llm_augment.generalize_llm

# Scenario migration
python -m llm_augment.migrate_scenario

# Dataset merging
python -m llm_augment.merge_dataset

# DPO preference data generation
python -m llm_augment.generate_dpo_data
```

#### Syntax Analysis
```bash
python analyze_syntax.py
```

---

## Data Generation Pipeline

```text
Stage 1: AST Generalization    generate_corpus.py
          251 templates → ~1500 entries (query + simple description)
               ↓
Stage 2: LLM Multi-style       llm_augment/generalize_llm.py
          Translation
          ×6 styles → ~9000 entries (4 fixed + 2 random tones)
               ↓
Stage 3: Scenario Migration     llm_augment/migrate_scenario.py
          ×20 domains → ~30000 entries (balanced CRUD, syntax-checked)
               ↓
Stage 4: Dataset Merging        llm_augment/merge_dataset.py
          Merge translations + migrations → unified text2gremlin dataset
               ↓
Stage 5: DPO Preference Data    llm_augment/generate_dpo_data.py
          Type A (multi-task) + Type B (single-task) + Type C (long-chain)
          → ~8900 preference pairs (21 domains)
```

---

## Project Structure

```text
├── generate_corpus.py          # AST generalization entry point
├── run_llm_pipeline.py         # Unified LLM pipeline runner
├── analyze_syntax.py           # Gremlin syntax distribution analysis
├── gremlin_templates.csv       # Query templates (251 entries)
├── config.json                 # Configuration (gitignored)
├── config_example.json         # Configuration example
├── requirements.txt            # Python dependencies
│
├── llm_augment/                # LLM augmentation package
│   ├── __init__.py
│   ├── generalize_llm.py       # Stage 2: Multi-style translation
│   ├── migrate_scenario.py     # Stage 3: Scenario migration
│   ├── merge_dataset.py        # Stage 4: Dataset merging
│   └── generate_dpo_data.py    # Stage 5: DPO preference data
│
├── base/                       # AST generalization core engine
│   ├── generator.py            # Generalization controller + syntax checker
│   ├── Config.py               # Configuration management
│   ├── Schema.py               # Schema and data management
│   ├── GremlinParse.py         # Data structure definitions
│   ├── GremlinExpr.py          # Complex expressions (predicates, anonymous traversals)
│   ├── GremlinTransVisitor.py  # AST parsing
│   ├── TraversalGenerator.py   # Traversal generator
│   ├── GremlinBase.py          # Translation engine
│   ├── gremlin/                # ANTLR-generated Gremlin parser
│   └── template/               # Translation dictionaries
│
├── db_data/                    # Data and schemas
│   ├── schema/                 # Graph database schemas
│   └── reference/              # Multi-domain schemas for migration
│
└── output/                     # Output directory
    └── preference_data/        # DPO preference data
```

---

## Configuration

### LLM Configuration (`config.json` → `llm`)

| Field | Description | Default |
|-------|-------------|---------|
| base_url | LLM API endpoint | Required |
| api_key | API key | Required |
| model | Model name | Required |
| temperature | Sampling temperature | 1.0 |
| max_retries | Max retries per item | 3 |
| max_concurrency | Concurrent requests | 5 |
| save_interval | Incremental save interval | 50 |
| timeout | Request timeout (seconds) | 40 |

### Template File (`gremlin_templates.csv`)

| Column | Description | Example |
|--------|-------------|---------|
| template | Gremlin query template | `g.V().hasLabel('person')` |
| description | Template description (optional) | Query all persons |

### Combination Control (`base/combination_control_config.json`)

Controls query generation volume during AST generalization:
- Chain length categories: short (≤4 steps), medium (5–6), long (7–8), extra-long (≥9)
- Data value filling: 1 value for intermediate steps, 2–3 for terminal steps
- Property generalization: dynamically adjusted based on chain length

---

## Output Formats

### AST Generalization (`generated_corpus_*.json`)
```json
{
  "metadata": { "total_unique_queries": 1564, "..." : "..." },
  "corpus": [
    { "query": "g.V().hasLabel('person')", "description": "..." }
  ]
}
```

### LLM Translation (`llm_translated_*.json`)
```json
{
  "corpus": [
    {
      "query": "g.V().hasLabel('person')",
      "translations": [
        { "style": "zh_formal", "text": "查询所有人类型的顶点" },
        { "style": "en_casual", "text": "Find all person nodes" }
      ]
    }
  ]
}
```

### Scenario Migration (`migrated_*.json`)
```json
{
  "migrations": [
    {
      "target_domain": "ecommerce",
      "generated_samples": [
        { "operation": "read", "query": "g.V()...", "natural_language": "..." }
      ]
    }
  ]
}
```

### DPO Preference Data (`preference_data/dpo_data_merged.json`)
```json
{
  "metadata": {
    "total_samples": 8920,
    "rejected_count": 3032,
    "type_distribution": { "A": 4380, "B": 2318, "C": 2222 },
    "domain_distribution": { "movie": 401, "ecommerce": 399, "..." : "..." },

  },
  "samples": [
    {
      "task_id": "pref_MOVI_A_0001",
      "task_type": "A",
      "domain": "movie",
      "source_queries": [
        { "text": "Query all actors", "gremlin": "g.V().hasLabel('person')" }
      ],
      "input": { "instruction": "Please query all actors and update..." },
      "chosen": { "style": "groovy", "code": "def actors = g.V()..." },
      "rejected": { "style": "gremlin", "code": "g.V().hasLabel..." },
      "preference_reason": ["Groovy style is clearer...", "..."]
    }
  ]
}
```

---

## Key Features

### AST Generalization
Generates multiple variants from a single template with intelligent combinatorial control and automatic deduplication:
```text
Template: g.V().hasLabel('person').out('acted_in')
  → g.V().hasLabel('movie').out('acted_in')
  → g.V().hasLabel('person').out('directed')
  → ...
```

### LLM Multi-style Translation
Each query is translated into 6 styles (4 fixed + 2 random):
- Chinese formal / Chinese casual / English formal / English casual
- Mixed Chinese-English / Abbreviated / Q&A style / With typos

### Scenario Migration
Migrates movie-domain data to 20 business domains with balanced CRUD operations. Every generated Gremlin query is validated via ANTLR syntax checking.

### DPO Preference Data
Three task types generate Groovy vs Gremlin preference pairs across 21 domains (movie + 20 migrated), totaling 8920 samples:

- **Type A (Multi-task Composition, 4380 samples)**: Combines 2–5 simple queries into a composite task
  - chosen: Groovy imperative style (def variables, .next(), return map)
  - rejected: Pure Gremlin functional style (as/select/project forced into a single chain)
  - Automatically detects command conflicts (e.g., delete before update), reorders or rejects
- **Type B (Single Task, 2318 samples)**: Simple queries that don't need Groovy wrapping
  - chosen: Original pure Gremlin
  - rejected: Over-engineered Groovy wrapper
- **Type C (Long-chain Decomposition, 2222 samples)**: Complex long-chain queries decomposed into steps
  - chosen: Groovy multi-step style
  - rejected: Original long-chain Gremlin

### Pipeline Features
- Concurrency control: `asyncio.wait(FIRST_COMPLETED)` + Semaphore + batched task creation
- Incremental saving: auto-saves every 50 items, supports resumption
- Pydantic validation: strict format validation for all LLM outputs
- ANTLR syntax checking: pure Gremlin code is syntax-validated (Groovy code is skipped due to variable reference incompatibility with ANTLR)
- Per-item retry: failed items retry with exponential backoff without affecting others
- No-comment policy: all generated Groovy/Gremlin code is comment-free

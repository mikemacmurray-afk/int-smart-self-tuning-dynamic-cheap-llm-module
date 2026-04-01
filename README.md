# Smart LLM

**Self-tuning model selector for free/cheap LLMs.**

A standalone Python package that dynamically selects and calls free or very cheap LLMs for operational tasks — file processing, text extraction, classification, formatting — where deep thinking is not required and supermodel costs are not justified.

## Quick Start

```python
from smart_llm import SmartLLM

llm = SmartLLM(api_key="sk-or-your-openrouter-key")

# Simple text response
result = await llm.ask("Summarize this text in 2 sentences: ...")

# JSON extraction
data = await llm.ask_json("Extract name and date from: Invoice from Acme Corp dated 2026-03-15")
# {"name": "Acme Corp", "date": "2026-03-15"}
```

## How It Works

Smart LLM manages a **self-tuning registry** of LLM models that automatically:

1. **Probes models** every 15 minutes to check health, speed, and throttle status
2. **Ranks models** using a composite score: 60% live probe data + 40% historical success patterns
3. **Falls back automatically** through the ranked list if a model fails
4. **Discovers new models** monthly via OpenRouter's catalogue API
5. **Retires dead models** that are no longer available
6. **Emergency rescans** when all free models are failing

### Priority Chain

```
Local model (Ollama/LM Studio) → Free OpenRouter → Cheap OpenRouter → Paid (last resort)
```

## Installation

```bash
# Copy the smart_llm/ folder into your project, then:
pip install openai httpx aiosqlite
```

## Configuration

### Constructor Arguments

```python
llm = SmartLLM(
    api_key="sk-or-...",                    # OpenRouter API key
    storage="sqlite",                       # "sqlite" | "mysql" | "json"
    storage_path="./smart_llm.db",          # File path for sqlite/json
    storage_url="mysql://user:pass@host/db",# Connection URL for mysql
    local_url="http://localhost:11434",      # Ollama/LM Studio URL
    local_model="qwen2.5:7b",              # Preferred local model
    log_retention_days=7,                   # Rolling log window
    probe_interval_minutes=15,              # Health check frequency
    scan_interval_days=30,                  # Catalogue scan frequency
)
```

### Environment Variables

```bash
SMART_LLM_API_KEY=sk-or-...
SMART_LLM_STORAGE=sqlite
SMART_LLM_STORAGE_PATH=./smart_llm.db
SMART_LLM_LOCAL_URL=http://localhost:11434
SMART_LLM_LOCAL_MODEL=qwen2.5:7b
SMART_LLM_PROBE_MINUTES=15
SMART_LLM_SCAN_DAYS=30
SMART_LLM_LOG_DAYS=7
```

## Storage Backends

| Backend | Best For | Dependency |
|---------|----------|------------|
| **SQLite** (default) | Local scripts, development, single-process apps | None (stdlib) |
| **MySQL** | Production servers, multi-process apps | `sqlalchemy`, `pymysql` |
| **JSON** | Debugging, simple scripts, human-readable state | None (stdlib) |

## Operational Oversight

```python
# Health check
print(llm.status())
# {"health": "ok", "active_free": 5, "active_cheap": 3, "top_model": "google/gemma-3-27b-it:free"}

# Recent call log
for log in llm.get_logs(hours=24):
    print(f"{log.model_id}: {log.status} {log.response_ms}ms")

# Current rankings
for model, score in llm.get_ranked_models():
    print(f"{model}: {score:.2f}")

# Manual probe
results = await llm.probe_all()

# Manual catalogue scan
summary = await llm.scan_catalogue()
```

## Local Model Support

If you have Ollama or LM Studio running locally:

```python
llm = SmartLLM(
    api_key="sk-or-...",                    # Still needed as fallback
    local_url="http://localhost:11434",      # Ollama default port
    local_model="qwen2.5:7b",              # Your preferred local model
)
# Local model is tried FIRST — zero cost, zero latency dependency
# Falls back to OpenRouter if local is down
```

## Architecture

```
SmartLLM Client
├── Model Selector Engine
│   ├── Probe Manager (15-min health checks)
│   ├── Ranker (composite scoring)
│   └── Registry (monthly catalogue scan)
├── Provider Layer
│   ├── OpenRouter Provider
│   └── Local Provider (Ollama/LM Studio)
└── Storage Backend
    ├── SQLite (default)
    ├── MySQL
    └── JSON File
```

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## License

MIT

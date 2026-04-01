# Smart LLM Module — Architecture & Design

> See full design artifact in conversation artifacts.
> This is a workspace reference copy.

**Purpose:** Standalone, self-tuning Python module for dynamic selection of free/cheap LLMs.

**Key decisions:**
- Storage: Pluggable (SQLite default, MySQL, JSON file)
- Providers: OpenRouter + Local models (Ollama/LM Studio)
- Priority: Local → Free → Cheap → Paid
- Interface: SmartLLM client with automatic fallback
- Logging: 7-day rolling window
- Packaging: Self-contained `smart_llm/` folder

**See full design:** `smart-llm-design.md` in conversation artifacts

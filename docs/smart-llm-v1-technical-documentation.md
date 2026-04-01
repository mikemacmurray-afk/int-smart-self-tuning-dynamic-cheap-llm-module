# Smart LLM — Version 1.0.0 Technical Documentation

**Date:** 2026-04-01  
**Project:** int-smart-self-tuning-dynamic-cheap-llm-module  
**Version:** v1.0.0 (Release)

---

## 1. Overview

### 1.1 Purpose
The **Smart LLM** module is a standalone, self-tuning Python package designed to provide cost-optimized, resilient LLM calls. It specifically targets "operational" tasks—extracting data, formatting text, or simple classification—where the high intelligence of "frontier" models (like GPT-4o or Claude 3.5 Sonnet) is not required, yet costs can accumulate quickly.

### 1.2 Core Philosophy
- **Local Priority:** Always prefer locally running models (Ollama, LM Studio) if available, incurring zero external costs.
- **Dynamic Selection:** Never hardcode a "free" model; instead, maintain a live registry and rank them by actual performance.
- **Resilient Fallback:** Automatically cascade through increasingly capable (and expensive) tiers if preferred models fail.
- **Self-Cleaning:** Maintain a rolling 7-day log for oversight without bloating storage.

---

## 2. Architecture

The system follows a **Smart Client** pattern, where all selection logic is handled locally by the `SmartLLM` instance.

### 2.1 Component Overview
- **Storage Backend:** Pluggable layer (`SQLite`, `MySQL`, `JSON`) for persisting the model registry, probe results, and call history.
- **Provider Layer:** Standardized interface for `OpenRouter` and `Local` (OpenAI-compatible) API calls.
- **Selector Engine:** The "brain" that calculates model rankings based on a composite score of live health probes and historical success rates.
- **Registry Manager:** A background task handler that periodically scans the OpenRouter model catalogue, discovers new free models, and retires dead ones.

### 2.2 Unified Data Model
All components communicate using standard dataclasses defined in `smart_llm/data_models.py`:
- `ModelInfo`: Metadata for a registered model (ID, Tier, Provider, Status).
- `ProbeResult`: Results of the 15-minute background health checks.
- `CallRecord`: Detailed stats of every production LLM call, used for historical scoring.
- `ProviderResponse`: Standardized output from any LLM provider.

---

## 3. Storage Backends

Smart LLM supports three storage strategies to fit different deployment environments.

### 3.1 SQLite (Default)
- **Use Case:** Local scripts and single-host applications.
- **Implementation:** Uses Python’s standard library `sqlite3` in **WAL (Write-Ahead Logging)** mode.
- **Pros:** Zero dependencies, high performance on local disk, thread-safe.

### 3.2 MySQL / PostgreSQL
- **Use Case:** Production servers with multiple app instances sharing a single model registry.
- **Implementation:** Uses `SQLAlchemy Core`.
- **Requirements:** `sqlalchemy` + `pymysql` (MySQL) or `psycopg2` (PostgreSQL).

### 3.3 JSON File
- **Use Case:** Debugging, manual oversight, and very lightweight scripts.
- **Implementation:** A single `smart_llm_state.json` file.
- **Pros:** Human-readable, easy to sync via Git or shared drives.

---

## 4. Providers & Selection Logic

### 4.1 Ranking Algorithm (Composite Score)
Models are ranked using the following formula:
`Score = (ProbeScore × 0.6) + (HistoryScore × 0.4)`

1. **Probe Score (60%):** Based on the most recent 15-minute health check.
   - `1.0`: Success < 3s latency.
   - `0.7`: Success but slow (3-8s).
   - `0.1`: Rate limited (429).
   - `0.05`: Total failure (timeout/error).
2. **History Score (40%):** Success rate over the last 7 days.
   - Specifically matches the **current day of the week** and **+/- 2 hours** to account for time-of-day traffic patterns (e.g., peak US hours causing congestion).

### 4.2 Dynamic Timeout Calculation
The system calculates a "Per-Attempt Timeout" based on the healthiest model in the list:
- **12 Seconds (Aggressive):** If the best model responded < 3s in its last probe.
- **25 Seconds (Standard):** If models are working but slow.
- **35 Seconds (Conservative):** If no recent probe data is available.

### 4.3 Catalogue Management (Registry)
The `RegistryManager` performs two types of maintenance scans:
- **Monthly Scan:** Full discovery of new models from the OpenRouter API.
- **Emergency Scan:** Triggered if **all** free models have failed for more than 2 hours.

Each new candidate model undergoes a **Quality Probe**—a challenge response test ensuring it can return valid JSON before being promoted to "Active" status.

---

## 5. API Reference

### 5.1 The `SmartLLM` Client
The primary entry point.

```python
llm = SmartLLM(api_key="...", storage="sqlite")

# ask(): Simple text interface
text = await llm.ask("Describe the weather in 3 words.")

# ask_json(): Auto-extracts JSON from responses (robust to markdown fences)
data = await llm.ask_json("Extract invoice data from this text: ...")
```

### 5.2 Operational Methods
Methods for oversight and manual control:
- `status()`: Returns a health report (model counts, top-ranked model, scan status).
- `get_ranked_models()`: Returns the current sorted list of models and their scores.
- `get_logs(hours=24)`: Returns recent `CallRecord` entries.
- `probe_all()`: Triggers an immediate health check of all free models.
- `scan_catalogue()`: Manually trigger a discovery scan.

---

## 6. Implementation Notes

### 6.1 Local Model Priority
If `local_url` is provided (e.g., `http://localhost:11434`), Smart LLM will **always** attempt to reach the local server before touching any cloud provider. It checks for OpenAI-compatible model names and falls back silently to OpenRouter if the local server is down or returns errors.

### 6.2 Error Handling & Fallback
The `_call_with_fallback` method implements a "Cascade" logic:
1. Try **Local**.
2. Try **Free** models (Ranked highest to lowest).
3. Try **Cheap** paid models (e.g., Gemini Flash Lite, Llama 8B).
4. Try **Paid** fallback models (Guaranteed availability).

If any step fails, the failure is recorded in the storage backend to instantly update the rank for the next call.

---

## 7. Operational Oversight

For human-in-the-loop monitoring, use the provided `status()` API. It is designed to be plugged into monitoring dashboards or simple CLI tools.

**Example Health Summary:**
```json
{
  "health": "ok",
  "active_free": 12,
  "top_model": "google/gemma-3-27b-it:free",
  "top_score": 0.92,
  "total_history": 842,
  "last_scan": "2026-03-31T12:00:00Z"
}
```

---

*Documentation Version 1.0.0*  
*Created by Antigravity AI Architect*

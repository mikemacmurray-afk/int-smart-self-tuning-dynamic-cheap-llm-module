"""
Smart LLM — Self-tuning model selector for free/cheap LLMs.

A standalone, self-contained Python package that dynamically selects
and calls free or very cheap LLMs for operational tasks.

Usage:
    from smart_llm import SmartLLM

    llm = SmartLLM(api_key="sk-or-...")
    result = await llm.ask("Summarize this text: ...")
    data = await llm.ask_json("Extract the name and date: ...")

Priority chain: Local model → Free OpenRouter → Cheap → Paid (last resort)
"""

__version__ = "0.1.0"

from smart_llm.client import SmartLLM
from smart_llm.config import SmartLLMConfig
from smart_llm.data_models import CallRecord, ModelInfo, ProbeResult, ProviderResponse

__all__ = [
    "SmartLLM",
    "SmartLLMConfig",
    "ModelInfo",
    "ProbeResult",
    "CallRecord",
    "ProviderResponse",
]

# excel_ai_assistant/config.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "openai"  # logical name
    model: str = "openai/gpt-oss-20b"
    temperature: float = 0.1
    max_tokens: int = 800
    timeout_seconds: int = 60


@dataclass(frozen=True)
class AnalyzerConfig:
    max_sample_rows_per_sheet: int = 5
    max_sheets_in_context: int = 10
    max_text_tokens: int = 4000  # logical bound for overall context


@dataclass(frozen=True)
class AppConfig:
    llm: LLMConfig = LLMConfig()
    analyzer: AnalyzerConfig = AnalyzerConfig()
    openai_api_key: Optional[str] = None  # or load from env in your app layer

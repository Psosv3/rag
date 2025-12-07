# excel_ai_assistant/exceptions.py
from __future__ import annotations


class ExcelAIError(Exception):
    """Base exception for the excel_ai_assistant package."""


class ExcelLoadError(ExcelAIError):
    """Raised when there is a problem loading or parsing an Excel file."""


class LLMError(ExcelAIError):
    """Raised when there is a problem communicating with the LLM provider."""

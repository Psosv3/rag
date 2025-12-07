# excel_ai_assistant/analyzer.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .config import AnalyzerConfig
from .models import WorkbookSummary

_DEFAULT_SYSTEM_PROMPT: Final[str] = (
    "You are an assistant specialized in understanding Excel workbooks.\n"
    "You will receive:\n"
    "1) A structured summary of all sheets in the workbook.\n"
    "2) A question from the user.\n\n"
    "Rules:\n"
    "- Use only the information in the summary; do not invent data.\n"
    "- If you cannot answer with high confidence from the summary, say so explicitly.\n"
    "- When referencing cells or sheets, be precise (e.g., 'Sheet1!B5').\n"
)


@dataclass
class WorkbookAnalyzer:
    config: AnalyzerConfig

    def build_llm_prompt(self, workbook: WorkbookSummary, question: str) -> str:
        """
        Convert the workbook summary + question into a single prompt string.
        """
        context_text = workbook.to_text(max_sheets=self.config.max_sheets_in_context)

        # Optionally, we could truncate tokens here using a tokenizer.
        # For now we rely on limits in config and sheet sampling.
        parts = [
            "=== WORKBOOK SUMMARY START ===",
            context_text,
            "=== WORKBOOK SUMMARY END ===",
            "",
            "=== USER QUESTION ===",
            question,
            "=== END ===",
        ]
        return "\n".join(parts)

    @property
    def default_system_prompt(self) -> str:
        return _DEFAULT_SYSTEM_PROMPT

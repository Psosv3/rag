# excel_ai_assistant/qa_engine.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from .analyzer import WorkbookAnalyzer
from .config import AppConfig
from .excel_loader import ExcelWorkbookLoader
from .llm_client import LLMClient, OpenAILLMClient


@dataclass
class ExcelQASystem:
    """
    High-level interface for:
      - loading an Excel file,
      - understanding its structure,
      - answering a natural language question about it.
    """

    config: AppConfig
    loader: ExcelWorkbookLoader
    analyzer: WorkbookAnalyzer
    llm_client: LLMClient

    @classmethod
    def with_openai(cls, config: Optional[AppConfig] = None) -> "ExcelQASystem":
        """
        Convenience constructor using OpenAI as the LLM backend.
        Expects OPENAI_API_KEY in the environment or provided via config.
        """
        cfg = config or AppConfig()
        loader = ExcelWorkbookLoader()
        analyzer = WorkbookAnalyzer(config=cfg.analyzer)
        llm_client = OpenAILLMClient(config=cfg.llm, api_key=cfg.openai_api_key)
        return cls(config=cfg, loader=loader, analyzer=analyzer, llm_client=llm_client)

    def answer_question(self, source: Union[str, Path, bytes], question: str, *, file_id: Optional[str] = None) -> str:
        """
        Main entrypoint.

        :param source: Excel file path or bytes.
        :param question: User's natural language question.
        :param file_id: Optional logical ID for the file (e.g., for logging/tracking).
        :return: LLM-generated answer string.
        """
        # 1) Load + summarize the workbook
        workbook_summary = self.loader.load_summary(source = source,
                                                    file_id = file_id,
                                                    max_sample_rows_per_sheet = self.config.analyzer.max_sample_rows_per_sheet,
                                                    )
        print(f"\n********\nDEBUG in qa_engine.py Workbook summary built. Sheets included:\n{workbook_summary}\n########")
        # 2) Build the textual prompt that will be sent to the LLM
        prompt = self.analyzer.build_llm_prompt(workbook = workbook_summary,
                                                question = question)
        print(f"\n********\nDEBUG in qa_engine.py Prompt built: \n{len(prompt)}\n########")
        # 3) Call the LLM with that prompt
        answer = self.llm_client.generate(prompt,
                                          system_prompt = self.analyzer.default_system_prompt)
        
        return answer

# excel_ai_assistant/cli.py
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from .config import AppConfig, LLMConfig, AnalyzerConfig
from .qa_engine import ExcelQASystem

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


def build_app_config() -> AppConfig:
    openai_api_key = os.getenv("OPENAI_API_KEY")
    llm_cfg = LLMConfig(
        provider="openai",
        model=os.getenv("EXCEL_AI_LLM_MODEL", "openai/gpt-oss-20b"),
        temperature=float(os.getenv("EXCEL_AI_LLM_TEMPERATURE", "0.1")),
        max_tokens=int(os.getenv("EXCEL_AI_LLM_MAX_TOKENS", "800")),
        timeout_seconds=int(os.getenv("EXCEL_AI_LLM_TIMEOUT", "60")),
    )
    analyzer_cfg = AnalyzerConfig(
        max_sample_rows_per_sheet=int(os.getenv("EXCEL_AI_MAX_SAMPLE_ROWS", "5")),
        max_sheets_in_context=int(os.getenv("EXCEL_AI_MAX_SHEETS", "10")),
        max_text_tokens=int(os.getenv("EXCEL_AI_MAX_TEXT_TOKENS", "4000")),
    )
    return AppConfig(llm=llm_cfg, analyzer=analyzer_cfg, openai_api_key=openai_api_key)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ask questions about an Excel workbook using an LLM."
    )
    parser.add_argument("excel_path", type=str, help="Path to the Excel .xlsx file.")
    parser.add_argument("question", type=str, help="Question you want to ask.")

    args = parser.parse_args()
    excel_path = Path(args.excel_path)
    question = args.question

    if not excel_path.exists():
        raise SystemExit(f"File not found: {excel_path}")

    config = build_app_config()
    qa_system = ExcelQASystem.with_openai(config=config)
    answer = qa_system.answer_question(source=excel_path, question=question)
    print("\n=== ANSWER ===")
    print(answer)


if __name__ == "__main__":
    main()

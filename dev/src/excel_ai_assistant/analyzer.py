# excel_ai_assistant/analyzer.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .config import AnalyzerConfig
from .models import WorkbookSummary

_DEFAULT_SYSTEM_PROMPT: Final[str] = (
"Vous êtes un assistant qui lit des données de classeurs Excel compacté en texte."
"Vous recevez un texte structuré répréseantant le contenu du classeur ainsi qu'une question de l'utilisateur."
"Réécrivez tout sous forme de texte. Ne pas reproduire les structures des tableaux."
"Faites très attention aux détails, aux significations et aux relations implicites entre les données."
"Reproduire tout exactement comme dans le contenu fourni (chiffre, valeur,..)."
"Interdiction de faire des suppositions ou d'inventer des informations non présentes dans le contenu fourni."
)


@dataclass
class WorkbookAnalyzer:
    config: AnalyzerConfig

    def build_llm_prompt(self, workbook: WorkbookSummary) -> str:
        """
        Convert the workbook summary into a readable single prompt string.
        """
        context_text = workbook.to_text(max_sheets=self.config.max_sheets_in_context)

        # Optionally, we could truncate tokens here using a tokenizer.
        # For now we rely on limits in config and sheet sampling.
        return context_text

    @property
    def default_system_prompt(self) -> str:
        return _DEFAULT_SYSTEM_PROMPT

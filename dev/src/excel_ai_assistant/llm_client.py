# excel_ai_assistant/llm_client.py
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from .config import LLMConfig
from .exceptions import LLMError

# from langfuse.openai import OpenAI
from groq import Groq

import os
from dotenv import load_dotenv

###
load_dotenv()
assert os.getenv("OPENAI_API_KEY") 
assert os.getenv("MISTRAL_API_KEY") 
assert os.getenv("GROQ_API_KEY") 
assert os.getenv("BASETEN_API_KEY") 
openai_key = os.getenv("OPENAI_API_KEY")
mistral_api_key = os.getenv("MISTRAL_API_KEY")
groq_api_key = os.getenv("GROQ_API_KEY")
baseten_api_key = os.getenv("BASETEN_API_KEY")

logger = logging.getLogger(__name__)

class LLMClient(ABC):
    """Abstract interface for a large language model."""

    @abstractmethod
    def generate(self,
                 prompt: str,
                 *,
                 system_prompt: Optional[str] = None,
                 temperature: Optional[float] = 0.0,
                 max_tokens: Optional[int] = 4096,
                 ) -> str:
        """Generate text from a prompt."""


class OpenAILLMClient(LLMClient):
    """
    Example implementation using the official OpenAI Python SDK.

    Requires:
        pip install openai
    And environment variable:
        OPENAI_API_KEY=<your key>
    Or pass api_key to the constructor.
    """

    def __init__(self, config: LLMConfig, api_key: Optional[str] = None) -> None:
        self._config = config
        self._api_key = api_key
        self._client = Groq(api_key=groq_api_key)

    def generate(self, prompt: str, *, system_prompt: Optional[str] = None, temperature: Optional[float] = None, max_tokens: Optional[int] = None,) -> str:
        from openai import APIError  # type: ignore[import]

        system_prompt = system_prompt or ("Vous êtes un assistant qui analyse des classeurs Excel. Vous recevez un résumé textuel structuré du classeur ainsi qu’une question de l’utilisateur. Répondez uniquement à partir du résumé fourni. Si l’information nécessaire n’est pas présente, indiquez que vous ne pouvez pas répondre.")

        temp = temperature if temperature is not None else self._config.temperature
        max_toks = max_tokens if max_tokens is not None else self._config.max_tokens

        try:
            response = self._client.chat.completions.create(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=temp,
                max_tokens=max_toks,
            )
        except APIError as exc:  # noqa: BLE001
            logger.exception("LLM API error")
            raise LLMError(f"LLM API error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error calling LLM")
            raise LLMError(f"Unexpected error calling LLM: {exc}") from exc

        try:
            content = response.choices[0].message.content
            if not content:
                raise LLMError("LLM returned empty content.")
            return content
        except (KeyError, IndexError, AttributeError) as exc:
            logger.exception("Failed to parse LLM response")
            raise LLMError(f"Failed to parse LLM response: {exc}") from exc

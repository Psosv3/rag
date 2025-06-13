from langchain_mistralai.chat_models import ChatMistralAI
import os

openai_key = os.getenv("OPENAI_API_KEY")
mistral_api_key = os.getenv("MISTRAL_API_KEY")

mistral_llm = ChatMistralAI(
    api_key=mistral_api_key,
    model="mistral-small-latest",
    temperature=0.7,
)
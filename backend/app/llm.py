# app/llm.py
from openai import AsyncOpenAI, AsyncAzureOpenAI
from .settings import settings


def build_llm():
    if settings.llm_provider == "fake":
        from .llm_fake import fake_llm
        return fake_llm
    if settings.llm_provider == "azure":
        return AsyncAzureOpenAI(
            api_key=settings.llm_api_key,
            azure_endpoint=settings.azure_endpoint,
            api_version=settings.azure_api_version,
        )
    # OpenAI proper (base_url None) or Ollama's OpenAI-compatible endpoint
    return AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )


llm = build_llm()


def set_llm(client: any) -> None:
    global llm
    llm = client

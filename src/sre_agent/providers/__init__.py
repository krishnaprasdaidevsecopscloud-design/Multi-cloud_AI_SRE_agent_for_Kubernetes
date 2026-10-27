from sre_agent.config import Settings
from sre_agent.providers.base import LLMProvider


def build_provider(settings: Settings) -> LLMProvider:
    if settings.provider == "bedrock":
        from sre_agent.providers.bedrock import BedrockProvider

        return BedrockProvider(settings)
    from sre_agent.providers.azure_openai import AzureOpenAIProvider

    return AzureOpenAIProvider(settings)

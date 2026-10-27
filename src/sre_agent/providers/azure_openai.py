"""Azure OpenAI provider (chat completions with function/tool calling)."""

from __future__ import annotations

import json

from openai import AzureOpenAI

from sre_agent.config import Settings
from sre_agent.providers.base import (
    LLMProvider,
    Message,
    ModelResponse,
    ToolCall,
    ToolSpec,
)


def _build_client(settings: Settings) -> AzureOpenAI:
    if settings.azure_openai_api_key:
        return AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )
    # Keyless: Entra ID via managed identity / workload identity / az login.
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )
    return AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        azure_ad_token_provider=token_provider,
        api_version=settings.azure_openai_api_version,
    )


class AzureOpenAIProvider(LLMProvider):
    name = "azure_openai"

    def __init__(self, settings: Settings, client=None):
        self.deployment = settings.azure_openai_deployment
        self.max_tokens = settings.max_tokens
        self.temperature = settings.temperature
        self.client = client or _build_client(settings)

    @staticmethod
    def _to_openai(system: str, messages: list[Message]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.text})
            elif m.role == "assistant":
                msg: dict = {"role": "assistant", "content": m.text or None}
                if m.tool_calls:
                    msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in m.tool_calls
                    ]
                out.append(msg)
            elif m.role == "tool":
                for r in m.tool_results:
                    out.append({"role": "tool", "tool_call_id": r.call_id, "content": r.content})
        return out

    def complete(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> ModelResponse:
        kwargs: dict = {
            "model": self.deployment,
            "messages": self._to_openai(system, messages),
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        usage = resp.usage
        return ModelResponse(
            text=msg.content or "",
            tool_calls=calls,
            input_tokens=getattr(usage, "prompt_tokens", 0),
            output_tokens=getattr(usage, "completion_tokens", 0),
        )

"""Amazon Bedrock provider using the Converse API (works with Amazon Nova)."""

from __future__ import annotations

import boto3
from botocore.config import Config

from sre_agent.config import Settings
from sre_agent.providers.base import (
    LLMProvider,
    Message,
    ModelResponse,
    ToolCall,
    ToolSpec,
)


class BedrockProvider(LLMProvider):
    name = "bedrock"

    def __init__(self, settings: Settings, client=None):
        self.model_id = settings.bedrock_model_id
        self.max_tokens = settings.max_tokens
        self.temperature = settings.temperature
        # Credentials come from the default chain: IRSA / Pod Identity / ECS task role / env.
        self.client = client or boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            config=Config(retries={"max_attempts": 5, "mode": "adaptive"}, read_timeout=60),
        )

    @staticmethod
    def _to_converse(messages: list[Message]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": [{"text": m.text}]})
            elif m.role == "assistant":
                content: list[dict] = []
                if m.text:
                    content.append({"text": m.text})
                for tc in m.tool_calls:
                    content.append(
                        {"toolUse": {"toolUseId": tc.id, "name": tc.name, "input": tc.arguments}}
                    )
                out.append({"role": "assistant", "content": content})
            elif m.role == "tool":
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "toolResult": {
                                    "toolUseId": r.call_id,
                                    "content": [{"text": r.content}],
                                    "status": "error" if r.is_error else "success",
                                }
                            }
                            for r in m.tool_results
                        ],
                    }
                )
        return out

    def complete(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> ModelResponse:
        kwargs: dict = {
            "modelId": self.model_id,
            "system": [{"text": system}],
            "messages": self._to_converse(messages),
            "inferenceConfig": {"maxTokens": self.max_tokens, "temperature": self.temperature},
        }
        if tools:
            kwargs["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": {"json": t.parameters},
                        }
                    }
                    for t in tools
                ]
            }
        resp = self.client.converse(**kwargs)
        blocks = resp["output"]["message"]["content"]
        text = "".join(b["text"] for b in blocks if "text" in b)
        calls = [
            ToolCall(
                id=b["toolUse"]["toolUseId"],
                name=b["toolUse"]["name"],
                arguments=b["toolUse"].get("input") or {},
            )
            for b in blocks
            if "toolUse" in b
        ]
        usage = resp.get("usage", {})
        return ModelResponse(
            text=text,
            tool_calls=calls,
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
        )

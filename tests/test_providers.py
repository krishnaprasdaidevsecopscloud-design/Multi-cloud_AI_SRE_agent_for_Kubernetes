from types import SimpleNamespace

from sre_agent.config import Settings
from sre_agent.providers.azure_openai import AzureOpenAIProvider
from sre_agent.providers.base import Message, ToolCall, ToolResult, ToolSpec
from sre_agent.providers.bedrock import BedrockProvider

SPEC = ToolSpec("list_pods", "d", {"type": "object", "properties": {}})


class FakeBedrock:
    def converse(self, **kw):
        self.kw = kw
        return {
            "output": {"message": {"content": [
                {"text": "checking"},
                {"toolUse": {"toolUseId": "t1", "name": "list_pods", "input": {"namespace": "x"}}},
            ]}},
            "usage": {"inputTokens": 10, "outputTokens": 5},
        }


def test_bedrock_roundtrip():
    fb = FakeBedrock()
    p = BedrockProvider(Settings(), client=fb)
    msgs = [
        Message("user", "hi"),
        Message("assistant", tool_calls=[ToolCall("t0", "list_pods", {})]),
        Message("tool", tool_results=[ToolResult("t0", "list_pods", "ok")]),
    ]
    r = p.complete("sys", msgs, [SPEC])
    assert r.tool_calls[0].arguments == {"namespace": "x"} and r.input_tokens == 10
    assert fb.kw["toolConfig"]["tools"][0]["toolSpec"]["name"] == "list_pods"
    assert fb.kw["messages"][2]["content"][0]["toolResult"]["toolUseId"] == "t0"


class FakeOpenAI:
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.kw = kw
        tc = SimpleNamespace(id="c1", function=SimpleNamespace(name="list_pods", arguments='{"namespace":"y"}'))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tc]))],
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
        )


def test_azure_roundtrip():
    fo = FakeOpenAI()
    p = AzureOpenAIProvider(Settings(), client=fo)
    msgs = [
        Message("user", "hi"),
        Message("assistant", tool_calls=[ToolCall("c0", "list_pods", {"a": 1})]),
        Message("tool", tool_results=[ToolResult("c0", "list_pods", "ok")]),
    ]
    r = p.complete("sys", msgs, [SPEC])
    assert r.tool_calls[0].arguments == {"namespace": "y"}
    assert fo.kw["messages"][-1] == {"role": "tool", "tool_call_id": "c0", "content": "ok"}
    assert fo.kw["tools"][0]["function"]["name"] == "list_pods"

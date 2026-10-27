"""The investigation loop: model <-> tools until the model answers or the step budget ends."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from sre_agent.config import Settings
from sre_agent.providers.base import LLMProvider, Message, ToolResult
from sre_agent.tools.registry import ToolRegistry

log = structlog.get_logger()

SYSTEM_PROMPT = """You are a senior Site Reliability Engineer investigating a Kubernetes cluster.
You are READ-ONLY: you can inspect but never change anything. Never claim to have fixed or
restarted something; instead recommend the exact kubectl/IaC change a human should make.

Method:
1. Start broad (list_pods with only_unhealthy, list_nodes) then narrow to the failing object.
2. For a crashing pod read describe_pod, then get_pod_logs (previous=true) and get_events.
3. Base every conclusion on tool output. If the evidence is insufficient, say what is missing.
4. Do not repeat an identical tool call.

Final answer format:
**Root cause:** one or two sentences naming the specific resource and reason.
**Evidence:** bullet list citing tool output (pod names, exit codes, event messages).
**Recommended fix:** concrete steps for a human operator.
"""


@dataclass
class ToolTrace:
    name: str
    arguments: dict
    is_error: bool


@dataclass
class InvestigationResult:
    answer: str
    steps: int
    tool_trace: list[ToolTrace] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    truncated: bool = False


class SREAgent:
    def __init__(self, provider: LLMProvider, tools: ToolRegistry, settings: Settings):
        self.provider = provider
        self.tools = tools
        self.settings = settings
        self.specs = tools.specs()

    def investigate(self, question: str) -> InvestigationResult:
        messages = [Message(role="user", text=question)]
        result = InvestigationResult(answer="", steps=0)
        seen: set[tuple[str, str]] = set()

        for step in range(1, self.settings.max_steps + 1):
            result.steps = step
            resp = self.provider.complete(SYSTEM_PROMPT, messages, self.specs)
            result.input_tokens += resp.input_tokens
            result.output_tokens += resp.output_tokens

            if not resp.tool_calls:
                result.answer = resp.text.strip()
                return result

            messages.append(Message(role="assistant", text=resp.text, tool_calls=resp.tool_calls))
            results = []
            for call in resp.tool_calls:
                key = (call.name, repr(sorted(call.arguments.items())))
                if key in seen:
                    content, is_err = (
                        "Duplicate call: you already have this result. Use a different tool or answer.",
                        True,
                    )
                else:
                    seen.add(key)
                    content, is_err = self.tools.execute(call.name, call.arguments)
                log.info("tool_call", tool=call.name, args=call.arguments, error=is_err)
                result.tool_trace.append(ToolTrace(call.name, call.arguments, is_err))
                results.append(ToolResult(call.id, call.name, content, is_err))
            messages.append(Message(role="tool", tool_results=results))

        # Budget exhausted: force a final answer without tools.
        messages.append(
            Message(role="user", text="Step budget reached. Give your best final answer now.")
        )
        resp = self.provider.complete(SYSTEM_PROMPT, messages, [])
        result.answer = resp.text.strip()
        result.truncated = True
        return result

import pathlib

import yaml

from sre_agent.agent import SREAgent
from sre_agent.config import Settings
from sre_agent.evaluation.fake_backend import FakeBackend
from sre_agent.evaluation.scoring import score_case
from sre_agent.providers.base import LLMProvider, ModelResponse, ToolCall
from sre_agent.tools.registry import ToolRegistry, redact

CASES = yaml.safe_load(
    (pathlib.Path(__file__).parent.parent / "eval" / "cases.yaml").read_text(encoding="utf-8")
)["cases"]


def registry(case_id="oomkilled-checkout", **kw):
    case = next(c for c in CASES if c["id"] == case_id)
    return ToolRegistry(FakeBackend(case["cluster"]), Settings(**kw))


def test_redacts_secrets():
    assert "hunter2" not in redact("password=hunter2")
    assert "AKIAABCDEFGHIJKLMNOP" not in redact("key AKIAABCDEFGHIJKLMNOP")


def test_unhealthy_filter_hides_healthy_pods():
    out, err = registry().execute("list_pods", {"namespace": "shop"})
    assert not err and "checkout" in out and "cart-5c8d" not in out


def test_unknown_tool_and_bad_args_return_errors_not_exceptions():
    r = registry()
    assert r.execute("delete_pod", {})[1] is True
    assert r.execute("describe_pod", {"bogus": 1})[1] is True


def test_not_found_is_actionable():
    out, err = registry().execute("describe_pod", {"name": "nope", "namespace": "shop"})
    assert err and "namespace" in out.lower()


def test_namespace_allowlist_enforced():
    r = registry(allowed_namespaces="shop")
    assert r.execute("list_pods", {"namespace": "prod"})[1] is True
    assert r.execute("list_pods", {"namespace": "all"})[1] is True
    assert r.execute("list_pods", {"namespace": "shop"})[1] is False


def test_output_truncated():
    r = registry(tool_output_max_chars=50)
    out, _ = r.execute("list_pods", {"namespace": "shop", "only_unhealthy": False})
    assert "truncated" in out


def test_no_write_tools_exposed():
    names = {s.name for s in ToolRegistry.specs()}
    assert not any(v in n for n in names for v in ("delete", "create", "patch", "exec", "scale"))


class ScriptedProvider(LLMProvider):
    name = "scripted"

    def __init__(self, script):
        self.script = list(script)

    def complete(self, system, messages, tools):
        return self.script.pop(0)


def test_agent_loop_and_scoring():
    case = CASES[0]
    s = Settings()
    provider = ScriptedProvider(
        [
            ModelResponse("", [ToolCall("1", "list_pods", {"namespace": "shop"})]),
            ModelResponse(
                "**Root cause:** checkout-7d9f-abcde is OOMKilled (exit 137), memory limit too low.",
                [],
            ),
        ]
    )
    agent = SREAgent(provider, ToolRegistry(FakeBackend(case["cluster"]), s), s)
    result = agent.investigate(case["question"])
    assert result.steps == 2
    assert score_case(case, result).score == 5.0


def test_duplicate_calls_are_blocked():
    case = CASES[0]
    s = Settings(max_steps=3)
    same = ToolCall("1", "list_pods", {"namespace": "shop"})
    provider = ScriptedProvider(
        [ModelResponse("", [same]), ModelResponse("", [same]), ModelResponse("", [same]),
         ModelResponse("final", [])]
    )
    agent = SREAgent(provider, ToolRegistry(FakeBackend(case["cluster"]), s), s)
    result = agent.investigate("q")
    assert result.truncated and result.tool_trace[1].is_error

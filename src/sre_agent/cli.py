import argparse

from sre_agent.agent import SREAgent
from sre_agent.config import get_settings
from sre_agent.providers import build_provider
from sre_agent.tools.backend import KubeBackend
from sre_agent.tools.registry import ToolRegistry


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask the read-only SRE agent about your cluster")
    ap.add_argument("question")
    ap.add_argument("--provider", choices=["bedrock", "azure_openai"])
    args = ap.parse_args()

    s = get_settings()
    if args.provider:
        s.provider = args.provider
    agent = SREAgent(build_provider(s), ToolRegistry(KubeBackend(s), s), s)
    r = agent.investigate(args.question)
    print(r.answer)
    print(f"\n[{r.steps} steps, tools: {[t.name for t in r.tool_trace]}]")


if __name__ == "__main__":
    main()

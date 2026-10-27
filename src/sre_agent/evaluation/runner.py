"""Evaluation pipeline: run the real agent+model against fixed scenarios and score 0-5.

  sre-eval --provider bedrock --cases eval/cases.yaml --out eval/results/bedrock.json
  sre-eval --provider azure_openai --min-score 4.5     # exits 1 below threshold (CI gate)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys

import yaml

from sre_agent.agent import SREAgent
from sre_agent.config import get_settings
from sre_agent.evaluation.fake_backend import FakeBackend
from sre_agent.evaluation.scoring import score_case
from sre_agent.providers import build_provider
from sre_agent.tools.registry import ToolRegistry


def run(cases: list[dict], settings) -> dict:
    provider = build_provider(settings)
    rows = []
    for case in cases:
        agent = SREAgent(provider, ToolRegistry(FakeBackend(case["cluster"]), settings), settings)
        result = agent.investigate(case["question"])
        sc = score_case(case, result)
        rows.append(
            {
                "id": case["id"],
                "score": sc.score,
                "breakdown": sc.breakdown,
                "steps": result.steps,
                "tools": [t.name for t in result.tool_trace],
                "answer": result.answer,
            }
        )
        print(f"{case['id']:<28} {sc.score:.1f}/5  {sc.breakdown}")
    mean = statistics.mean(r["score"] for r in rows)
    return {"provider": settings.provider, "mean_score": round(mean, 2), "cases": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["bedrock", "azure_openai"])
    ap.add_argument("--cases", default="eval/cases.yaml")
    ap.add_argument("--out", default="")
    ap.add_argument("--min-score", type=float, default=0.0)
    args = ap.parse_args()

    settings = get_settings()
    if args.provider:
        settings.provider = args.provider
    cases = yaml.safe_load(pathlib.Path(args.cases).read_text(encoding="utf-8"))["cases"]
    report = run(cases, settings)
    print(f"\nMEAN SCORE ({report['provider']}): {report['mean_score']}/5")
    if args.out:
        p = pathlib.Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if report["mean_score"] < args.min_score:
        print(f"FAIL: below threshold {args.min_score}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

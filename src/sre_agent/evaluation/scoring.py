"""Deterministic 0-5 rubric. One point per criterion so scores are explainable and diff-able.

  1. root_cause_resource : answer names the culprit resource (pod/node/deployment)
  2. root_cause_reason   : answer states the correct reason (any accepted keyword group)
  3. evidence            : answer cites concrete evidence from tool output
  4. required_tools      : every required tool was called
  5. clean_execution     : no tool errors, no duplicate calls, finished inside the step budget
"""

from __future__ import annotations

from dataclasses import dataclass

from sre_agent.agent import InvestigationResult


@dataclass
class CaseScore:
    case_id: str
    score: float
    breakdown: dict[str, bool]


def _has_any(text: str, words: list[str]) -> bool:
    t = text.lower()
    return any(w.lower() in t for w in words)


def score_case(case: dict, result: InvestigationResult) -> CaseScore:
    ans = result.answer
    exp = case["expect"]
    used = {t.name for t in result.tool_trace}
    b = {
        "root_cause_resource": _has_any(ans, exp["resource"]),
        "root_cause_reason": _has_any(ans, exp["reason_any"]),
        "evidence": _has_any(ans, exp["evidence_any"]),
        "required_tools": set(exp["required_tools"]) <= used,
        "clean_execution": not result.truncated and not any(t.is_error for t in result.tool_trace),
    }
    return CaseScore(case["id"], float(sum(b.values())), b)

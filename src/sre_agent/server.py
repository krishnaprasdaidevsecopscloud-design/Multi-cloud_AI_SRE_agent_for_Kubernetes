"""HTTP API. One image serves every target (ECS, EKS, AKS, Container Apps, AgentCore)."""

from __future__ import annotations

import logging

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from sre_agent import __version__
from sre_agent.agent import SREAgent
from sre_agent.config import get_settings
from sre_agent.providers import build_provider
from sre_agent.tools.backend import KubeBackend
from sre_agent.tools.registry import ToolRegistry

settings = get_settings()
logging.basicConfig(level=settings.log_level)
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)

app = FastAPI(title="Multi-cloud AI SRE Agent", version=__version__)
_agent: SREAgent | None = None


def get_agent() -> SREAgent:
    global _agent
    if _agent is None:  # lazy so /healthz works even if the cluster/model is misconfigured
        _agent = SREAgent(
            build_provider(settings),
            ToolRegistry(KubeBackend(settings), settings),
            settings,
        )
    return _agent


class InvestigateRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class InvestigateResponse(BaseModel):
    answer: str
    steps: int
    tools_used: list[str]
    truncated: bool
    input_tokens: int
    output_tokens: int


@app.get("/healthz")
def healthz():
    return {"status": "ok", "version": __version__, "provider": settings.provider}


@app.post("/investigate", response_model=InvestigateResponse)
def investigate(req: InvestigateRequest):
    try:
        r = get_agent().investigate(req.question)
    except Exception as e:
        structlog.get_logger().error("investigate_failed", error=str(e))
        raise HTTPException(status_code=502, detail="Investigation failed; see server logs.") from e
    return InvestigateResponse(
        answer=r.answer,
        steps=r.steps,
        tools_used=[t.name for t in r.tool_trace],
        truncated=r.truncated,
        input_tokens=r.input_tokens,
        output_tokens=r.output_tokens,
    )


# AgentCore Runtime contract: POST /invocations and GET /ping on port 8080.
@app.get("/ping")
def ping():
    return {"status": "Healthy"}


@app.post("/invocations")
def invocations(payload: dict):
    question = payload.get("prompt") or payload.get("question") or ""
    return investigate(InvestigateRequest(question=question))

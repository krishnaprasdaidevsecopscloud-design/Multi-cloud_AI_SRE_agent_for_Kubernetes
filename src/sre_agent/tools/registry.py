"""Tool registry: schemas the model sees + the guarded executor.

Lessons baked in (these are the "tool fixes" that move eval scores):
  * descriptions say WHEN to use a tool and what it returns, not just what it is
  * every argument has a sane default (namespace="default", tail_lines) so the model can't stall
  * outputs are compact JSON, truncated with an explicit marker, never raw API dumps
  * errors are returned as actionable text (is_error) instead of raising -> model can self-correct
  * secrets are redacted from logs before they reach the model
  * unhealthy-only filter on list_pods keeps context small in big clusters
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from sre_agent.config import Settings
from sre_agent.providers.base import ToolSpec
from sre_agent.tools.backend import BackendError, ClusterBackend

_SECRET_PATTERNS = [
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|authorization)\s*[=:]\s*\S+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)bearer\s+[a-z0-9._\-]{20,}"),
    re.compile(r"eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}"),
]


def redact(text: str) -> str:
    for p in _SECRET_PATTERNS:
        text = p.sub("[REDACTED]", text)
    return text


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def _is_unhealthy(pod: dict) -> bool:
    if pod["phase"] not in ("Running", "Succeeded"):
        return True
    for c in pod["containers"]:
        if pod["phase"] == "Succeeded":
            continue
        if not c["ready"] or c["state"] == "waiting":
            return True
        if c["restarts"] > 0 and c["last_termination"]:
            return True
    return False


class ToolRegistry:
    def __init__(self, backend: ClusterBackend, settings: Settings):
        self.backend = backend
        self.s = settings
        self._impl: dict[str, Callable[..., Any]] = {
            "list_namespaces": self.list_namespaces,
            "list_pods": self.list_pods,
            "describe_pod": self.describe_pod,
            "get_pod_logs": self.get_pod_logs,
            "get_events": self.get_events,
            "list_deployments": self.list_deployments,
            "list_nodes": self.list_nodes,
        }

    # ---- schemas -------------------------------------------------------------------------
    @staticmethod
    def specs() -> list[ToolSpec]:
        ns = {
            "type": "string",
            "description": "Kubernetes namespace. Use 'all' to search every namespace. Default: 'default'.",
        }
        return [
            ToolSpec(
                "list_namespaces",
                "List namespaces in the cluster. Use first when the user does not say which namespace.",
                {"type": "object", "properties": {}},
            ),
            ToolSpec(
                "list_pods",
                "List pods with phase, per-container ready/restart/state/last termination reason "
                "(e.g. OOMKilled, CrashLoopBackOff). Start here for 'what is broken' questions. "
                "Set only_unhealthy=true to hide healthy pods.",
                {
                    "type": "object",
                    "properties": {
                        "namespace": ns,
                        "label_selector": {"type": "string", "description": "e.g. app=checkout"},
                        "only_unhealthy": {"type": "boolean", "description": "Default true."},
                    },
                },
            ),
            ToolSpec(
                "describe_pod",
                "Detailed view of ONE pod: container states, resource requests/limits, owner "
                "controller, unhealthy conditions. Use after list_pods identifies a suspect pod.",
                {
                    "type": "object",
                    "properties": {"namespace": ns, "name": {"type": "string"}},
                    "required": ["name"],
                },
            ),
            ToolSpec(
                "get_pod_logs",
                "Recent log lines of a pod container (secrets redacted). For a crashing pod set "
                "previous=true to read the logs of the last crashed instance.",
                {
                    "type": "object",
                    "properties": {
                        "namespace": ns,
                        "name": {"type": "string"},
                        "container": {"type": "string", "description": "Optional; default first."},
                        "previous": {"type": "boolean", "description": "Default false."},
                        "tail_lines": {"type": "integer", "description": "Default 100, max 500."},
                    },
                    "required": ["name"],
                },
            ),
            ToolSpec(
                "get_events",
                "Recent Kubernetes events, newest first. Reveals scheduling failures "
                "(FailedScheduling), image pull errors, probe failures, evictions, OOM kills.",
                {
                    "type": "object",
                    "properties": {
                        "namespace": ns,
                        "object_name": {"type": "string", "description": "Filter to one object."},
                        "warnings_only": {"type": "boolean", "description": "Default true."},
                    },
                },
            ),
            ToolSpec(
                "list_deployments",
                "Deployments with desired/ready/available replicas and image. Use to spot "
                "under-replicated or recently changed workloads.",
                {"type": "object", "properties": {"namespace": ns}},
            ),
            ToolSpec(
                "list_nodes",
                "Nodes with readiness and problem conditions (MemoryPressure, DiskPressure, "
                "NotReady). Use when pods are Pending/Evicted or many pods fail at once.",
                {"type": "object", "properties": {}},
            ),
        ]

    # ---- execution -----------------------------------------------------------------------
    def execute(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Returns (content, is_error). Never raises."""
        fn = self._impl.get(name)
        if fn is None:
            return f"Unknown tool '{name}'. Available: {', '.join(sorted(self._impl))}", True
        try:
            result = fn(**self._clean(arguments))
        except BackendError as e:
            return str(e), True
        except TypeError as e:
            return f"Invalid arguments for {name}: {e}", True
        except Exception as e:  # noqa: BLE001 - tool failures must never crash the agent loop
            return f"Tool {name} failed: {type(e).__name__}: {e}", True
        text = result if isinstance(result, str) else json.dumps(result, default=str)
        return truncate(text, self.s.tool_output_max_chars), False

    @staticmethod
    def _clean(args: dict[str, Any]) -> dict[str, Any]:
        # Models sometimes send null / empty strings for optional args.
        return {k: v for k, v in (args or {}).items() if v not in (None, "")}

    def _check_ns(self, namespace: str) -> str:
        allow = self.s.namespace_allowlist
        if allow and namespace != "all" and namespace not in allow:
            raise BackendError(f"Namespace '{namespace}' is not permitted. Allowed: {sorted(allow)}")
        if allow and namespace == "all":
            raise BackendError(f"Cluster-wide queries are disabled. Use one of: {sorted(allow)}")
        return namespace

    # ---- tools ---------------------------------------------------------------------------
    def list_namespaces(self):
        names = self.backend.list_namespaces()
        allow = self.s.namespace_allowlist
        return [n for n in names if not allow or n["name"] in allow]

    def list_pods(self, namespace="default", label_selector="", only_unhealthy=True):
        pods = self.backend.list_pods(self._check_ns(namespace), label_selector)
        total = len(pods)
        if only_unhealthy:
            pods = [p for p in pods if _is_unhealthy(p)]
        return {"total_pods": total, "returned": len(pods), "pods": pods[:50]}

    def describe_pod(self, name, namespace="default"):
        return self.backend.get_pod(self._check_ns(namespace), name)

    def get_pod_logs(self, name, namespace="default", container="", previous=False, tail_lines=None):
        n = min(int(tail_lines or self.s.log_tail_lines), 500)
        logs = self.backend.get_pod_logs(self._check_ns(namespace), name, container, previous, n)
        return redact(logs) or "(no log output)"

    def get_events(self, namespace="default", object_name="", warnings_only=True):
        ev = self.backend.list_events(self._check_ns(namespace), object_name)
        if warnings_only:
            ev = [e for e in ev if e["type"] == "Warning"]
        return {"returned": min(len(ev), 25), "events": ev[:25]}

    def list_deployments(self, namespace="default"):
        return self.backend.list_deployments(self._check_ns(namespace))

    def list_nodes(self):
        return self.backend.list_nodes()

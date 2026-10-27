"""Deterministic in-memory cluster built from a scenario dict, for repeatable evaluation."""

from __future__ import annotations

from sre_agent.tools.backend import BackendError


class FakeBackend:
    def __init__(self, cluster: dict):
        self.c = cluster

    def list_namespaces(self):
        return [{"name": n, "phase": "Active"} for n in self.c.get("namespaces", ["default"])]

    def list_pods(self, namespace, label_selector=""):
        pods = self.c.get("pods", [])
        return [p for p in pods if namespace == "all" or p["namespace"] == namespace]

    def get_pod(self, namespace, name):
        for p in self.c.get("pods", []):
            if p["name"] == name and p["namespace"] == namespace:
                return p
        raise BackendError("Not found. Check the namespace and name spelling.")

    def get_pod_logs(self, namespace, name, container, previous, tail_lines):
        key = f"{namespace}/{name}" + ("#previous" if previous else "")
        logs = self.c.get("logs", {})
        if key in logs:
            return logs[key]
        if f"{namespace}/{name}" in logs:
            return logs[f"{namespace}/{name}"]
        raise BackendError("Not found. Check the namespace and name spelling.")

    def list_events(self, namespace, involved_object=""):
        ev = [e for e in self.c.get("events", []) if namespace in ("all", e["namespace"])]
        if involved_object:
            ev = [e for e in ev if e["object"].endswith("/" + involved_object)]
        return ev

    def list_deployments(self, namespace):
        return [
            d for d in self.c.get("deployments", []) if namespace in ("all", d["namespace"])
        ]

    def list_nodes(self):
        return self.c.get("nodes", [])

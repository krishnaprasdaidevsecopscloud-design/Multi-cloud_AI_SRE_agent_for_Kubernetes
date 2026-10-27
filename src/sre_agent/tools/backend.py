"""Cluster backends. Every method is a READ. There is deliberately no write method anywhere:
read-only is enforced by (1) this interface, (2) Kubernetes RBAC that grants only get/list/watch,
and (3) the tool registry exposing nothing else.
"""

from __future__ import annotations

from typing import Protocol


class ClusterBackend(Protocol):
    def list_namespaces(self) -> list[dict]: ...
    def list_pods(self, namespace: str, label_selector: str = "") -> list[dict]: ...
    def get_pod(self, namespace: str, name: str) -> dict: ...
    def get_pod_logs(
        self, namespace: str, name: str, container: str, previous: bool, tail_lines: int
    ) -> str: ...
    def list_events(self, namespace: str, involved_object: str = "") -> list[dict]: ...
    def list_deployments(self, namespace: str) -> list[dict]: ...
    def list_nodes(self) -> list[dict]: ...


class BackendError(Exception):
    """Raised for expected failures (not found, forbidden). Message is shown to the model."""


class KubeBackend:
    """Real cluster access via the official Kubernetes Python client."""

    def __init__(self, settings):
        from kubernetes import client, config

        if settings.cluster_type in ("eks", "aks"):
            from sre_agent.tools.cluster_auth import configure_remote

            configure_remote(settings)
        elif settings.cluster_type == "kubeconfig":
            config.load_kube_config(config_file=settings.kubeconfig or None)
        else:
            config.load_incluster_config()
        self.core = client.CoreV1Api()
        self.apps = client.AppsV1Api()
        self._ApiException = client.exceptions.ApiException

    def _wrap(self, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except self._ApiException as e:
            if e.status == 404:
                raise BackendError("Not found. Check the namespace and name spelling.") from e
            if e.status == 403:
                raise BackendError(
                    "Forbidden: the agent's service account lacks permission for this read."
                ) from e
            raise BackendError(f"Kubernetes API error {e.status}: {e.reason}") from e

    def list_namespaces(self) -> list[dict]:
        r = self._wrap(self.core.list_namespace)
        return [{"name": n.metadata.name, "phase": n.status.phase} for n in r.items]

    def list_pods(self, namespace: str, label_selector: str = "") -> list[dict]:
        if namespace == "all":
            r = self._wrap(self.core.list_pod_for_all_namespaces, label_selector=label_selector)
        else:
            r = self._wrap(self.core.list_namespaced_pod, namespace, label_selector=label_selector)
        return [self._pod_summary(p) for p in r.items]

    @staticmethod
    def _pod_summary(p) -> dict:
        containers = []
        for cs in p.status.container_statuses or []:
            state = "running"
            reason = ""
            if cs.state.waiting:
                state, reason = "waiting", cs.state.waiting.reason or ""
            elif cs.state.terminated:
                state, reason = "terminated", cs.state.terminated.reason or ""
            last = ""
            if cs.last_state and cs.last_state.terminated:
                lt = cs.last_state.terminated
                last = f"{lt.reason} (exit {lt.exit_code})"
            containers.append(
                {
                    "name": cs.name,
                    "ready": cs.ready,
                    "restarts": cs.restart_count,
                    "state": state,
                    "reason": reason,
                    "last_termination": last,
                    "image": cs.image,
                }
            )
        return {
            "namespace": p.metadata.namespace,
            "name": p.metadata.name,
            "phase": p.status.phase,
            "node": p.spec.node_name,
            "containers": containers,
            "conditions": [
                {"type": c.type, "status": c.status, "reason": c.reason or "", "message": c.message or ""}
                for c in (p.status.conditions or [])
                if c.status != "True"
            ],
        }

    def get_pod(self, namespace: str, name: str) -> dict:
        p = self._wrap(self.core.read_namespaced_pod, name, namespace)
        d = self._pod_summary(p)
        d["spec_containers"] = [
            {
                "name": c.name,
                "image": c.image,
                "resources": c.resources.to_dict() if c.resources else {},
            }
            for c in p.spec.containers
        ]
        d["owner"] = [f"{o.kind}/{o.name}" for o in (p.metadata.owner_references or [])]
        return d

    def get_pod_logs(
        self, namespace: str, name: str, container: str, previous: bool, tail_lines: int
    ) -> str:
        kw = {"tail_lines": tail_lines, "previous": previous}
        if container:
            kw["container"] = container
        return self._wrap(self.core.read_namespaced_pod_log, name, namespace, **kw)

    def list_events(self, namespace: str, involved_object: str = "") -> list[dict]:
        sel = f"involvedObject.name={involved_object}" if involved_object else ""
        if namespace == "all":
            r = self._wrap(self.core.list_event_for_all_namespaces, field_selector=sel)
        else:
            r = self._wrap(self.core.list_namespaced_event, namespace, field_selector=sel)
        items = sorted(r.items, key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp, reverse=True)
        return [
            {
                "type": e.type,
                "reason": e.reason,
                "object": f"{e.involved_object.kind}/{e.involved_object.name}",
                "namespace": e.metadata.namespace,
                "message": e.message,
                "count": e.count,
            }
            for e in items
        ]

    def list_deployments(self, namespace: str) -> list[dict]:
        if namespace == "all":
            r = self._wrap(self.apps.list_deployment_for_all_namespaces)
        else:
            r = self._wrap(self.apps.list_namespaced_deployment, namespace)
        return [
            {
                "namespace": d.metadata.namespace,
                "name": d.metadata.name,
                "desired": d.spec.replicas,
                "ready": d.status.ready_replicas or 0,
                "available": d.status.available_replicas or 0,
                "image": d.spec.template.spec.containers[0].image,
            }
            for d in r.items
        ]

    def list_nodes(self) -> list[dict]:
        r = self._wrap(self.core.list_node)
        out = []
        for n in r.items:
            bad = [
                {"type": c.type, "status": c.status, "reason": c.reason or ""}
                for c in n.status.conditions
                if (c.type == "Ready" and c.status != "True")
                or (c.type != "Ready" and c.status == "True")
            ]
            out.append(
                {
                    "name": n.metadata.name,
                    "ready": not any(b["type"] == "Ready" for b in bad),
                    "problem_conditions": bad,
                    "allocatable": dict(n.status.allocatable or {}),
                }
            )
        return out

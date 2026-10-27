"""Authenticate to a REMOTE cluster (agent running on ECS / AgentCore / Container Apps).

Agents running inside the cluster (EKS/AKS targets) use the in-cluster service account instead.

  eks: SigV4-presigned STS GetCallerIdentity token (same as `aws eks get-token`), refreshed
       automatically because EKS tokens live ~15 minutes.
  aks: Entra ID access token for the AKS AAD server app, from the managed identity.
"""

from __future__ import annotations

import base64
import tempfile

from sre_agent.config import Settings

AKS_AAD_SERVER_APP = "6dae42f8-4368-4678-94ff-3960e28e3630"


def eks_token(cluster_name: str, region: str) -> str:
    import boto3
    from botocore.signers import RequestSigner

    session = boto3.session.Session()
    sts = session.client("sts", region_name=region, endpoint_url=f"https://sts.{region}.amazonaws.com")
    signer = RequestSigner(
        sts.meta.service_model.service_id, region, "sts", "v4", session.get_credentials(), session.events
    )
    url = signer.generate_presigned_url(
        {
            "method": "GET",
            "url": f"https://sts.{region}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15",
            "body": {},
            "headers": {"x-k8s-aws-id": cluster_name},
            "context": {},
        },
        region_name=region,
        expires_in=60,
        operation_name="",
    )
    return "k8s-aws-v1." + base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def aks_token() -> str:
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential().get_token(f"{AKS_AAD_SERVER_APP}/.default").token


def configure_remote(settings: Settings) -> None:
    """Populate the global kubernetes client Configuration for a remote EKS/AKS cluster."""
    from kubernetes import client

    cfg = client.Configuration()
    cfg.host = settings.cluster_endpoint
    ca = base64.b64decode(settings.cluster_ca_data)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".crt") as f:
        f.write(ca)
    cfg.ssl_ca_cert = f.name

    def refresh(c: client.Configuration) -> None:
        tok = (
            eks_token(settings.cluster_name, settings.aws_region)
            if settings.cluster_type == "eks"
            else aks_token()
        )
        c.api_key = {"authorization": "Bearer " + tok}

    cfg.refresh_api_key_hook = refresh
    refresh(cfg)
    client.Configuration.set_default(cfg)

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (12-factor)."""

    model_config = SettingsConfigDict(env_prefix="SRE_", env_file=".env", extra="ignore")

    provider: Literal["bedrock", "azure_openai"] = "bedrock"

    # AWS Bedrock (Amazon Nova)
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "us.amazon.nova-pro-v1:0"

    # Azure OpenAI
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = "gpt-4o"  # the *deployment name*, not the model name
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_api_key: str = ""  # empty => Entra ID / managed identity auth

    # Agent behaviour
    max_steps: int = 8
    max_tokens: int = 1500
    temperature: float = 0.0
    tool_output_max_chars: int = 6000
    log_tail_lines: int = 100

    # Kubernetes
    # "incluster" (agent runs on EKS/AKS), "eks"/"aks" (agent runs elsewhere, targets a remote
    # cluster), or "kubeconfig" (local dev).
    cluster_type: Literal["incluster", "eks", "aks", "kubeconfig"] = "incluster"
    cluster_name: str = ""  # eks only
    cluster_endpoint: str = ""  # eks/aks API server URL
    cluster_ca_data: str = ""  # eks/aks base64 CA bundle
    kubeconfig: str = ""  # used when cluster_type=kubeconfig
    allowed_namespaces: str = ""  # comma-separated; empty => all namespaces

    log_level: str = "INFO"

    @property
    def namespace_allowlist(self) -> set[str]:
        return {n.strip() for n in self.allowed_namespaces.split(",") if n.strip()}


def get_settings() -> Settings:
    return Settings()

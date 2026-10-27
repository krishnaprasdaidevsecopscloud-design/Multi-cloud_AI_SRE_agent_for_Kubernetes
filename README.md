# Multi-cloud AI SRE Agent for Kubernetes

A **read-only investigation agent**: ask it *"why is checkout restarting?"* and it inspects your cluster with tools (pods, logs, events, nodes, deployments), reasons over the evidence, and returns a root cause plus a recommended fix for a human to apply. It never changes anything.

- **Two model backends, one agent:** Amazon Bedrock (**Amazon Nova**) and **Azure OpenAI**, behind a provider-neutral interface.
- **Five deployment targets via Terraform:** Bedrock **AgentCore** Runtime, **ECS Fargate**, **EKS**, **Azure Container Apps**, **AKS**.
- **Evaluation pipeline:** frozen incident scenarios scored 0–5 with an explainable rubric; usable as a release gate.

Docs: [pre-req-doc.md](pre-req-doc.md) (accounts, roles, APIs, permissions) · [tech-doc.md](tech-doc.md) (step-by-step deploy to EKS/AKS) · [docs/evaluation.md](docs/evaluation.md)

---

## Concepts in plain English

### What is an "agent" with "tool calling"?
A plain LLM only produces text; it cannot look at your cluster. **Tool calling** lets you hand the model a menu of functions (name, description, JSON-schema arguments). Instead of answering, the model can reply *"call `get_pod_logs(name=checkout-1, previous=true)`"*. **Your code** runs the function and feeds the result back. Repeat until the model has enough evidence to answer. That loop (`src/sre_agent/agent.py`) is the whole "agent".

```
question ─> LLM ─> "call list_pods" ─> your code runs it ─> result ─> LLM ─> "call get_events" ─> … ─> final answer
```

### What is Amazon Bedrock (and Nova)?
**Amazon Bedrock** is AWS's managed service for foundation models: you call an API, AWS runs the model, and access is controlled with normal **IAM** (no API keys). **Amazon Nova** is Amazon's own model family (Micro, Lite, Pro, Premier) — fast and inexpensive, with tool-use support. We use Bedrock's unified **Converse API**, which has the same request shape for tools across models. Nova Pro is the default here.
- **Why here:** your agent runs on AWS, so credentials come from the task role / pod identity, data stays in your AWS account, and billing is on your AWS bill.
- **Bedrock AgentCore** is a *separate* AWS service for hosting agents (managed runtime, sessions, identity, observability). We deploy our container there as one of the targets; the model is still Nova via Bedrock.

### What is Azure OpenAI?
**Azure OpenAI Service** runs OpenAI models (GPT‑4o, etc.) inside your Azure subscription, with Azure networking, **Entra ID** auth (managed identity, no keys), regional data residency and quotas. You create an *account*, then a named **deployment** of a model; your code calls the deployment name. We use chat completions with `tools` (function calling).
- **Why here:** same agent, Azure-native identity and billing.

### Why support both?
Multi-cloud teams run clusters in both clouds and want incident analysis that doesn't depend on one vendor. The agent loop, tools, safety and evaluation are identical; only `providers/bedrock.py` vs `providers/azure_openai.py` differ (~100 lines each). The same evaluation suite also lets you **compare models** objectively.

---

## Architecture

```
src/sre_agent/
  agent.py            investigation loop (step budget, duplicate-call guard, forced final answer)
  providers/          bedrock.py (Converse) · azure_openai.py (chat completions) · base.py (neutral types)
  tools/
    registry.py       tool schemas + guarded executor (redaction, truncation, namespace allow-list)
    backend.py        KubeBackend (real, read-only) — the interface has NO write methods
    cluster_auth.py   token auth to remote EKS/AKS for ECS/AgentCore/Container Apps
  evaluation/         fake cluster, 0–5 scoring, runner / CI gate
  server.py           FastAPI: /investigate, /healthz, plus AgentCore /invocations + /ping
deploy/helm/sre-agent Helm chart (read-only ClusterRole, non-root, read-only rootfs)
infra/aws             ECR, IAM, ECS Fargate, AgentCore, EKS Pod Identity + Helm
infra/azure           Azure OpenAI (keyless), ACR, Container Apps, AKS workload identity + Helm
eval/cases.yaml       incident scenarios
```

### Read-only is enforced in three independent layers
1. **Code:** the backend interface and the tool list contain only reads (a test asserts no `delete/create/patch/exec/scale` tool exists).
2. **Kubernetes RBAC:** `get`/`list` only; no `secrets`, no `pods/exec`.
3. **Cloud IAM:** the runtime identity can only invoke the one model and describe the one cluster.

Additional guard rails: namespace allow-list, secret redaction on logs, output truncation, step budget, duplicate-call blocking, non-root container with read-only root filesystem (Helm).

---

## Quick start

```bash
pip install -e ".[dev]"
pytest -q                                   # unit tests, no cloud required
cp .env.example .env                        # choose provider + cluster access
sre-agent "Why are pods in the shop namespace restarting?"
sre-eval --provider bedrock                 # run the evaluation suite
```

Run as a service: `uvicorn sre_agent.server:app --port 8080`, then
`curl -X POST localhost:8080/investigate -H 'content-type: application/json' -d '{"question":"What is unhealthy?"}'`.

Deploying to the clouds: follow [tech-doc.md](tech-doc.md).

## Evaluation and the 3.75 → 5.0 result
The pipeline in this repo scores each scenario 0–5 (1 point each for naming the culprit, correct reason, cited evidence, calling the required tools, clean execution). The headline improvement from **3.75 to 5.0 out of 5** came from fixing the *tools*, not the model: richer tool descriptions, safe defaults, compact structured outputs, actionable error messages, and filtering to unhealthy pods. Those fixes are implemented in `tools/registry.py` and described in [docs/evaluation.md](docs/evaluation.md).

> Scores depend on the model, region and scenario set. The 3.75 → 5.0 figures are the project's reported result; run `sre-eval` against your own model to reproduce numbers for your environment. The unit tests verify the scoring and loop with scripted models; they do not call a real LLM.

## Status and limits
- Unit tests, `terraform validate` (both stacks) and chart structure are checked in CI. The Terraform has **not been applied** to live accounts from this repo's CI; follow tech-doc.md in a sandbox first.
- Read-only means it can recommend, not remediate. That is deliberate.
- Logs are sent to your chosen model provider after redaction; review that against your data policies.

## License
MIT — see [LICENSE](LICENSE).

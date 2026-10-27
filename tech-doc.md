# Technical guide: deploy the SRE agent to AWS (EKS) and Azure (AKS)

Complete [pre-req-doc.md](pre-req-doc.md) first. This guide has one shared build step, then **one independent track per target**. Pick the ones you need:

| Track | Agent runs on | Model | Investigates | Terraform flag |
|---|---|---|---|---|
| A | **EKS** (in-cluster) | Bedrock Nova | same cluster | `enable_eks` |
| B | **ECS Fargate** | Bedrock Nova | remote EKS | `enable_ecs` |
| C | **Bedrock AgentCore Runtime** | Bedrock Nova | remote EKS | `enable_agentcore` |
| D | **AKS** (in-cluster) | Azure OpenAI | same cluster | `enable_aks` |
| E | **Azure Container Apps** | Azure OpenAI | remote AKS | `enable_container_apps` |

```
 user ──HTTP──> [ agent container ] ──tool calls──> read-only K8s API
                      │  ▲
                      ▼  │ tool_use / function_call
              Bedrock Converse (Nova)   or   Azure OpenAI chat completions
```

---

## 0. Run locally first (10 minutes, no cloud deploy)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q                                              # 11+ tests, no cloud needed

cp .env.example .env     # set SRE_PROVIDER and credentials; SRE_CLUSTER_TYPE=kubeconfig
sre-agent "Which pods are unhealthy and why?"
```

Run the evaluation pipeline against a real model (uses a fake, frozen cluster, so it is repeatable):

```bash
sre-eval --provider bedrock      --out eval/results/bedrock.json
sre-eval --provider azure_openai --out eval/results/azure.json
```

---

## 1. Build and push the image

The Terraform creates the registry, so use a **two-phase apply**: registry first, then image, then everything else.

> **Architecture:** AgentCore Runtime runs **linux/arm64** containers; ECS/EKS/AKS/Container Apps are usually amd64. Build a multi-arch image once and every target works.

### 1A. AWS (ECR)
```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars        # edit eks_cluster_name, flags, subnets
terraform init
terraform apply -target=aws_ecr_repository.agent    # phase 1: only the registry

REPO=$(terraform output -raw ecr_repository_url)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin ${REPO%%/*}
cd ../..
docker buildx build --platform linux/amd64,linux/arm64 -t $REPO:0.1.0 --push .
```
(The repo uses immutable tags: bump `image_tag` for every release.)

### 1B. Azure (ACR)
```bash
cd infra/azure
cp terraform.tfvars.example terraform.tfvars        # edit subscription, RG, AKS names, flags
az login && az account set --subscription <id>
terraform init
terraform apply -target=azurerm_container_registry.this   # phase 1: only the registry

ACR=$(terraform output -raw acr_login_server)
cd ../..
az acr login --name ${ACR%%.*}
docker buildx build --platform linux/amd64,linux/arm64 -t $ACR/sre-agent:0.1.0 --push .
# or, without local Docker:  az acr build -r ${ACR%%.*} -t sre-agent:0.1.0 .
```

---

## Track A — EKS (agent runs inside the cluster)

1. In `infra/aws/terraform.tfvars` set `enable_eks = true`, `eks_cluster_name`, optional `allowed_namespaces`.
2. Make sure your kube identity is cluster-admin (Helm installs a ClusterRole): `aws eks update-kubeconfig --name <cluster>`.
3. Apply everything:
   ```bash
   cd infra/aws && terraform plan -out tfplan && terraform apply tfplan
   ```
   What it creates: IAM role (Nova invoke only) + **EKS Pod Identity association** + Helm release (Deployment, Service, ServiceAccount, read-only ClusterRole/Binding).
4. Verify:
   ```bash
   kubectl -n sre-agent rollout status deploy/sre-agent
   kubectl -n sre-agent port-forward svc/sre-agent 8080:80 &
   curl -s localhost:8080/healthz
   curl -s localhost:8080/investigate -H 'content-type: application/json' \
     -d '{"question":"Which pods are unhealthy in kube-system and why?"}'
   ```
5. Prove it is read-only:
   ```bash
   kubectl auth can-i delete pods --as=system:serviceaccount:sre-agent:sre-agent   # no
   kubectl auth can-i get secrets --as=system:serviceaccount:sre-agent:sre-agent   # no
   ```

## Track B — ECS Fargate (remote EKS)

1. `terraform.tfvars`: `enable_ecs = true`, `vpc_id`, `private_subnet_ids` (see pre-req §2.1 for networking).
2. Your EKS cluster must use authentication mode `API` or `API_AND_CONFIG_MAP`:
   `aws eks update-cluster-config --name <c> --access-config authenticationMode=API_AND_CONFIG_MAP`
3. `terraform apply`. It creates: ECS cluster, task definition, service (private, no public IP), task/execution roles, log group, an **EKS access entry with `AmazonEKSViewPolicy`** for the task role.
4. Smoke test (no inbound port, so use ECS Exec):
   ```bash
   TASK=$(aws ecs list-tasks --cluster sre-agent --query 'taskArns[0]' --output text)
   aws ecs execute-command --cluster sre-agent --task $TASK --container agent --interactive \
     --command "python -c \"import urllib.request as u,json;print(u.urlopen(u.Request('http://127.0.0.1:8080/investigate',json.dumps({'question':'What pods are unhealthy?'}).encode(),{'content-type':'application/json'})).read().decode())\""
   ```
   (Needs the Session Manager plugin for the AWS CLI.) Logs: CloudWatch group `/ecs/sre-agent`.
5. To expose it to users, put an **internal** ALB in front (or call it from other private services). Do not expose it publicly without authentication.

## Track C — Bedrock AgentCore Runtime (remote EKS)

1. `terraform.tfvars`: `enable_agentcore = true`. Image must be **arm64** (done in §1 by multi-arch build).
2. `terraform apply`. Creates the AgentCore runtime role, an access entry (`AmazonEKSViewPolicy`) for it, and `aws_bedrockagentcore_agent_runtime`.
3. Invoke:
   ```bash
   ARN=$(terraform output -raw agentcore_runtime_arn)
   aws bedrock-agentcore invoke-agent-runtime --agent-runtime-arn "$ARN" \
     --runtime-session-id "sre-session-$(date +%s)-0000000000000" \
     --cli-binary-format raw-in-base64-out \
     --payload '{"prompt":"Which pods are unhealthy and why?"}' out.json && cat out.json
   ```
   The container implements the AgentCore contract: `POST /invocations` and `GET /ping` on port 8080.
4. The provider resource is new; if `terraform validate` complains about argument names, check your `hashicorp/aws` version's docs for `aws_bedrockagentcore_agent_runtime` (`>= 6.18` is pinned).

## Track D — AKS (agent runs inside the cluster)

1. `infra/azure/terraform.tfvars`: `enable_aks = true`, cluster/RG names.
2. Auth for Terraform's Helm provider: `az aks get-credentials -g <rg> -n <aks>` and `kubelogin convert-kubeconfig -l azurecli`.
3. `terraform apply`. Creates: Azure OpenAI account (**keyless**, `local_auth_enabled=false`) + `gpt-4o` deployment, ACR, managed identity, `Cognitive Services OpenAI User` role, **federated credential** for `system:serviceaccount:sre-agent:sre-agent`, `AcrPull` for kubelet, Helm release.
4. Verify:
   ```bash
   kubectl -n sre-agent rollout status deploy/sre-agent
   kubectl -n sre-agent port-forward svc/sre-agent 8080:80 &
   curl -s localhost:8080/investigate -H 'content-type: application/json' \
     -d '{"question":"Which pods are unhealthy and why?"}'
   ```
5. If the pod reports `AuthenticationFailed` for OpenAI: confirm the pod has label `azure.workload.identity/use=true` and the ServiceAccount has the `azure.workload.identity/client-id` annotation (`kubectl -n sre-agent get sa,pod -o yaml`), and allow ~1–2 min for role propagation.

## Track E — Azure Container Apps (remote AKS)

1. `terraform.tfvars`: `enable_container_apps = true`. AKS must have **Entra ID + Azure RBAC** enabled (pre-req §3.1).
2. `terraform apply`. Creates Log Analytics, Container Apps environment, the app (ingress **internal**), identity + roles (`AKS RBAC Reader` etc.).
3. Smoke test:
   ```bash
   az containerapp exec -g <rg> -n sre-agent --command \
     "python -c \"import urllib.request as u;print(u.urlopen('http://127.0.0.1:8080/healthz').read())\""
   az containerapp logs show -g <rg> -n sre-agent --follow
   ```
4. If AKS local accounts are disabled, `kube_config` is empty and the CA is missing: pass it explicitly (add a variable and set `SRE_CLUSTER_CA_DATA` from `az aks show ... --query` / your kubeconfig `certificate-authority-data`).

---

## 2. Evaluation gate (before every release)

```bash
sre-eval --provider bedrock      --min-score 4.5
sre-eval --provider azure_openai --min-score 4.5
```
Or run the **eval** GitHub Action (manual dispatch, OIDC). It exits non-zero below the threshold, so it can gate a release. See [docs/evaluation.md](docs/evaluation.md) for the rubric and how tool fixes move the score.

## 3. Production hardening checklist
- [ ] Remote Terraform state with locking (backends are stubbed in `versions.tf`).
- [ ] Set `allowed_namespaces`; keep `max_steps` low.
- [ ] Put authentication in front of `/investigate` (internal ALB + OIDC, API Management, or private network only).
- [ ] Private networking: VPC endpoints for Bedrock; Azure OpenAI private endpoint + `public_network_access_enabled=false`.
- [ ] Image scanning (ECR scan-on-push is on; enable Defender for Containers on ACR).
- [ ] Alerts on Bedrock/OpenAI throttling and on token spend.
- [ ] Retention and PII policy for pod logs processed by the model.

## 4. Teardown
```bash
cd infra/aws   && terraform destroy
cd infra/azure && terraform destroy
```
ECR/ACR repos with images may need `force_delete`/manual cleanup. Shared resources you did not create (EKS/AKS, RG) are never destroyed.

## 5. Troubleshooting
| Symptom | Likely cause / fix |
|---|---|
| `AccessDeniedException ... bedrock:InvokeModel` | Role missing, wrong `bedrock_model_id`, or model not available in region |
| `ValidationException: ... on-demand throughput isn't supported` | Use the inference-profile ID (`us.amazon.nova-pro-v1:0`), not the bare model ID |
| `Forbidden: the agent's service account lacks permission` | RBAC/access entry not applied yet or wrong cluster |
| `401` from EKS API (ECS/AgentCore) | access entry missing; auth mode is `CONFIG_MAP` only |
| `DeploymentNotFound` (Azure OpenAI) | `SRE_AZURE_OPENAI_DEPLOYMENT` must be the **deployment name** |
| `429` from model | quota/throttling: raise TPM / request quota; adaptive retries are already on |
| Agent loops without answering | lower `SRE_MAX_STEPS`; inspect `tools_used` in the response |

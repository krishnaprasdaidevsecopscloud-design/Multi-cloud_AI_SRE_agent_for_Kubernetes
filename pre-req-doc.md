# Prerequisites: accounts, roles, APIs and permissions

Everything you must have **before** following [tech-doc.md](tech-doc.md). Three identities appear throughout; keep them separate:

| Identity | Who/what | When it acts |
|---|---|---|
| **Deployer** | You (or your CI) running `terraform apply` | Deploy time only |
| **Runtime identity** | The agent's own role/identity (task role, pod identity, managed identity) | Every investigation |
| **Cluster identity** | The Kubernetes RBAC subject the agent acts as | Every investigation |

The runtime identity is deliberately tiny: *invoke one model + read the cluster*. It cannot change anything.

---

## 1. Tools on your workstation

| Tool | Min version | Used for |
|---|---|---|
| Git | 2.30 | source control |
| GitHub CLI `gh` | 2.40 | create/push the repo |
| Python | 3.11 | local runs, tests, evaluation |
| Docker | 24 | build the image |
| Terraform | 1.6 | all infrastructure |
| kubectl | matches cluster ±1 | verification |
| Helm | 3.13 | chart lint / manual installs |
| AWS CLI v2 | 2.15 | AWS auth, ECR login, `update-kubeconfig` |
| Azure CLI `az` | 2.60 | Azure auth, ACR build, `get-credentials` |
| kubelogin | 0.1.x | AKS Entra auth (needed by the Terraform helm provider on AKS) |

---

## 2. AWS prerequisites

### 2.1 Account setup
1. An AWS account with a **budget alert** set (LLM calls cost money).
2. An existing **EKS cluster** (1.29+). Required cluster settings:
   - Authentication mode **`API` or `API_AND_CONFIG_MAP`** (needed for access entries; ECS/AgentCore targets).
   - Add-on **`eks-pod-identity-agent`** installed (needed for the EKS target).
3. **Bedrock model access** in your region: Console → Bedrock → *Model access* → confirm **Amazon Nova Pro** (and/or Lite/Micro) is available. Nova models are Amazon-first-party and normally enabled by default; if you see "Request access", request it. Use a region that offers Nova (e.g. `us-east-1`, `us-west-2`).
4. For ECS only: a **VPC with private subnets** that have either a NAT gateway or VPC endpoints for `bedrock-runtime`, `sts`, `ecr.api`, `ecr.dkr`, `logs`, S3 (ECR layers), plus egress to the EKS API endpoint.

### 2.2 AWS service APIs used
`bedrock-runtime` (Converse API), `sts`, `eks`, `ecr`, `ecs`, `logs`, `iam`, `bedrock-agentcore` (control plane for AgentCore Runtime), `xray` (AgentCore tracing).

### 2.3 Deployer permissions (who runs Terraform)
For a sandbox use `AdministratorAccess`. For production grant at least the following (scope `Resource` to your account/region/name-prefix):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "Ecr", "Effect": "Allow", "Action": ["ecr:*"], "Resource": "*"},
    {"Sid": "Iam", "Effect": "Allow", "Action": [
      "iam:CreateRole","iam:DeleteRole","iam:GetRole","iam:PassRole","iam:TagRole","iam:UpdateAssumeRolePolicy",
      "iam:CreatePolicy","iam:DeletePolicy","iam:GetPolicy","iam:GetPolicyVersion","iam:ListPolicyVersions","iam:CreatePolicyVersion","iam:DeletePolicyVersion",
      "iam:AttachRolePolicy","iam:DetachRolePolicy","iam:PutRolePolicy","iam:DeleteRolePolicy","iam:GetRolePolicy",
      "iam:ListRolePolicies","iam:ListAttachedRolePolicies","iam:ListInstanceProfilesForRole"], "Resource": "*"},
    {"Sid": "Eks", "Effect": "Allow", "Action": [
      "eks:DescribeCluster","eks:CreateAccessEntry","eks:DeleteAccessEntry","eks:DescribeAccessEntry",
      "eks:AssociateAccessPolicy","eks:DisassociateAccessPolicy","eks:ListAssociatedAccessPolicies",
      "eks:CreatePodIdentityAssociation","eks:DeletePodIdentityAssociation","eks:DescribePodIdentityAssociation","eks:ListPodIdentityAssociations",
      "eks:TagResource"], "Resource": "*"},
    {"Sid": "Ecs", "Effect": "Allow", "Action": ["ecs:*"], "Resource": "*"},
    {"Sid": "Net", "Effect": "Allow", "Action": [
      "ec2:CreateSecurityGroup","ec2:DeleteSecurityGroup","ec2:Describe*","ec2:AuthorizeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupEgress","ec2:RevokeSecurityGroupIngress","ec2:CreateTags"], "Resource": "*"},
    {"Sid": "Logs", "Effect": "Allow", "Action": ["logs:*"], "Resource": "*"},
    {"Sid": "AgentCore", "Effect": "Allow", "Action": ["bedrock-agentcore:*"], "Resource": "*"},
    {"Sid": "Sts", "Effect": "Allow", "Action": ["sts:GetCallerIdentity"], "Resource": "*"},
    {"Sid": "Helm", "Effect": "Allow", "Action": ["eks:AccessKubernetesApi"], "Resource": "*"}
  ]
}
```

The deployer also needs **Kubernetes admin** on the EKS cluster for `enable_eks=true` (Helm creates a namespace, ClusterRole, ClusterRoleBinding). Grant via an EKS access entry with `AmazonEKSClusterAdminPolicy`.

### 2.4 Runtime permissions (created by Terraform, listed for audit)
Agent role (task role / AgentCore role / pod role):

| Action | Resource | Why |
|---|---|---|
| `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream` | `foundation-model/amazon.nova-*` (all regions) + the pinned `inference-profile/us.amazon.nova-*` | Converse API calls |
| `eks:DescribeCluster` | the one cluster | read endpoint/CA (remote targets) |
| EKS access policy `AmazonEKSViewPolicy` (cluster scope) | the cluster | read-only Kubernetes data plane (ECS/AgentCore) |

> The Converse API is authorised by `bedrock:InvokeModel`; there is no separate `bedrock:Converse` IAM action.

ECS execution role: managed `AmazonECSTaskExecutionRolePolicy`. AgentCore role: ECR pull, CloudWatch Logs, X-Ray (see `infra/aws/agentcore.tf`).

### 2.5 Cluster identity (EKS)
- **In-cluster (EKS target):** Helm ClusterRole `sre-agent-readonly` — `get,list` on `namespaces, pods, pods/log, events, nodes` and `deployments, replicasets, statefulsets, daemonsets`. **No `secrets`, no `pods/exec`, no write verbs.**
- **Remote (ECS/AgentCore):** EKS access entry + `AmazonEKSViewPolicy` (created by Terraform).

---

## 3. Azure prerequisites

### 3.1 Subscription setup
1. Azure subscription with a **budget/cost alert**.
2. **Azure OpenAI access** approved for the subscription, and **quota** for your chosen model in your region (Portal → Azure OpenAI / AI Foundry → *Quotas*). Default `gpt-4o`, Standard, 30K TPM.
3. Resource providers registered:
   ```bash
   for p in Microsoft.CognitiveServices Microsoft.ContainerRegistry Microsoft.App \
            Microsoft.OperationalInsights Microsoft.ContainerService Microsoft.ManagedIdentity; do
     az provider register --namespace $p
   done
   ```
4. An existing **resource group** for the new resources.
5. An existing **AKS cluster** with:
   - `--enable-oidc-issuer` and `--enable-workload-identity`
   - **Microsoft Entra ID integration with Azure RBAC** (`--enable-aad --enable-azure-rbac`) — required for the Container Apps target; recommended for all.

### 3.2 Azure APIs used
Azure OpenAI data plane (`https://<resource>.openai.azure.com`, scope `https://cognitiveservices.azure.com/.default`), Azure Resource Manager, Container Registry, Container Apps, AKS (AAD server app `6dae42f8-4368-4678-94ff-3960e28e3630`), Log Analytics, Managed Identity.

### 3.3 Deployer permissions (who runs Terraform)
| Role | Scope | Why |
|---|---|---|
| `Contributor` | the new resource group | create OpenAI, ACR, Container Apps, identity |
| `Role Based Access Control Administrator` (or `User Access Administrator`) | the resource group, the AKS cluster | Terraform creates role assignments |
| `Reader` | the AKS resource group | read the AKS data source |
| `Azure Kubernetes Service Cluster User Role` + `Azure Kubernetes Service RBAC Cluster Admin` | the AKS cluster | Helm install on AKS target |

No Microsoft Entra directory roles are needed (the federated credential is an ARM resource on the managed identity).

### 3.4 Runtime permissions (created by Terraform, listed for audit)
User-assigned managed identity `sreagent-id`:

| Role | Scope | Why |
|---|---|---|
| `Cognitive Services OpenAI User` | the OpenAI account | call chat completions (keyless) |
| `AcrPull` | the ACR | pull the image (Container Apps) |
| `Azure Kubernetes Service Cluster User Role` | the AKS cluster | fetch cluster info (Container Apps target) |
| `Azure Kubernetes Service RBAC Reader` | the AKS cluster | read-only data plane, **excludes secrets** (Container Apps target) |

The AKS target uses the Helm `ClusterRole` (same as §2.5) plus a **federated identity credential** binding `system:serviceaccount:sre-agent:sreagent` to the identity.

---

## 4. Local development prerequisites
- Python venv: `pip install -e ".[dev]"`
- Any kubeconfig (kind/minikube is fine) with read access.
- For real model calls locally: working `aws sts get-caller-identity` (Bedrock) **or** `az login` + role *Cognitive Services OpenAI User* (Azure OpenAI).
- `pytest` and `sre-eval` against the fake cluster need **no** cloud or cluster access to run the unit tests.

---

## 5. GitHub
- GitHub account and `gh auth login` (scopes: `repo`, `workflow`).
- Optional CI evaluation gate via OIDC (no stored keys):
  - **AWS:** IAM OIDC provider `token.actions.githubusercontent.com`; role trusting `repo:<owner>/Multi-cloud_AI_SRE_agent_for_Kubernetes:*` with only `bedrock:InvokeModel`. Set repo variables `AWS_EVAL_ROLE_ARN`, `AWS_REGION`.
  - **Azure:** App registration + federated credential for the repo; role *Cognitive Services OpenAI User*. Set variables `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`.

---

## 6. Pre-flight checklist

```bash
# AWS
aws sts get-caller-identity
aws bedrock list-foundation-models --by-provider amazon --query "modelSummaries[?contains(modelId,'nova')].modelId"
aws eks describe-cluster --name <cluster> --query "cluster.accessConfig.authenticationMode"
aws eks list-addons --cluster-name <cluster>            # expect eks-pod-identity-agent

# Azure
az account show
az cognitiveservices usage list -l <region> -o table | grep -i openai
az aks show -g <rg> -n <aks> --query "{oidc:oidcIssuerProfile.enabled, wi:securityProfile.workloadIdentity.enabled, rbac:aadProfile.enableAzureRbac}"

# Tooling
terraform version && helm version --short && kubectl version --client
```

## 7. Cost and safety notes
- Each investigation = a few model calls (≈ 3–8 tool steps). Cap with `SRE_MAX_STEPS` (default 8) and `SRE_MAX_TOKENS`.
- Set `SRE_ALLOWED_NAMESPACES` to confine the agent; the tool layer rejects anything else.
- Pod logs may contain secrets; the agent redacts common patterns, but treat the model provider as a data processor and review your compliance posture before pointing it at production logs.

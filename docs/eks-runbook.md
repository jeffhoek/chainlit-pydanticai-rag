# EKS Deployment Runbook — chainlit-pydanticai-rag

This runbook covers deploying the Chainlit + Pydantic AI RAG chatbot to an AWS EKS cluster using GitHub Actions CI/CD. It is modeled after the `blackjackpy-trainer` reference deployment.

---

## Architecture Overview

```
GitHub (push to main)
    ↓
[Build Job]
  • OIDC → AWS credentials (no long-lived keys)
  • docker build → push to ECR (tag: commit SHA)
    ↓
[Deploy Job]
  • Check EKS cluster health (skips gracefully if down)
  • kubectl apply k8s/ manifests
  • Rolling update with new image
  • Wait for rollout (120s timeout)
    ↓
AWS EKS (eks-proto, us-east-2)
  └─ Namespace: rag
      ├─ Deployment: chainlit-rag (1 replica)
      ├─ Service: ClusterIP (port 80 → 8080)
      └─ Ingress: ALB (internet-facing, sticky sessions)
           ↓
      Chainlit app (port 8080)
        • Loads knowledge base from S3 on startup
        • Generates embeddings (OpenAI)
        • In-memory vector store (NumPy)
        • Pydantic AI agent → Claude (Anthropic)
```

### Why 1 Replica?

The vector store is held in memory per-pod. Multiple pods would each hold an independent copy — acceptable with ALB sticky sessions — but starting with 1 replica simplifies the initial deployment. Scale up once you've validated the deployment.

### WebSocket Considerations

Chainlit uses WebSockets. The ALB is configured with:
- **600-second idle timeout** — exceeds Chainlit's session keep-alive to prevent mid-chat drops
- **24-hour sticky sessions** — ensures each browser always routes to the same pod (required for WebSocket state)

---

## Prerequisites

### Tools

| Tool | Purpose | Install |
|------|---------|---------|
| `aws` CLI v2 | ECR login, EKS kubeconfig, IAM | https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html |
| `kubectl` | Apply manifests, check pod status | `brew install kubectl` |
| `eksctl` | IAM identity mapping for RBAC | `brew install eksctl` |
| `docker` or `podman` | Local image build/test | `brew install podman` |
| `uv` | Generate Chainlit auth secret | already in project |

### AWS Requirements

- EKS cluster `eks-proto` is **ACTIVE** in `us-east-2`
- ECR repository `chainlit-pydanticai-rag` exists (created in setup below)
- AWS CLI configured with sufficient permissions for setup steps

### GitHub Repository Requirements

- Repository is in GitHub (not just local)
- You have access to **Settings → Secrets and variables → Actions**

---

## One-Time Setup

### Step 1 — Create ECR Repository

```bash
aws ecr create-repository \
  --repository-name chainlit-pydanticai-rag \
  --region us-east-2
```

Note the registry URI from the output (format: `<account-id>.dkr.ecr.us-east-2.amazonaws.com`).

### Step 2 — Configure GitHub OIDC Provider in AWS

This allows GitHub Actions to assume an IAM role without storing long-lived AWS credentials.

```bash
# Check if OIDC provider already exists (may already be set up from blackjackpy-trainer)
aws iam list-open-id-connect-providers | grep token.actions.githubusercontent.com
```

If not listed, create it:

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

### Step 3 — Create IAM Deploy Role

Replace `<github-org>` and `<repo-name>` with your GitHub org/username and repo name.

```bash
GITHUB_ORG=<your-github-org>
REPO_NAME=chainlit-pydanticai-rag
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Trust policy — allows GitHub Actions to assume this role
cat > /tmp/trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:${GITHUB_ORG}/${REPO_NAME}:*"
        }
      }
    }
  ]
}
EOF

# Create the role
aws iam create-role \
  --role-name github-actions-chainlit-rag \
  --assume-role-policy-document file:///tmp/trust-policy.json

# Attach ECR permissions (push/pull images)
aws iam attach-role-policy \
  --role-name github-actions-chainlit-rag \
  --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser

# Inline policy for EKS access (describe cluster + update kubeconfig)
cat > /tmp/eks-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "eks:DescribeCluster",
        "eks:ListClusters"
      ],
      "Resource": "*"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name github-actions-chainlit-rag \
  --policy-name eks-describe \
  --policy-document file:///tmp/eks-policy.json

# Get the role ARN (you'll need this for Step 6)
aws iam get-role \
  --role-name github-actions-chainlit-rag \
  --query "Role.Arn" \
  --output text
```

### Step 4 — Grant the Deploy Role kubectl Access

```bash
eksctl create iamidentitymapping \
  --cluster eks-proto \
  --region us-east-2 \
  --arn arn:aws:iam::<account-id>:role/github-actions-chainlit-rag \
  --username github-actions \
  --group system:masters
```

> **Note:** `system:masters` is the simplest way to grant full cluster access for CI/CD. For tighter security, create a custom ClusterRole limited to the `rag` namespace.

### Step 5 — Create the Kubernetes Namespace and Secrets

```bash
# Update your kubeconfig to point at eks-proto
aws eks update-kubeconfig --name eks-proto --region us-east-2

# Create the namespace
kubectl apply -f k8s/namespace.yaml

# Generate a Chainlit auth secret
# Run this and copy the output value
uv run chainlit create-secret
# → something like: CHAINLIT_AUTH_SECRET="abc123..."

# Create the k8s secret (substitute real values)
kubectl create secret generic rag-secrets \
  --namespace rag \
  --from-literal=ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  --from-literal=OPENAI_API_KEY=$OPENAI_API_KEY \
  --from-literal=APP_PASSWORD=$APP_PASSWORD \
  --from-literal=CHAINLIT_AUTH_SECRET=$CHAINLIT_AUTH_SECRET \
  --from-literal=AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID \
  --from-literal=AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY \
  --from-literal=S3_BUCKET=$S3_BUCKET \
  --from-literal=S3_KEY=$S3_KEY
```

> **S3 IAM Alternative (IRSA):** For production, consider using IAM Roles for Service Accounts (IRSA) instead of passing `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` as secrets. IRSA eliminates long-lived credentials for S3 access. See the [IRSA documentation](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html).

### Step 6 — Apply the ConfigMap

```bash
kubectl apply -f k8s/configmap.yaml
```

### Step 7 — Add GitHub Actions Secret

In your GitHub repository:
1. Go to **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Name: `AWS_DEPLOY_ROLE_ARN`
4. Value: the role ARN from Step 3 (format: `arn:aws:iam::<account-id>:role/github-actions-chainlit-rag`)

---

## Deploying

Once the one-time setup is complete, deployments happen automatically:

- **Auto-deploy**: push any commit to `main`
- **Manual trigger**: GitHub → Actions → "Deploy to EKS" → "Run workflow"

The workflow:
1. Builds a Docker image tagged with the commit SHA
2. Pushes to ECR
3. Checks the EKS cluster is active (skips deploy gracefully if not)
4. Applies all `k8s/` manifests
5. Does a rolling update (`kubectl set image`) to the new image
6. Waits up to 120s for rollout to complete

---

## Post-Deploy Verification

```bash
# Check pod status (may take 30-60s to become Ready due to embedding generation)
kubectl get pods -n rag -w

# Check logs for successful startup
kubectl logs -n rag deploy/chainlit-rag --follow

# Get the ALB hostname
kubectl get ingress -n rag
# HOSTS column will show the ALB DNS name

# Health check
curl http://<alb-hostname>/healthz
# Expected: {"status":"ok"}

# Open in browser
open http://<alb-hostname>
# → Chainlit login page; use APP_USERNAME / APP_PASSWORD
```

---

## Rollback

```bash
# Roll back to the previous deployment
kubectl rollout undo deployment/chainlit-rag -n rag

# Or roll back to a specific revision
kubectl rollout history deployment/chainlit-rag -n rag
kubectl rollout undo deployment/chainlit-rag -n rag --to-revision=<N>
```

---

## Troubleshooting

### Pod stuck in `Pending`

```bash
kubectl describe pod -n rag -l app=chainlit-rag
```
Common causes: insufficient node resources, image pull error (check ECR permissions), or no nodes available.

### Pod stuck in `Init` / slow to become `Ready`

Expected behavior — the app fetches data from S3 and generates embeddings on startup. The `startupProbe` allows up to **120 seconds** before marking the pod unhealthy. If it's taking longer:

```bash
kubectl logs -n rag deploy/chainlit-rag
# Look for: data loading, embedding progress, or error messages
```

If S3 access fails, the app falls back to the local `data/` directory baked into the image.

### Image pull errors

```bash
kubectl describe pod -n rag -l app=chainlit-rag | grep -A5 Events
```
Ensure the ECR repository exists and the deploy role has `AmazonEC2ContainerRegistryPowerUser`.

### WebSocket disconnects mid-chat

Check the ALB idle timeout. If users are seeing disconnects, confirm the ingress annotation is set to `idle_timeout.timeout_seconds=600`.

### Updating secrets

Kubernetes secrets are not automatically reloaded by running pods. After updating:

```bash
kubectl delete secret rag-secrets -n rag
kubectl create secret generic rag-secrets --namespace rag \
  --from-literal=ANTHROPIC_API_KEY=<new-value> \
  # ... all other values
kubectl rollout restart deployment/chainlit-rag -n rag
```

### Scaling up replicas

The in-memory vector store is rebuilt independently per pod. With ALB sticky sessions, each user session stays on one pod. Scale up once validated:

```bash
kubectl scale deployment chainlit-rag -n rag --replicas=2
```

---

## Environment Variables Reference

### Stored as Kubernetes Secret (`rag-secrets`)

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic Claude API key |
| `OPENAI_API_KEY` | OpenAI API key for embeddings |
| `APP_PASSWORD` | Chainlit login password |
| `CHAINLIT_AUTH_SECRET` | Chainlit session signing secret (`chainlit create-secret`) |
| `AWS_ACCESS_KEY_ID` | AWS credentials for S3 data loading |
| `AWS_SECRET_ACCESS_KEY` | AWS credentials for S3 data loading |
| `S3_BUCKET` | S3 bucket containing the knowledge base |
| `S3_KEY` | S3 object key for the knowledge base file |

### Stored as Kubernetes ConfigMap (`rag-config`)

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_USERNAME` | `admin` | Chainlit login username |
| `AWS_REGION` | `us-east-2` | AWS region for S3 |
| `LLM_MODEL` | `anthropic:claude-haiku-4-5-20251001` | Pydantic AI model string |
| `TOP_K` | `5` | Number of chunks returned by RAG retrieval |
| `SYSTEM_PROMPT` | _(see configmap)_ | System prompt injected into the Pydantic AI agent |

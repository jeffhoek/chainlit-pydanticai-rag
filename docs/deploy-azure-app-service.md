# Deploying to Azure App Service

This guide walks through deploying the RAG chatbot to Azure App Service as a Linux container, using Azure Container Registry for images, Azure Key Vault for secrets, and Azure Blob Storage for RAG content. CI/CD runs via Azure Pipelines with Workload Identity Federation — no static credentials.

Two requirements shape the infrastructure design:
- **WebSocket support** (Chainlit) → ARR sticky sessions (`clientAffinityEnabled: true`)
- **120s+ startup time** (blob load + embedding generation) → `WEBSITE_CONTAINER_START_TIME_LIMIT: 230`

---

## Architecture

```
GitHub (source) → Azure Pipelines → ACR (images)
                                        ↓
                              App Service (Linux container)
                                ↓              ↓
                           Key Vault      Blob Storage
                                ↑              ↑
                     User-Assigned Managed Identity (RBAC)

Azure Policy  → governs resource group
Azure Bicep   → provisions all infrastructure (Resource Manager)
```

---

## Service Mapping

| AWS | GCP | Azure | Notes |
|---|---|---|---|
| ECR | Artifact Registry | Container Registry (ACR) | Admin disabled; Managed Identity pull |
| EKS | Cloud Run | App Service (Linux container) | WebSockets + ARR sticky sessions |
| SSM Parameter Store | Secret Manager | Key Vault | RBAC authorization model; KV references in app settings |
| S3 | Cloud Storage | Blob Storage | `azure-storage-blob` SDK; `DefaultAzureCredential` auth |
| EKS Pod Identity | Workload Identity / Service Account | User-Assigned Managed Identity | Requires `AZURE_CLIENT_ID` app setting |
| GitHub Actions + AWS OIDC | Cloud Build + Workload Identity | Azure Pipelines + Workload Identity Federation | No static credentials |
| CloudFormation | Terraform / Cloud Deployment Manager | Bicep / Azure Resource Manager | IaC layer |
| — | Organization Policy | Azure Policy | Enforce HTTPS, required tags |
| — | IAM | Azure RBAC | Minimal-privilege role assignments |

---

## Resource Names

Pattern: `{type}-chainlit-rag-{env}` (globally unique resources drop hyphens)

| Resource | Dev |
|---|---|
| Resource Group | `rg-chainlit-rag-dev` |
| Managed Identity | `id-chainlit-rag-dev` |
| Container Registry | `acrchainlitragdev` |
| App Service Plan | `asp-chainlit-rag-dev` |
| App Service | `app-chainlit-rag-dev` |
| Key Vault | `kv-chainlit-rag-dev` |
| Storage Account | `stchainlitragdev` |
| Blob Container | `rag-content` |

---

## Prerequisites

- Azure CLI (`az`) authenticated to the target subscription
- Azure DevOps project created (e.g., `chainlit-rag`)
- Contributor access on the target resource group (or subscription for first deploy)
- `az bicep upgrade` run at least once (Bicep CLI 0.18+ required for `.bicepparam`)

---

## Step 1: Create the Resource Group (one-time)

```bash
az group create \
  --name rg-chainlit-rag-dev \
  --location eastus \
  --tags environment=dev application=chainlit-rag
```

---

## Step 2: Azure DevOps Setup (one-time)

> **New to Azure DevOps?** There are two separate portals used in this step:
> - **Azure DevOps** → [dev.azure.com](https://dev.azure.com) — pipelines, service connections, environments
> - **Azure Portal** → [portal.azure.com](https://portal.azure.com) — all Azure resources (Key Vault, App Service, Microsoft Entra ID, etc.)
>
> Keep both open in separate tabs.

### 2.0 Connect Azure DevOps to your Entra ID tenant (new organizations only)

If your Azure DevOps organization was just created, it is not yet linked to the Microsoft Entra ID (formerly Azure Active Directory) tenant that manages your Azure subscription. Without this link, Azure DevOps cannot list your resource groups or automatically create app registrations.

In **Azure DevOps** ([dev.azure.com](https://dev.azure.com)):

1. Click **Organization Settings** (bottom-left gear icon)
2. In the left sidebar under **General**, click **Microsoft Entra**
3. Click **Connect directory**
4. Select the Entra ID tenant that owns your Azure subscription
5. Confirm — you will be signed out and redirected back to Azure DevOps

### 2.1 Open Service Connections

In **Azure DevOps** ([dev.azure.com](https://dev.azure.com)):

1. Select your project
2. Click **Project Settings** (bottom-left gear icon)
3. In the left sidebar under **Pipelines**, click **Service connections**
4. Click **New service connection** (top right)

### 2.2 Create the GitHub service connection

This connection allows Azure Pipelines to check out your source code from GitHub.

1. Select **GitHub** → click **Next**
2. Under **Authentication method**, leave **Grant authorization** selected
3. Under **OAuth Configuration**, the only option is **AzurePipelines** — this is correct, leave it selected
4. Click **Authorize** — a GitHub OAuth window will open; approve access
5. Under **Service connection name**, enter: `github-chainlit-rag`
6. Check **Grant access permission to all pipelines**
7. Click **Save**

### 2.3 Create the Azure Resource Manager service connection

This connection allows Azure Pipelines to deploy resources to your Azure subscription using Workload Identity Federation (WIF) — a modern, credential-free authentication method.

1. Click **New service connection** again
2. Select **Azure Resource Manager** → click **Next**
3. Leave **Identity type** as **App registration (automatic)** (recommended)
4. Leave **Credential** as **Workload identity federation** (recommended)
5. Leave **Scope level** as **Subscription**
6. Under **Subscription**, select your Azure subscription
7. Under **Resource group**, select `rg-chainlit-rag-dev`
   - If the dropdown shows "Loading..." indefinitely, your Entra ID directory is not connected — complete step 2.0 first, then return here
8. Under **Service connection name**, enter: `azure-chainlit-rag`
9. Check **Grant access permission to all pipelines**
10. Click **Save**

Azure DevOps automatically creates an App Registration (service principal) in your Entra ID tenant to represent this connection.

### 2.4 Find the pipeline service principal Object ID

The pipeline service principal is the identity Azure Pipelines uses to deploy infrastructure. Its Object ID is needed so Bicep can grant it the correct roles.

> **App Registration vs Enterprise Application:** Creating a service connection creates two related objects in Entra ID: an **App Registration** (the application definition) and an **Enterprise Application** (the service principal — the actual identity that runs and gets role assignments). For role assignments, you need the **Enterprise Application's Object ID**, not the App Registration's Object ID. These are different GUIDs.

The easiest way is via the CLI:

```bash
az ad sp list --display-name "azure-chainlit-rag" --query "[0].id" -o tsv
```

Or via the **Azure Portal** tab ([portal.azure.com](https://portal.azure.com)):

1. In the top search bar, search for **Microsoft Entra ID** and select it
2. In the left sidebar, click **Enterprise applications** (not App registrations)
3. In the search box, type `azure-chainlit-rag`
4. Click the matching result
5. On the Overview page, copy the **Object ID** value

### 2.5 Add the Object ID as a pipeline variable

This value is passed to Bicep so it can grant the pipeline identity the roles it needs to deploy resources.

In your local repository, open `azure-pipelines.yml` and add a `variables:` block (or add to the existing one):

```yaml
variables:
  PIPELINE_SP_OBJECT_ID: '<paste-your-object-id-here>'
```

This is not a secret — it is safe to commit to the repository.

### 2.6 Create the Pipeline

This registers your `azure-pipelines.yml` file with Azure DevOps so it knows how to build and deploy the app.

In **Azure DevOps** ([dev.azure.com](https://dev.azure.com)):

1. In the left sidebar, click the **Pipelines** rocket icon
2. Click **Pipelines** → **New pipeline**
3. Select **GitHub** as the source
4. Authorize GitHub if prompted, then select the `chainlit-pydanticai-rag` repository
5. When asked to configure, select **Existing Azure Pipelines YAML file**
6. Set branch to `main` and path to `/azure-pipelines.yml` → click **Continue**
7. Click the dropdown arrow next to **Run** and choose **Save** — do not run yet, finish the remaining setup steps first

### 2.7 Create the Deployment Environment

Azure DevOps Environments are used to track deployments and optionally require manual approval before the pipeline deploys to a given target.

In **Azure DevOps** ([dev.azure.com](https://dev.azure.com)):

1. In the left sidebar, click the **Pipelines** rocket icon (this is the main Pipelines section, not Project Settings)
2. Click **Environments** in the left sidebar
3. Click **New environment**
4. Enter name: `chainlit-rag-dev`
5. Leave **Resource** as **None**
6. Click **Create**

> **Why two sidebars?** Azure DevOps has a left sidebar for the main Pipelines section (rocket icon) and a separate left sidebar for Project Settings (gear icon). Environments live in the main Pipelines section, not in Project Settings.

---

> **How it all fits together:** The pipeline service principal (created in 2.3) needs **Contributor** on the resource group to provision Azure resources on the first run. After that first run, the Bicep `rbac` module grants it only the minimal roles it needs going forward (Azure Container Registry Push, Website Contributor). The `PIPELINE_SP_OBJECT_ID` variable (2.4–2.5) is what tells Bicep which service principal to assign those roles to. The pipeline (2.6) and environment (2.7) must exist before the first push to `main` will produce a successful run.

---

## Step 3: Deploy Infrastructure (Bicep)

The pipeline does this automatically on every push to `main`. To deploy manually:

### Set env
```
PIPELINE_SP_OBJECT_ID=<pipeline-sp-object-id>
```

### Dry run — shows what will change
```bash
az deployment group what-if \
  --resource-group rg-chainlit-rag-dev \
  --template-file infra/main.bicep \
  --parameters infra/parameters.dev.bicepparam \
  --parameters pipelineServicePrincipalObjectId=$PIPELINE_SP_OBJECT_ID
```
```
# Expected:
...
Resource changes: 13 to create, 3 unsupported.
Diagnostics (3):
...
```


### Apply
```
az deployment group create \
  --resource-group rg-chainlit-rag-dev \
  --template-file infra/main.bicep \
  --parameters infra/parameters.dev.bicepparam \
  --parameters pipelineServicePrincipalObjectId=$PIPELINE_SP_OBJECT_ID \
  --mode Incremental
```

**Module deployment order** (enforced by `dependsOn` in `main.bicep`):

1. `identity` — User-Assigned Managed Identity (outputs feed everything else)
2. `acr` — Container Registry (admin disabled; Managed Identity pull only)
3. `keyVault` — Key Vault (RBAC authorization model, soft delete 7 days)
4. `storage` — Storage Account + `rag-content` blob container (no public access)
5. `appService` — App Service Plan (B2) + Web App with all app settings and KV references
6. `rbac` — All role assignments (must complete before App Service resolves KV refs)
7. `policy` — Azure Policy assignments (HTTPS-only, require `environment`/`application` tags)

---

## Step 4: Provision Key Vault Secrets (one-time)

Secrets are not created by Bicep. Run these after the first successful infrastructure deploy.

### 4.0 Grant yourself write access to Key Vault (one-time)

The Key Vault uses the RBAC authorization model — no one has access by default, including the person who deployed it. The Bicep `rbac` module only grants the App Service's managed identity read access. You must explicitly grant yourself write access before you can set secrets.

```bash
USER_OID=$(az ad signed-in-user show --query id -o tsv)

az role assignment create \
  --role "Key Vault Secrets Officer" \
  --assignee-object-id $USER_OID \
  --assignee-principal-type User \
  --scope $(az keyvault show \
      --name kv-chainlit-rag-dev \
      --resource-group rg-chainlit-rag-dev \
      --query id -o tsv)
```

### 4.1 Set the secrets

```bash
az keyvault secret set \
  --vault-name kv-chainlit-rag-dev \
  --name anthropic-api-key \
  --value "$ANTHROPIC_API_KEY"

az keyvault secret set \
  --vault-name kv-chainlit-rag-dev \
  --name openai-api-key \
  --value "$OPENAI_API_KEY"

az keyvault secret set \
  --vault-name kv-chainlit-rag-dev \
  --name app-password \
  --value "$APP_PASSWORD"

az keyvault secret set \
  --vault-name kv-chainlit-rag-dev \
  --name chainlit-auth-secret \
  --value "$CHAINLIT_AUTH_SECRET"
```

Restart the App Service to re-resolve the Key Vault references:

```bash
az webapp restart \
  --name app-chainlit-rag-dev \
  --resource-group rg-chainlit-rag-dev
```

---

## Step 5: Upload RAG Content to Blob Storage (one-time)

### 5.0 Grant yourself write access to Blob Storage (one-time)

Like Key Vault, the storage account uses RBAC — you need to grant yourself access before you can upload blobs.

```bash
az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee-object-id $(az ad signed-in-user show --query id -o tsv) \
  --assignee-principal-type User \
  --scope $(az storage account show \
      --name stchainlitragdev \
      --resource-group rg-chainlit-rag-dev \
      --query id -o tsv)
```

### 5.1 Upload the content file

```bash
az storage blob upload \
  --account-name stchainlitragdev \
  --container-name rag-content \
  --name content.txt \
  --file data/content.txt \
  --auth-mode login
```

---

## Step 6: Trigger the Pipeline

Push to `main` to trigger all three stages automatically:

```
Build       → docker build + push to ACR (tags: <git-sha-short>, latest)
DeployInfra → Bicep what-if + incremental deploy
DeployApp   → az webapp config container set + restart + /healthz poll (240s)
```

To trigger manually without a code change:

```bash
az pipelines run --name chainlit-pydanticai-rag
```

---

## Verification

```bash
# 1. All resources provisioned
az resource list --resource-group rg-chainlit-rag-dev -o table

# 2. KV references resolved (look for "Resolved" in the value column, not "Failed")
az webapp config appsettings list \
  --name app-chainlit-rag-dev \
  --resource-group rg-chainlit-rag-dev \
  --query "[?contains(value, '@Microsoft.KeyVault')]" -o table

# 3. Image present in ACR
az acr repository show-tags \
  --name acrchainlitragdev \
  --repository chainlit-pydanticai-rag \
  -o table

# 4. Health check responds 200
curl -v https://app-chainlit-rag-dev.azurewebsites.net/healthz

# 5. App logs confirm blob load and embedding success
az webapp log tail \
  --name app-chainlit-rag-dev \
  --resource-group rg-chainlit-rag-dev
# Expected: "Loading knowledge base from https://stchainlitragdev.blob.core.windows.net/..."
# Expected: "Ready! Loaded N chunks from the knowledge base."

# 6. WebSocket: open app in browser → DevTools → Network → WS tab → active connection

# 7. Sticky sessions: check browser cookies for ARRAffinity cookie after login
```

---

## Redeploying

**New code:** push to `main` — pipeline handles everything.

**New content file only:**

```bash
az storage blob upload \
  --account-name stchainlitragdev \
  --container-name rag-content \
  --name content.txt \
  --file data/content.txt \
  --auth-mode login

az webapp restart \
  --name app-chainlit-rag-dev \
  --resource-group rg-chainlit-rag-dev
```

**Updated secret value:**

```bash
az keyvault secret set \
  --vault-name kv-chainlit-rag-dev \
  --name <secret-name> \
  --value "<new-value>"

az webapp restart \
  --name app-chainlit-rag-dev \
  --resource-group rg-chainlit-rag-dev
```

---

## Troubleshooting

**KV reference not resolving (App Service shows "Failed")**
- Confirm the managed identity has `Key Vault Secrets User` on the vault: `az role assignment list --scope <kv-resource-id>`
- Confirm `AZURE_CLIENT_ID` app setting matches the MI's **client ID** (not object/principal ID)
- Re-run the Bicep `rbac` module, then restart the app

**Container pull failing (App Service can't pull from ACR)**
- Both `acrUseManagedIdentityCreds: true` AND `acrUserManagedIdentityID` must be set together — missing `acrUserManagedIdentityID` causes App Service to try the system-assigned MI (not enabled)
- Confirm the MI has `AcrPull` on the registry: `az role assignment list --scope <acr-resource-id>`

**`DefaultAzureCredential` picks wrong identity**
- `AZURE_CLIENT_ID` must be set to the user-assigned MI's **client ID** (not object/principal ID)
- Without it, the SDK falls through to system-assigned MI and fails

**Container startup timeout**
- `WEBSITE_CONTAINER_START_TIME_LIMIT: 230` allows 230s; if startup still times out, check logs for errors during blob load or embedding generation
- The B2 plan has `alwaysOn: true`, so cold starts only happen after a restart or deploy

**Bicep deploy fails with `.bicepparam` syntax error**
- Run `az bicep upgrade` to ensure Bicep CLI 0.18+
- The pipeline's DeployInfra stage runs `az bicep upgrade` automatically before deploying

**Policy assignment fails with authorization error**
- `Microsoft.Authorization/policyAssignments` requires `Resource Policy Contributor` on the resource group
- Run the `policy` module manually the first time with a higher-privileged identity, or grant the pipeline SP that role temporarily

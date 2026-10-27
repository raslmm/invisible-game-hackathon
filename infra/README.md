# Azure Cloud Deployment Guide

This directory provides Infrastructure as Code (IaC) to deploy **The Invisible Game** to Microsoft Azure Container Apps with optional Azure AI Foundry integration.

## One-Click Deployment via Azure CLI

```bash
# 1. Log in to Azure
az login

# 2. Create a resource group
az group create --name rg-invisible-game --location eastus

# 3. Build and deploy container directly using Azure Container Apps
az containerapp up \
  --name invisible-game-live \
  --resource-group rg-invisible-game \
  --location eastus \
  --source . \
  --target-port 8765 \
  --ingress external

# 4. (Optional) Configure Azure AI Foundry / Azure OpenAI model endpoint
az containerapp update \
  --name invisible-game-live \
  --resource-group rg-invisible-game \
  --set-env-vars \
    AZURE_AI_FOUNDRY_ENDPOINT="https://<your-foundry-resource>.openai.azure.com" \
    AZURE_AI_MODEL_DEPLOYMENT="gpt-4o-mini" \
    AZURE_INFERENCE_CREDENTIAL="<your-azure-key>"
```

## Bicep Deployment

Alternatively, deploy using the Bicep template:

```powershell
az deployment group create `
  --resource-group rg-invisible-game `
  --template-file infra/main.bicep
```

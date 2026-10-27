@description('Location for all resources.')
param location string = resourceGroup().location

@description('Name of the Invisible Passes Container App.')
param appName string = 'invisible-passes-${uniqueString(resourceGroup().id)}'

@description('Container image to deploy.')
param containerImage string = 'mcr.microsoft.com/azure-cli:latest'

@description('Optional Azure AI Foundry model deployment name.')
param azureAiModelDeployment string = ''

@description('Optional Azure AI Foundry endpoint.')
param azureAiFoundryEndpoint string = ''

@secure()
@description('Optional Azure AI Foundry inference credential.')
param azureInferenceCredential string = ''

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${appName}-logs'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource containerAppEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: '${appName}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: appName
  location: location
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8765
        transport: 'auto'
      }
      secrets: empty(azureInferenceCredential) ? [] : [
        {
          name: 'azure-inference-credential'
          value: azureInferenceCredential
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'invisible-passes-web'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
          env: concat(
            [
              {
                name: 'PYTHONUNBUFFERED'
                value: '1'
              }
            ],
            empty(azureAiModelDeployment) ? [] : [
              {
                name: 'AZURE_AI_MODEL_DEPLOYMENT'
                value: azureAiModelDeployment
              }
            ],
            empty(azureAiFoundryEndpoint) ? [] : [
              {
                name: 'AZURE_AI_FOUNDRY_ENDPOINT'
                value: azureAiFoundryEndpoint
              }
            ],
            empty(azureInferenceCredential) ? [] : [
              {
                name: 'AZURE_INFERENCE_CREDENTIAL'
                secretRef: 'azure-inference-credential'
              }
            ]
          )
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
    }
  }
}

output appFqdn string = containerApp.properties.configuration.ingress.fqdn

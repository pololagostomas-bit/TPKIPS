<##
Despliegue de PILOTO de Triton Picking en Azure App Service.

No sube datos ni credenciales desde este repositorio. Necesita que quien lo
ejecute haya iniciado sesión con `az login` y tenga permisos para crear recursos
en la suscripción elegida. Construye la imagen directamente en Azure Container
Registry, por lo que Docker local no es necesario.

SQLite es válido aquí solo para un piloto de UNA instancia. Antes de aumentar
instancias o usar operación productiva se debe migrar a PostgreSQL administrado.
##>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $SubscriptionId,
    [Parameter(Mandatory)] [string] $ResourceGroup,
    [Parameter(Mandatory)] [string] $Location,
    [Parameter(Mandatory)] [ValidatePattern('^[a-z0-9-]{2,60}$')] [string] $AppName,
    [Parameter(Mandatory)] [ValidatePattern('^[a-z0-9]{5,50}$')] [string] $RegistryName,
    [ValidateSet('demo', 'entra')] [string] $AuthMode = 'demo'
)

$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$planName = "$AppName-plan"
$imageName = 'triton-picking:pilot'

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'No se encontró Azure CLI. Instálalo y ejecuta az login antes de continuar.'
}

az account set --subscription $SubscriptionId
az group create --name $ResourceGroup --location $Location --output none

# ACR no admite guiones en el nombre; el parámetro lo valida antes de crear nada.
az acr create --resource-group $ResourceGroup --name $RegistryName --sku Basic --admin-enabled false --output none
az acr build --registry $RegistryName --image $imageName --file "$projectPath\infrastructure\Dockerfile" $projectPath

# B1 permite ejecutar un contenedor Linux y es suficiente para el piloto.
az appservice plan create --resource-group $ResourceGroup --name $planName --location $Location --is-linux --sku B1 --output none

$image = "$RegistryName.azurecr.io/$imageName"
az webapp create --resource-group $ResourceGroup --plan $planName --name $AppName `
    --container-image-name $image --assign-identity '[system]' `
    --acr-use-identity --acr-identity '[system]' --output none

# La identidad de la Web App necesita leer la imagen privada desde ACR. Esto
# exige permiso para asignar roles (Owner, User Access Administrator o RBAC
# Administrator) además de Contributor para crear los recursos.
$webPrincipalId = az webapp identity show --resource-group $ResourceGroup --name $AppName --query principalId --output tsv
$acrResourceId = az acr show --resource-group $ResourceGroup --name $RegistryName --query id --output tsv
az role assignment create --assignee-object-id $webPrincipalId --assignee-principal-type ServicePrincipal `
    --role AcrPull --scope $acrResourceId --output none

# El portal persiste /home cuando esta variable está activa. Se mantiene una sola
# instancia: SQLite no debe compartirse entre instancias ni montarse en Azure Files.
az webapp config appsettings set --resource-group $ResourceGroup --name $AppName --settings `
    HOST=0.0.0.0 PORT=8000 WEBSITES_PORT=8000 `
    WEBSITES_ENABLE_APP_SERVICE_STORAGE=true `
    TRITON_DB_PATH=/home/data/triton.db TRITON_AUTH_MODE=$AuthMode --output none
az webapp config set --resource-group $ResourceGroup --name $AppName --health-check-path /health --output none
az webapp config set --resource-group $ResourceGroup --name $AppName --number-of-workers 1 --output none
az webapp restart --resource-group $ResourceGroup --name $AppName

$hostName = az webapp show --resource-group $ResourceGroup --name $AppName --query defaultHostName --output tsv
Write-Host "Piloto publicado en https://$hostName"
if ($AuthMode -eq 'demo') {
    Write-Warning 'Está en modo demo. Antes de compartirlo con usuarios, configura Microsoft Entra y vuelve a ejecutar con -AuthMode entra.'
}

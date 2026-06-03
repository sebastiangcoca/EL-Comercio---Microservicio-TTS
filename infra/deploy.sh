#!/bin/bash

# ------------------ Cambiar al directorio raíz del proyecto ------------------
# Obtener el directorio donde está el script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# El directorio raíz está un nivel arriba del script
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
echo "📁 Cambiando al directorio raíz del proyecto: $PROJECT_ROOT"
cd "$PROJECT_ROOT" || {
  echo "❌ Error al cambiar al directorio raíz del proyecto"
  exit 1
}

# ------------------ Verificar Login en Azure ------------------
echo "🔐 Verificando autenticación en Azure..."
az account show > /dev/null 2>&1 || {
  echo "❌ No estás autenticado en Azure"
  echo "   Por favor, ejecuta: az login"
  exit 1
}
echo "✅ Autenticación verificada"

# ------------------ Configuración ------------------
RESOURCE_GROUP="POCText"
LOCATION="eastus2"
REGISTRY_NAME="acrvoicetranscription"
REGISTRY_LOGIN_SERVER="acrvoicetranscription.azurecr.io"
BASE_IMAGE_NAME="tts-api"
IMAGE_VERSION=$(date +"%Y%m%d%H%M%S")
IMAGE_NAME="$BASE_IMAGE_NAME:$IMAGE_VERSION"
CONTAINER_APP_NAME="acatextvoicetranscription"
ENVIRONMENT="dev"
DOCKERFILE="Dockerfile"

# ------------------ Login en ACR ------------------
echo "🔐 Iniciando sesión en Azure Container Registry..."
az acr login --name $REGISTRY_NAME || {
  echo "❌ Error al iniciar sesión en ACR"
  exit 1
}

# ------------------ Build de la imagen Docker ------------------
echo "🔨 Construyendo imagen Docker: $IMAGE_NAME ..."
docker build -f "$DOCKERFILE" -t $REGISTRY_LOGIN_SERVER/$IMAGE_NAME . || {
  echo "❌ Error al construir la imagen Docker"
  exit 1
}

# ------------------ Push de la imagen a ACR ------------------
echo "📤 Subiendo imagen Docker a ACR..."
docker push $REGISTRY_LOGIN_SERVER/$IMAGE_NAME || {
  echo "❌ Error al subir la imagen a ACR"
  exit 1
}

# ------------------ Habilitar Admin User del ACR (si no está habilitado) ------------------
echo "🔐 Verificando y habilitando admin user del ACR..."
ADMIN_ENABLED=$(az acr show --name $REGISTRY_NAME --query adminUserEnabled --output tsv 2>/dev/null || echo "false")
if [ "$ADMIN_ENABLED" != "true" ]; then
  echo "   Habilitando admin user del ACR..."
  az acr update -n $REGISTRY_NAME --admin-enabled true || {
    echo "❌ Error al habilitar admin user del ACR"
    exit 1
  }
  echo "   ✅ Admin user habilitado"
else
  echo "   ✅ Admin user ya está habilitado"
fi

# ------------------ Obtener credenciales del ACR ------------------
echo "🔐 Obteniendo credenciales del ACR..."
ACR_USERNAME=$(az acr credential show --name $REGISTRY_NAME --query username --output tsv 2>/dev/null)
ACR_PASSWORD=$(az acr credential show --name $REGISTRY_NAME --query passwords[0].value --output tsv 2>/dev/null)

# Verificar que se obtuvieron las credenciales
if [ -z "$ACR_USERNAME" ] || [ -z "$ACR_PASSWORD" ]; then
  echo "❌ Error: No se pudieron obtener las credenciales del ACR"
  echo "   Verifica que el admin user esté habilitado y que tengas permisos"
  exit 1
fi

# ------------------ Configurar Registry en Container App ------------------
echo "🔐 Configurando credenciales del registry en Container App..."
az containerapp registry set \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --server $REGISTRY_LOGIN_SERVER \
  --username $ACR_USERNAME \
  --password $ACR_PASSWORD || {
  echo "❌ Error al configurar credenciales del registry en Container App"
  echo "   Verifica que el Container App exista y que tengas permisos"
  exit 1
}
echo "✅ Credenciales del registry configuradas correctamente"

# ------------------ Actualizar Container App ------------------
echo "🚀 Actualizando Container App con nueva imagen..."
echo "   Imagen: $REGISTRY_LOGIN_SERVER/$IMAGE_NAME"
echo ""
echo "⚠️  NOTA: Las variables de entorno deben estar configuradas en Azure Container App"
echo ""

az containerapp update \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --image $REGISTRY_LOGIN_SERVER/$IMAGE_NAME || {
  echo "❌ Error al actualizar Container App"
  exit 1
}

# ------------------ Configurar Puerto de Ingress ------------------
echo "🔧 Configurando puerto de ingress a 8000..."
az containerapp ingress update \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --target-port 8000 \
  --type external \
  --transport auto || {
  echo "❌ Error: No se pudo actualizar el puerto de ingress"
  echo "   Por favor, verifica los permisos y configura manualmente en Azure Portal"
  exit 1
}

# Verificar configuración del ingress
echo "🔍 Verificando configuración del ingress..."
INGRESS_TARGET_PORT=$(az containerapp ingress show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query targetPort \
  --output tsv 2>/dev/null)

if [ "$INGRESS_TARGET_PORT" = "8000" ]; then
  echo "   ✅ Puerto de ingress configurado correctamente: $INGRESS_TARGET_PORT"
else
  echo "   ⚠️  Advertencia: El puerto del ingress es $INGRESS_TARGET_PORT, esperado 8000"
  echo "   Intenta actualizarlo manualmente o ejecuta el deploy nuevamente"
fi

# Obtener la URL de la aplicación
APP_URL=$(az containerapp show \
  --name $CONTAINER_APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query properties.configuration.ingress.fqdn \
  --output tsv 2>/dev/null)

if [ -n "$APP_URL" ]; then
  echo "   🌐 URL de la aplicación: https://$APP_URL"
  echo "   📚 Swagger UI: https://$APP_URL/docs"
fi

# ------------------ Resumen del Deploy ------------------
echo ""
echo "✅ Deploy completado exitosamente"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📦 Imagen:       $REGISTRY_LOGIN_SERVER/$IMAGE_NAME"
echo "🏗️  App:          $CONTAINER_APP_NAME"
echo "🌍 Ambiente:     $ENVIRONMENT"
echo "📍 Región:       $LOCATION"
if [ -n "$APP_URL" ]; then
  echo "🌐 URL:          https://$APP_URL"
  echo "📚 Swagger UI:  https://$APP_URL/docs"
  echo "📖 ReDoc:       https://$APP_URL/redoc"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "💡 Configuración requerida en Azure Container App:"
echo ""
echo "   📋 Variable de entorno OBLIGATORIA:"
echo "      - 'key-vault-name': Nombre del Azure Key Vault (ej: 'kv-framework-qa')"
echo ""
echo "   📋 Variables de entorno OPCIONALES:"
echo "      - 'USE_KEY_VAULT': 'true' (por defecto) o 'false' para deshabilitar Key Vault"
echo "      - 'TESTING': 'false' (por defecto) o 'true' para deshabilitar Key Vault en testing"
echo ""
echo "   🔐 Autenticación con Key Vault:"
echo "      - El proyecto usa DefaultAzureCredential (funciona automáticamente con Managed Identity)"
echo "      - Si Key Vault no está disponible, hace fallback a variables de entorno"
echo ""
echo "   📝 Configurar en:"
echo "      Azure Container Apps > $CONTAINER_APP_NAME > Configuration > Environment variables"
echo ""
echo "   ℹ️  Nota: Los secretos se obtienen automáticamente desde Azure Key Vault."
echo "            Solo necesitas configurar 'key-vault-name' para habilitar Key Vault."
echo ""

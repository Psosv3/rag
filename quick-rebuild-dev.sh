#!/bin/bash

# Script de rebuild rapide pour modifications de code (ENVIRONNEMENT DEV)
# Usage: ./quick-rebuild-dev.sh [service-name]

set -e

SERVICE=${1:-rag-api-dev}

# Couleurs
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[REBUILD-DEV]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log "🚀 Rebuild rapide pour $SERVICE (DEV)"

# Vérifier que docker-compose-dev.yml existe
if [ ! -f "docker-compose-dev.yml" ]; then
    error "docker-compose-dev.yml non trouvé"
    exit 1
fi

# Vérifier que .env.dev existe
if [ ! -f ".env.dev" ]; then
    warn ".env.dev non trouvé"
    log "Créez votre fichier .env.dev depuis le template:"
    log "  cp env.dev.template .env.dev"
    error "Fichier .env.dev requis pour l'environnement dev"
    exit 1
fi

# Sauvegarder l'état actuel
log "Sauvegarde de l'état actuel..."
docker-compose -f docker-compose-dev.yml ps > rebuild-dev-backup-$(date +%Y%m%d-%H%M%S).log 2>/dev/null || true

# Arrêter le service spécifique
log "Arrêt du service $SERVICE..."
docker-compose -f docker-compose-dev.yml stop $SERVICE

# Rebuild avec cache intelligent
log "Rebuild du service $SERVICE..."
docker-compose -f docker-compose-dev.yml build $SERVICE

# Redémarrer le service
log "Redémarrage du service $SERVICE..."
docker-compose -f docker-compose-dev.yml up -d $SERVICE

# Attendre le démarrage
log "Attente du démarrage..."
sleep 15

# Vérifier l'état
log "État du service:"
docker-compose -f docker-compose-dev.yml ps $SERVICE

# Test de santé
log "Test de santé..."
if curl -f -s http://localhost:8001/health/ > /dev/null 2>&1; then
    log "✅ Service $SERVICE fonctionnel après rebuild (DEV)"
else
    warn "⚠️ Service $SERVICE ne répond pas immédiatement"
    log "Vérifiez les logs: docker-compose -f docker-compose-dev.yml logs $SERVICE"
fi

log "🎉 Rebuild DEV terminé!"


#!/bin/bash

# Script de rebuild rapide pour modifications de code
# Usage: ./quick-rebuild.sh [service-name]

set -e

SERVICE=${1:-rag-api}

# Couleurs
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[REBUILD]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log "🚀 Rebuild rapide pour $SERVICE"

# Vérifier que docker-compose.yml existe
if [ ! -f "docker-compose.yml" ]; then
    error "docker-compose.yml non trouvé"
    exit 1
fi

# Sauvegarder l'état actuel
log "Sauvegarde de l'état actuel..."
docker-compose ps > rebuild-backup-$(date +%Y%m%d-%H%M%S).log 2>/dev/null || true

# Arrêter le service spécifique
log "Arrêt du service $SERVICE..."
docker-compose stop $SERVICE

# Rebuild avec cache intelligent
log "Rebuild du service $SERVICE..."
docker-compose build $SERVICE

# Redémarrer le service
log "Redémarrage du service $SERVICE..."
docker-compose up -d $SERVICE

# Attendre le démarrage
log "Attente du démarrage..."
sleep 15

# Vérifier l'état
log "État du service:"
docker-compose ps $SERVICE

# Test de santé
log "Test de santé..."
if curl -f -s http://localhost:8000/health/ > /dev/null 2>&1; then
    log "✅ Service $SERVICE fonctionnel après rebuild"
else
    warn "⚠️ Service $SERVICE ne répond pas immédiatement"
    log "Vérifiez les logs: docker-compose logs $SERVICE"
fi

log "🎉 Rebuild terminé!" 
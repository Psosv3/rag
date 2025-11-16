#!/bin/bash

# Script pour arrêter l'environnement de développement
# Usage: ./dev-stop.sh

set -e

# Couleurs
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[DEV-STOP]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log "🛑 Arrêt de l'environnement de développement..."

# Vérifier que docker-compose-dev.yml existe
if [ ! -f "docker-compose-dev.yml" ]; then
    error "docker-compose-dev.yml non trouvé"
    exit 1
fi

# Arrêter les services
log "Arrêt des conteneurs..."
docker-compose -f docker-compose-dev.yml down

log "✅ Environnement de développement arrêté avec succès!"
log ""
log "Pour redémarrer: ./dev-start.sh ou docker-compose -f docker-compose-dev.yml up -d"


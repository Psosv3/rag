#!/bin/bash

# Script pour démarrer l'environnement de développement
# Usage: ./dev-start.sh

set -e

# Couleurs
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[DEV-START]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log "🚀 Démarrage de l'environnement de développement..."

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
    log "  # puis éditez .env.dev avec vos valeurs"
    error "Fichier .env.dev requis pour démarrer l'environnement dev"
    exit 1
fi

# Créer les répertoires nécessaires s'ils n'existent pas
log "Création des répertoires nécessaires..."
mkdir -p data-dev logs-dev

# Démarrer les services
log "Démarrage des conteneurs..."
docker-compose -f docker-compose-dev.yml up -d

# Attendre le démarrage
log "Attente du démarrage des services..."
sleep 10

# Afficher l'état
log "État des services:"
docker-compose -f docker-compose-dev.yml ps

# Test de santé
log "Test de santé de l'API..."
sleep 5
if curl -f -s http://localhost:8001/health/ > /dev/null 2>&1; then
    log "✅ Environnement de développement démarré avec succès!"
    log "API disponible sur: http://localhost:8001"
    log "Documentation: http://localhost:8001/docs"
else
    warn "⚠️ L'API ne répond pas encore, cela peut prendre quelques secondes..."
    log "Vérifiez les logs avec: docker-compose -f docker-compose-dev.yml logs -f"
fi

log ""
log "Commandes utiles:"
log "  - Voir les logs: docker-compose -f docker-compose-dev.yml logs -f"
log "  - Arrêter: ./dev-stop.sh ou docker-compose -f docker-compose-dev.yml down"
log "  - Rebuild: ./quick-rebuild-dev.sh"


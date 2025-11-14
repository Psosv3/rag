#!/bin/bash

# Script de déploiement RAG API avec Traefik
# Usage: ./deploy-traefik.sh

set -e

# Couleurs
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log "🚀 Déploiement RAG API avec Traefik"

# Vérifier que Traefik tourne
if ! docker ps | grep -q traefik; then
    error "Traefik ne semble pas tourner. Vérifiez votre configuration Traefik."
    exit 1
fi

# Vérifier le réseau Traefik
if ! docker network ls | grep -q traefik; then
    warn "Réseau 'traefik' non trouvé. Tentative de création..."
    docker network create traefik || {
        warn "Le réseau existe peut-être sous un autre nom. Vérifiez avec: docker network ls"
    }
fi

# Arrêter l'ancienne configuration
log "Arrêt des anciens conteneurs..."
docker-compose down 2>/dev/null || true

# Démarrer avec la configuration Traefik
log "Démarrage avec Traefik..."
docker-compose -f docker-compose-traefik.yml up --build -d

# Attendre le démarrage
log "Attente du démarrage..."
sleep 30

# Vérifier l'état
log "État des conteneurs:"
docker-compose -f docker-compose-traefik.yml ps

# Test de l'API
log "Test de l'API..."
if curl -f -s http://localhost:8000/health/ > /dev/null 2>&1; then
    log "✅ API locale accessible"
else
    error "❌ API locale inaccessible"
    docker-compose -f docker-compose-traefik.yml logs
    exit 1
fi

# Test du domaine (si DNS configuré)
log "Test du domaine public..."
if curl -f -s https://api-rag.onexus.tech/health/ > /dev/null 2>&1; then
    log "✅ API publique accessible via Traefik"
elif curl -f -s http://api-rag.onexus.tech/health/ > /dev/null 2>&1; then
    warn "⚠️ API accessible en HTTP mais pas HTTPS (certificat en cours?)"
else
    warn "⚠️ API non accessible publiquement (DNS ou Traefik config?)"
fi

log "🎉 Déploiement terminé!"
log ""
log "URLs d'accès:"
log "- API publique: https://api-rag.onexus.tech/"
log "- Health check: https://api-rag.onexus.tech/health/"
log "- API locale: http://localhost:8000/"
log ""
log "Vérification Traefik:"
log "- Dashboard Traefik: http://votre-ip:8080 (si activé)"
log "- Logs Traefik: docker logs traefik" 
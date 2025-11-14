#!/bin/bash

# Script de déploiement automatique RAG API
# Usage: ./git-deploy.sh [branch-name]
# Par défaut déploie la branche 'main'

set -e

# Configuration
BRANCH=${1:-main}
BACKUP_DIR="./backups"
PROJECT_NAME="rag-api"

# Couleurs pour les messages
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Fonctions utilitaires
log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

info() {
    echo -e "${BLUE}[DEPLOY]${NC} $1"
}

# Fonction pour vérifier les prérequis
check_prerequisites() {
    if [ ! -f "docker-compose.yml" ]; then
        error "docker-compose.yml non trouvé. Assurez-vous d'être dans le bon répertoire."
        exit 1
    fi

    if [ ! -f ".env" ]; then
        error "Fichier .env non trouvé. Copiez env.template vers .env et configurez-le."
        exit 1
    fi

    if ! command -v docker &> /dev/null; then
        error "Docker n'est pas installé ou n'est pas dans le PATH"
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null; then
        error "Docker Compose n'est pas installé ou n'est pas dans le PATH"
        exit 1
    fi
}

# Fonction de sauvegarde avant déploiement
backup_current_state() {
    info "Sauvegarde de l'état actuel..."
    
    mkdir -p $BACKUP_DIR
    
    # Sauvegarder les logs des conteneurs
    if docker-compose ps | grep -q "Up"; then
        docker-compose logs > "$BACKUP_DIR/logs-pre-deploy-$(date +%Y%m%d-%H%M%S).log" 2>/dev/null || true
        docker-compose ps > "$BACKUP_DIR/containers-state-$(date +%Y%m%d-%H%M%S).log" 2>/dev/null || true
    fi
    
    log "✅ Sauvegarde terminée"
}

# Fonction pour vérifier l'état Git
check_git_status() {
    info "Vérification de l'état Git..."
    
    # Vérifier si on est dans un repo Git
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        error "Pas dans un repository Git. Initialisez d'abord avec 'git init' et configurez le remote."
        exit 1
    fi
    
    # Vérifier si des changements locaux non committés existent
    if ! git diff-index --quiet HEAD -- 2>/dev/null; then
        warn "Des changements locaux non committés détectés:"
        git status --porcelain
        echo ""
        read -p "Voulez-vous continuer malgré tout ? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            error "Déploiement annulé. Committez ou stashez vos changements d'abord."
            exit 1
        fi
    fi
    
    log "✅ État Git vérifié"
}

# Fonction de déploiement
deploy() {
    info "Récupération des modifications depuis la branche '$BRANCH'..."
    
    # Fetch et pull
    git fetch origin
    git checkout $BRANCH
    git pull origin $BRANCH
    
    log "✅ Code mis à jour"
    
    info "Arrêt des conteneurs existants..."
    docker-compose down --remove-orphans
    
    log "✅ Conteneurs arrêtés"
    
    info "Construction et démarrage des nouveaux conteneurs..."
    docker-compose up --build -d
    
    log "✅ Conteneurs démarrés"
}

# Fonction de vérification post-déploiement
verify_deployment() {
    info "Vérification du déploiement..."
    
    # Attendre que les services soient prêts
    sleep 15
    
    # Vérifier l'état des conteneurs
    echo "État des conteneurs :"
    docker-compose ps
    
    # Test de santé de l'API
    local max_attempts=5
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        info "Test de l'API (tentative $attempt/$max_attempts)..."
        
        if curl -f -s http://localhost:8000/health/ > /dev/null 2>&1; then
            log "✅ API fonctionnelle !"
            break
        else
            if [ $attempt -eq $max_attempts ]; then
                warn "❌ L'API ne répond pas après $max_attempts tentatives"
                warn "Vérifiez les logs avec: docker-compose logs -f"
                return 1
            fi
            sleep 10
            ((attempt++))
        fi
    done
    
    # Afficher les logs récents
    echo ""
    info "Logs récents (dernières 10 lignes) :"
    docker-compose logs --tail=10
    
    return 0
}

# Fonction de rollback en cas d'échec
rollback() {
    error "Échec du déploiement. Tentative de rollback..."
    
    # Revenir à la version précédente
    git checkout HEAD~1 2>/dev/null || true
    
    # Redémarrer avec l'ancienne version
    docker-compose down
    docker-compose up --build -d
    
    warn "Rollback effectué. Vérifiez l'état du système."
}

# Fonction de nettoyage
cleanup() {
    info "Nettoyage des ressources inutilisées..."
    
    # Nettoyer les images Docker orphelines
    docker image prune -f
    docker volume prune -f
    
    # Nettoyer les anciennes sauvegardes (garder les 10 plus récentes)
    if [ -d "$BACKUP_DIR" ]; then
        cd $BACKUP_DIR
        ls -t *.log 2>/dev/null | tail -n +11 | xargs -r rm -f
        cd - > /dev/null
    fi
    
    log "✅ Nettoyage terminé"
}

# Script principal
main() {
    echo "🚀 Déploiement automatique RAG API"
    echo "=================================="
    echo "Branche: $BRANCH"
    echo "Timestamp: $(date)"
    echo ""
    
    # Vérifications préliminaires
    check_prerequisites
    check_git_status
    
    # Sauvegarde
    backup_current_state
    
    # Déploiement
    if deploy; then
        if verify_deployment; then
            cleanup
            echo ""
            log "🎉 Déploiement réussi !"
            echo ""
            log "URLs d'accès :"
            log "- API: https://api-rag.onexus.tech/"
            log "- Health check: https://api-rag.onexus.tech/health/"
            log "- Documentation: https://api-rag.onexus.tech/docs"
            echo ""
            log "Commandes utiles :"
            log "- Logs: docker-compose logs -f"
            log "- Status: docker-compose ps"
            log "- Monitoring: ./monitor.sh"
            log "- Sauvegarde: ./backup.sh"
        else
            rollback
            exit 1
        fi
    else
        rollback
        exit 1
    fi
}

# Gestion des signaux (Ctrl+C)
trap 'error "Déploiement interrompu par l utilisateur"; exit 1' INT TERM

# Lancement du script principal
main "$@" 
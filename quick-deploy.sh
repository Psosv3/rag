#!/bin/bash

# Script de déploiement rapide depuis la machine locale
# Usage: ./quick-deploy.sh "Message de commit" [branch]
# Automatise: git add, commit, push

set -e

# Configuration
COMMIT_MESSAGE="${1:-Update: automatic deployment $(date '+%Y-%m-%d %H:%M:%S')}"
BRANCH="${2:-main}"
VPS_HOST="${VPS_HOST:-api-rag.onexus.tech}"
VPS_USER="${VPS_USER:-root}"
VPS_PROJECT_DIR="${VPS_PROJECT_DIR:-/opt/rag-project}"

# Couleurs pour les messages
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Fonctions utilitaires
log() {
    echo -e "${GREEN}[LOCAL]${NC} $1"
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
    # Vérifier qu'on est dans un repo Git
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        error "Pas dans un repository Git"
        exit 1
    fi

    # Vérifier la configuration Git
    if ! git config user.name > /dev/null 2>&1; then
        error "Configuration Git manquante. Exécutez: git config --global user.name 'Votre Nom'"
        exit 1
    fi

    if ! git config user.email > /dev/null 2>&1; then
        error "Configuration Git manquante. Exécutez: git config --global user.email 'votre-email@domain.com'"
        exit 1
    fi

    # Vérifier qu'on a un remote configuré
    if ! git remote get-url origin > /dev/null 2>&1; then
        error "Pas de remote 'origin' configuré. Ajoutez-le avec: git remote add origin <URL>"
        exit 1
    fi
}

# Fonction pour afficher l'état du repository
show_git_status() {
    echo ""
    info "État actuel du repository :"
    echo "Repository: $(git remote get-url origin 2>/dev/null || echo 'N/A')"
    echo "Branche: $(git branch --show-current)"
    echo "Dernier commit: $(git log -1 --oneline 2>/dev/null || echo 'Aucun commit')"
    echo ""
    
    # Afficher les changements
    if ! git diff-index --quiet HEAD -- 2>/dev/null; then
        warn "Fichiers modifiés détectés :"
        git status --porcelain | head -10
        if [ $(git status --porcelain | wc -l) -gt 10 ]; then
            echo "... et $(( $(git status --porcelain | wc -l) - 10 )) autres fichiers"
        fi
        echo ""
    else
        log "Aucun changement détecté"
    fi
}

# Fonction de validation avant commit
validate_before_commit() {
    # Vérifier si des fichiers sensibles sont dans le staging
    if git diff --cached --name-only | grep -E '\.(env|key|pem|p12|pfx)$' > /dev/null; then
        error "ATTENTION: Des fichiers sensibles sont sur le point d'être committés :"
        git diff --cached --name-only | grep -E '\.(env|key|pem|p12|pfx)$'
        echo ""
        read -p "Voulez-vous vraiment continuer ? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            error "Déploiement annulé pour des raisons de sécurité"
            exit 1
        fi
    fi

    # Vérifier la taille des fichiers
    large_files=$(git diff --cached --name-only | xargs -I{} sh -c 'if [ -f "{}" ] && [ $(stat -f%z "{}" 2>/dev/null || stat -c%s "{}" 2>/dev/null || echo 0) -gt 10485760 ]; then echo "{}"; fi' 2>/dev/null || true)
    if [ -n "$large_files" ]; then
        warn "Fichiers volumineux détectés (>10MB) :"
        echo "$large_files"
        echo ""
        read -p "Voulez-vous continuer ? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            error "Déploiement annulé"
            exit 1
        fi
    fi
}

# Fonction de déploiement local
deploy_local() {
    info "Préparation du déploiement local..."

    # Ajouter tous les fichiers modifiés
    log "Ajout des fichiers modifiés..."
    git add .

    # Validation avant commit
    validate_before_commit

    # Commit
    log "Création du commit: \"$COMMIT_MESSAGE\""
    git commit -m "$COMMIT_MESSAGE" || {
        warn "Aucun changement à committer"
        return 0
    }

    # Push
    log "Push vers la branche '$BRANCH'..."
    git push origin $BRANCH

    log "✅ Code poussé avec succès !"
}

# Fonction de déploiement sur VPS (optionnel)
deploy_vps() {
    if [ -z "$DEPLOY_TO_VPS" ]; then
        return 0
    fi

    info "Déploiement automatique sur le VPS..."
    
    # Vérifier la connexion SSH
    if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$VPS_USER@$VPS_HOST" echo "SSH OK" > /dev/null 2>&1; then
        warn "Impossible de se connecter au VPS $VPS_HOST"
        warn "Le code a été poussé mais le déploiement VPS doit être fait manuellement"
        warn "Connectez-vous au VPS et exécutez: cd $VPS_PROJECT_DIR && ./git-deploy.sh"
        return 0
    fi

    # Exécuter le déploiement sur le VPS
    log "Exécution du déploiement sur $VPS_HOST..."
    ssh "$VPS_USER@$VPS_HOST" "cd $VPS_PROJECT_DIR && ./git-deploy.sh $BRANCH" || {
        error "Échec du déploiement sur le VPS"
        warn "Le code a été poussé mais vérifiez manuellement le VPS"
        return 1
    }

    log "✅ Déploiement VPS terminé !"
}

# Fonction principale
main() {
    echo "🚀 Déploiement rapide RAG API"
    echo "============================"
    echo "Message: $COMMIT_MESSAGE"
    echo "Branche: $BRANCH"
    echo "Timestamp: $(date)"
    echo ""

    # Vérifications
    check_prerequisites
    show_git_status

    # Confirmation
    read -p "Voulez-vous continuer avec le déploiement ? (Y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        warn "Déploiement annulé par l'utilisateur"
        exit 0
    fi

    # Déploiement local
    deploy_local

    # Déploiement VPS (si configuré)
    deploy_vps

    echo ""
    log "🎉 Déploiement terminé !"
    echo ""
    log "Prochaines étapes :"
    log "1. Vérifiez que le code est visible sur votre repository Git"
    if [ -z "$DEPLOY_TO_VPS" ]; then
        log "2. Connectez-vous au VPS et exécutez: cd $VPS_PROJECT_DIR && ./git-deploy.sh"
    else
        log "2. Vérifiez l'état du VPS: https://$VPS_HOST/health/"
    fi
    log "3. Testez votre API: https://$VPS_HOST/"
    echo ""
}

# Affichage de l'aide
show_help() {
    echo "Usage: $0 [MESSAGE] [BRANCH]"
    echo ""
    echo "Options:"
    echo "  MESSAGE   Message de commit (optionnel)"
    echo "  BRANCH    Branche de destination (défaut: main)"
    echo ""
    echo "Variables d'environnement:"
    echo "  VPS_HOST        Adresse du VPS (défaut: api-rag.onexus.tech)"
    echo "  VPS_USER        Utilisateur SSH (défaut: root)"
    echo "  VPS_PROJECT_DIR Répertoire du projet sur le VPS (défaut: /opt/rag-project)"
    echo "  DEPLOY_TO_VPS   Si défini, déploie automatiquement sur le VPS via SSH"
    echo ""
    echo "Exemples:"
    echo "  $0                                    # Déploiement avec message automatique"
    echo "  $0 \"Fix bug in authentication\"       # Déploiement avec message personnalisé"
    echo "  $0 \"New feature\" develop            # Déploiement sur la branche develop"
    echo "  DEPLOY_TO_VPS=1 $0 \"Auto deploy\"    # Déploiement automatique sur VPS"
    echo ""
}

# Gestion des arguments
case "${1:-}" in
    -h|--help)
        show_help
        exit 0
        ;;
    *)
        main "$@"
        ;;
esac 
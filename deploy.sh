#!/bin/bash

# Script de déploiement pour RAG API sur VPS Debian
# Usage: ./deploy.sh

set -e

echo "🚀 Début du déploiement de RAG API..."

# Couleurs pour les messages
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Fonction pour afficher les messages
log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Vérifier si Docker est installé
if ! command -v docker &> /dev/null; then
    error "Docker n'est pas installé. Installation en cours..."
    
    # Installation de Docker
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    
    echo \
      "deb [arch=\"$(dpkg --print-architecture)\" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
      \"$(. /etc/os-release && echo \"$VERSION_CODENAME\")\" stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    
    # Ajouter l'utilisateur au groupe docker
    sudo usermod -aG docker $USER
    
    log "Docker installé avec succès"
fi

# Vérifier si Docker Compose est installé
if ! command -v docker-compose &> /dev/null; then
    error "Docker Compose n'est pas installé. Installation en cours..."
    sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.2/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    log "Docker Compose installé avec succès"
fi

# Créer les dossiers nécessaires
log "Création des dossiers nécessaires..."
mkdir -p logs/nginx
mkdir -p ssl

# Arrêter les conteneurs existants
log "Arrêt des conteneurs existants..."
docker-compose down || true

# Construire et démarrer les conteneurs
log "Construction et démarrage des conteneurs..."
docker-compose up --build -d

# Attendre que les services soient prêts
log "Attente du démarrage des services..."
sleep 10

# Vérifier l'état des conteneurs
log "Vérification de l'état des conteneurs..."
docker-compose ps

# Vérifier si l'API répond
log "Test de l'API..."
if curl -f http://localhost:8000/ &> /dev/null; then
    log "✅ API accessible localement"
else
    warn "❌ API non accessible localement"
fi

# Afficher les logs des conteneurs
log "Affichage des logs récents..."
docker-compose logs --tail=50

echo ""
log "🎉 Déploiement terminé !"
echo ""
log "Pour utiliser l'API :"
log "- Endpoint principal: https://api-rag.onexus.tech/"
log "- Upload de fichier: POST https://api-rag.onexus.tech/upload/"
log "- Construction d'index: POST https://api-rag.onexus.tech/build_index/"
log "- Poser une question: POST https://api-rag.onexus.tech/ask/"
echo ""
log "Commandes utiles :"
log "- Voir les logs: docker-compose logs -f"
log "- Redémarrer: docker-compose restart"
log "- Arrêter: docker-compose down"
log "- Reconstruire: docker-compose up --build -d"
echo ""
warn "⚠️  N'oubliez pas de :"
warn "1. Configurer votre DNS pour pointer api-rag.onexus.tech vers ce serveur"
warn "2. Installer un certificat SSL (voir instructions dans DEPLOYMENT.md)"
warn "3. Configurer votre pare-feu pour ouvrir les ports 80 et 443" 
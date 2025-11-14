#!/bin/bash

# Script d'installation initiale pour VPS Debian/Ubuntu
# Installation automatique de Docker, Docker Compose et préparation de l'environnement
# Usage: curl -fsSL https://raw.githubusercontent.com/votre-repo/RAG_ONEXUS/main/vps-setup.sh | bash

set -e

# Couleurs pour les messages
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

info() {
    echo -e "${BLUE}[SETUP]${NC} $1"
}

echo "🚀 Installation automatique - RAG API VPS Setup"
echo "=============================================="
echo ""

# Vérifier si on est sur Ubuntu/Debian
if ! command -v apt &> /dev/null; then
    error "Ce script ne fonctionne que sur Ubuntu/Debian"
    exit 1
fi

# Variables
PROJECT_DIR="/opt/rag-project"
USER_NAME=$(whoami)

log "Démarrage de l'installation pour l'utilisateur: $USER_NAME"

# Mise à jour du système
info "Mise à jour du système..."
sudo apt update && sudo apt upgrade -y

# Installation des paquets de base
info "Installation des paquets de base..."
sudo apt install -y \
    curl \
    wget \
    git \
    nano \
    htop \
    unzip \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release \
    ufw

# Installation de Docker
if ! command -v docker &> /dev/null; then
    info "Installation de Docker..."
    
    # Ajouter la clé GPG officielle de Docker
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    
    # Ajouter le repository Docker
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    # Installer Docker
    sudo apt update
    sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    
    # Ajouter l'utilisateur au groupe docker
    sudo usermod -aG docker $USER_NAME
    
    log "✅ Docker installé avec succès"
else
    log "✅ Docker déjà installé"
fi

# Installation de Docker Compose (version standalone)
if ! command -v docker-compose &> /dev/null; then
    info "Installation de Docker Compose..."
    
    # Télécharger la dernière version de Docker Compose
    DOCKER_COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep 'tag_name' | cut -d'"' -f4)
    sudo curl -L "https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    
    log "✅ Docker Compose installé avec succès"
else
    log "✅ Docker Compose déjà installé"
fi

# Installation de Certbot pour SSL
info "Installation de Certbot..."
sudo apt install -y certbot
log "✅ Certbot installé"

# Création du répertoire du projet
info "Configuration du répertoire du projet..."
sudo mkdir -p $PROJECT_DIR
sudo chown -R $USER_NAME:$USER_NAME $PROJECT_DIR
log "✅ Répertoire $PROJECT_DIR créé et configuré"

# Configuration du pare-feu UFW
info "Configuration du pare-feu..."
sudo ufw --force enable
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 8080/tcp   # HTTP externe pour debug
sudo ufw allow 8443/tcp   # HTTPS externe pour debug
log "✅ Pare-feu configuré"

# Optimisation système pour Docker
info "Optimisation système..."

# Augmenter les limites de fichiers ouverts
echo "* soft nofile 65536" | sudo tee -a /etc/security/limits.conf
echo "* hard nofile 65536" | sudo tee -a /etc/security/limits.conf

# Configuration swap (si pas de swap)
if ! swapon --show | grep -q .; then
    warn "Aucun swap détecté. Création d'un fichier swap de 2GB..."
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    log "✅ Swap configuré"
fi

# Créer les dossiers nécessaires pour le projet
cd $PROJECT_DIR
mkdir -p logs/nginx
mkdir -p ssl
mkdir -p data
mkdir -p backups

# Configuration Git globale (si pas encore configurée)
if ! git config --global user.name &> /dev/null; then
    warn "Configuration Git requise. Veuillez configurer après l'installation:"
    warn "git config --global user.name 'Votre Nom'"
    warn "git config --global user.email 'votre-email@domain.com'"
fi

# Créer un script de déploiement rapide
cat > $PROJECT_DIR/git-deploy.sh << 'EOF'
#!/bin/bash

# Script de déploiement automatique
# Usage: ./git-deploy.sh

set -e

log() {
    echo -e "\033[0;32m[INFO]\033[0m $1"
}

error() {
    echo -e "\033[0;31m[ERROR]\033[0m $1"
}

log "🚀 Début du déploiement..."

# Vérifier qu'on est dans le bon répertoire
if [ ! -f "docker-compose.yml" ]; then
    error "docker-compose.yml non trouvé. Assurez-vous d'être dans le bon répertoire."
    exit 1
fi

# Sauvegarder les conteneurs actuels
log "Sauvegarde de l'état actuel..."
docker-compose ps > deployment-backup-$(date +%Y%m%d-%H%M%S).log || true

# Arrêter les conteneurs
log "Arrêt des conteneurs..."
docker-compose down

# Récupérer les dernières modifications
log "Récupération des modifications Git..."
git pull origin main

# Reconstruire et démarrer
log "Reconstruction et démarrage..."
docker-compose up --build -d

# Attendre que les services soient prêts
log "Attente du démarrage des services..."
sleep 15

# Vérifier l'état
log "Vérification de l'état des conteneurs..."
docker-compose ps

# Test de santé
log "Test de l'API..."
if curl -f http://localhost:8000/health/ &> /dev/null; then
    log "✅ API fonctionnelle"
else
    error "❌ Problème avec l'API - vérifiez les logs"
    docker-compose logs --tail=20
fi

log "🎉 Déploiement terminé !"
EOF

chmod +x $PROJECT_DIR/git-deploy.sh

# Créer un script de monitoring
cat > $PROJECT_DIR/monitor.sh << 'EOF'
#!/bin/bash

# Script de monitoring simple
echo "=== STATUS DES CONTENEURS ==="
docker-compose ps

echo ""
echo "=== UTILISATION DES RESSOURCES ==="
docker stats --no-stream

echo ""
echo "=== ESPACE DISQUE ==="
df -h

echo ""
echo "=== DERNIERS LOGS (20 lignes) ==="
docker-compose logs --tail=20
EOF

chmod +x $PROJECT_DIR/monitor.sh

# Créer un script de sauvegarde
cat > $PROJECT_DIR/backup.sh << 'EOF'
#!/bin/bash

# Script de sauvegarde
BACKUP_DIR="/opt/rag-project/backups"
DATE=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="backup-$DATE.tar.gz"

echo "Création de la sauvegarde: $BACKUP_FILE"

tar -czf "$BACKUP_DIR/$BACKUP_FILE" \
    --exclude="backups" \
    --exclude="logs" \
    --exclude=".git" \
    data/ ssl/ .env docker-compose.yml

echo "✅ Sauvegarde créée: $BACKUP_DIR/$BACKUP_FILE"
ls -lh "$BACKUP_DIR/$BACKUP_FILE"

# Nettoyer les anciennes sauvegardes (garder les 10 plus récentes)
cd $BACKUP_DIR
ls -t backup-*.tar.gz | tail -n +11 | xargs -r rm

echo "🧹 Anciennes sauvegardes nettoyées"
EOF

chmod +x $PROJECT_DIR/backup.sh

# Instructions finales
echo ""
echo "🎉 Installation terminée avec succès !"
echo "======================================"
echo ""
log "Prochaines étapes :"
echo "1. Redémarrez votre session SSH ou exécutez: newgrp docker"
echo "2. Allez dans le répertoire projet: cd $PROJECT_DIR"
echo "3. Clonez votre repository: git clone [URL] ."
echo "4. Configurez les variables d'environnement: cp env.template .env && nano .env"
echo "5. Déployez: ./git-deploy.sh"
echo ""
log "Scripts utiles créés :"
echo "- ./git-deploy.sh   : Déploiement automatique"
echo "- ./monitor.sh      : Monitoring des conteneurs"
echo "- ./backup.sh       : Sauvegarde des données"
echo ""
warn "⚠️  IMPORTANT :"
warn "1. Configurez Git: git config --global user.name 'Nom' && git config --global user.email 'email'"
warn "2. Configurez le DNS pour pointer api-rag.onexus.tech vers ce serveur"
warn "3. Générez les certificats SSL avec Certbot"
echo ""
log "Pour tester l'installation :"
log "docker --version && docker-compose --version"
echo "" 
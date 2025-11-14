#!/bin/bash

# Script de configuration SSL automatique avec Certbot
# Usage: ./ssl-setup.sh [email] [domain]

set -e

# Configuration par défaut
DEFAULT_EMAIL="${SSL_EMAIL:-}"
DEFAULT_DOMAIN="${DOMAIN:-api-rag.onexus.tech}"
EMAIL="${1:-$DEFAULT_EMAIL}"
DOMAIN="${2:-$DEFAULT_DOMAIN}"

# Couleurs pour les messages
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Fonctions utilitaires
log() {
    echo -e "${GREEN}[SSL]${NC} $1"
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

# Fonction pour vérifier les prérequis
check_prerequisites() {
    # Vérifier qu'on est root ou qu'on a sudo
    if [ "$EUID" -ne 0 ] && ! sudo -n true 2>/dev/null; then
        error "Ce script nécessite des privilèges root ou sudo"
        exit 1
    fi

    # Vérifier l'email
    if [ -z "$EMAIL" ]; then
        echo "Email requis pour Certbot."
        read -p "Entrez votre email: " EMAIL
        if [ -z "$EMAIL" ]; then
            error "Email obligatoire"
            exit 1
        fi
    fi

    # Vérifier le domaine
    if [ -z "$DOMAIN" ]; then
        error "Domaine obligatoire"
        exit 1
    fi

    # Vérifier que Certbot est installé
    if ! command -v certbot &> /dev/null; then
        warn "Certbot n'est pas installé. Installation..."
        sudo apt update
        sudo apt install -y certbot
        log "✅ Certbot installé"
    fi

    # Vérifier que docker-compose.yml existe
    if [ ! -f "docker-compose.yml" ]; then
        error "docker-compose.yml non trouvé. Exécutez ce script depuis le répertoire du projet."
        exit 1
    fi
}

# Fonction pour vérifier la résolution DNS
check_dns_resolution() {
    info "Vérification de la résolution DNS pour $DOMAIN..."
    
    # Obtenir l'IP publique du serveur
    SERVER_IP=$(curl -s ifconfig.me || curl -s ipecho.net/plain || curl -s icanhazip.com)
    
    # Résoudre le domaine
    RESOLVED_IP=$(dig +short $DOMAIN | tail -n1)
    
    if [ -z "$RESOLVED_IP" ]; then
        error "Le domaine $DOMAIN ne résout vers aucune IP"
        warn "Configurez votre DNS avant de continuer"
        exit 1
    fi
    
    if [ "$SERVER_IP" != "$RESOLVED_IP" ]; then
        warn "⚠️  Le domaine $DOMAIN résout vers $RESOLVED_IP mais ce serveur a l'IP $SERVER_IP"
        warn "Assurez-vous que le DNS est correctement configuré"
        echo ""
        read -p "Voulez-vous continuer malgré tout ? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            error "Configuration SSL annulée"
            exit 1
        fi
    else
        log "✅ DNS correctement configuré ($DOMAIN → $SERVER_IP)"
    fi
}

# Fonction pour arrêter les services web
stop_web_services() {
    info "Arrêt temporaire des services web..."
    
    # Arrêter nginx container si il tourne
    if docker-compose ps nginx 2>/dev/null | grep -q "Up"; then
        docker-compose stop nginx
        log "✅ Container nginx arrêté"
    fi
    
    # Vérifier qu'aucun service n'occupe le port 80
    if sudo lsof -i :80 &> /dev/null; then
        warn "Le port 80 est encore occupé :"
        sudo lsof -i :80
        echo ""
        read -p "Voulez-vous forcer l'arrêt des services sur le port 80 ? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            sudo lsof -ti :80 | sudo xargs kill -9 2>/dev/null || true
            sleep 2
        fi
    fi
}

# Fonction pour générer le certificat SSL
generate_certificate() {
    info "Génération du certificat SSL pour $DOMAIN..."
    
    # Supprimer l'ancien certificat si il existe
    if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
        warn "Certificat existant détecté. Renouvellement..."
        sudo certbot renew --cert-name $DOMAIN --force-renewal
    else
        log "Génération d'un nouveau certificat..."
        sudo certbot certonly \
            --standalone \
            --preferred-challenges http \
            --email $EMAIL \
            --agree-tos \
            --no-eff-email \
            --non-interactive \
            -d $DOMAIN
    fi
    
    # Vérifier que le certificat a été créé
    if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
        error "Échec de la génération du certificat SSL"
        exit 1
    fi
    
    log "✅ Certificat SSL généré avec succès"
}

# Fonction pour copier les certificats
copy_certificates() {
    info "Copie des certificats vers le projet..."
    
    # Créer le dossier ssl
    mkdir -p ssl
    
    # Copier les certificats
    sudo cp /etc/letsencrypt/live/$DOMAIN/fullchain.pem ssl/$DOMAIN.crt
    sudo cp /etc/letsencrypt/live/$DOMAIN/privkey.pem ssl/$DOMAIN.key
    
    # Ajuster les permissions
    sudo chown -R $USER:$USER ssl/
    chmod 600 ssl/$DOMAIN.key
    chmod 644 ssl/$DOMAIN.crt
    
    log "✅ Certificats copiés dans ./ssl/"
}

# Fonction pour configurer le renouvellement automatique
setup_auto_renewal() {
    info "Configuration du renouvellement automatique..."
    
    # Script de post-renouvellement
    cat > /tmp/certbot-renew-hook.sh << EOF
#!/bin/bash
# Script exécuté après renouvellement Certbot

DOMAIN="$DOMAIN"
PROJECT_DIR="$(pwd)"

# Copier les nouveaux certificats
cp /etc/letsencrypt/live/\$DOMAIN/fullchain.pem \$PROJECT_DIR/ssl/\$DOMAIN.crt
cp /etc/letsencrypt/live/\$DOMAIN/privkey.pem \$PROJECT_DIR/ssl/\$DOMAIN.key

# Ajuster les permissions
chown -R $USER:$USER \$PROJECT_DIR/ssl/
chmod 600 \$PROJECT_DIR/ssl/\$DOMAIN.key
chmod 644 \$PROJECT_DIR/ssl/\$DOMAIN.crt

# Redémarrer nginx
cd \$PROJECT_DIR
docker-compose restart nginx

echo "Certificat renouvelé et nginx redémarré"
EOF

    sudo mv /tmp/certbot-renew-hook.sh /etc/letsencrypt/renewal-hooks/post/rag-api-renewal.sh
    sudo chmod +x /etc/letsencrypt/renewal-hooks/post/rag-api-renewal.sh
    
    # Ajouter une tâche cron pour le renouvellement
    CRON_JOB="0 12 * * * /usr/bin/certbot renew --quiet"
    
    # Vérifier si la tâche existe déjà
    if ! crontab -l 2>/dev/null | grep -q "certbot renew"; then
        (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
        log "✅ Tâche cron de renouvellement ajoutée"
    else
        log "✅ Tâche cron de renouvellement déjà configurée"
    fi
}

# Fonction pour redémarrer les services
restart_services() {
    info "Redémarrage des services avec SSL..."
    
    # Démarrer tous les conteneurs
    docker-compose up -d
    
    # Attendre que les services soient prêts
    sleep 10
    
    # Vérifier l'état
    docker-compose ps
    
    log "✅ Services redémarrés avec SSL"
}

# Fonction de test SSL
test_ssl() {
    info "Test de la configuration SSL..."
    
    # Test HTTP → HTTPS redirect
    if curl -I -s "http://$DOMAIN" | grep -q "301\|302"; then
        log "✅ Redirection HTTP → HTTPS fonctionnelle"
    else
        warn "❌ Redirection HTTP → HTTPS non détectée"
    fi
    
    # Test HTTPS
    local max_attempts=5
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        info "Test HTTPS (tentative $attempt/$max_attempts)..."
        
        if curl -f -s "https://$DOMAIN/health/" > /dev/null 2>&1; then
            log "✅ HTTPS fonctionnel !"
            break
        else
            if [ $attempt -eq $max_attempts ]; then
                warn "❌ HTTPS ne répond pas après $max_attempts tentatives"
                warn "Vérifiez les logs: docker-compose logs nginx"
                return 1
            fi
            sleep 5
            ((attempt++))
        fi
    done
    
    # Test du certificat
    if openssl s_client -connect $DOMAIN:443 -servername $DOMAIN < /dev/null 2>/dev/null | openssl x509 -noout -dates 2>/dev/null; then
        log "✅ Certificat SSL valide"
        echo ""
        info "Informations du certificat :"
        openssl s_client -connect $DOMAIN:443 -servername $DOMAIN < /dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates 2>/dev/null
    else
        warn "❌ Problème avec le certificat SSL"
    fi
}

# Fonction principale
main() {
    echo "🔒 Configuration SSL automatique"
    echo "==============================="
    echo "Domaine: $DOMAIN"
    echo "Email: $EMAIL"
    echo "Timestamp: $(date)"
    echo ""

    # Vérifications
    check_prerequisites
    check_dns_resolution

    # Confirmation
    read -p "Voulez-vous continuer avec la configuration SSL ? (Y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        warn "Configuration SSL annulée"
        exit 0
    fi

    # Configuration SSL
    stop_web_services
    generate_certificate
    copy_certificates
    setup_auto_renewal
    restart_services
    
    # Test
    test_ssl

    echo ""
    log "🎉 Configuration SSL terminée !"
    echo ""
    log "Votre API est maintenant accessible via :"
    log "- HTTPS: https://$DOMAIN/"
    log "- Health check: https://$DOMAIN/health/"
    log "- Documentation: https://$DOMAIN/docs"
    echo ""
    log "Informations importantes :"
    log "- Le certificat se renouvelle automatiquement"
    log "- Les certificats sont dans ./ssl/"
    log "- Logs nginx: docker-compose logs nginx"
    echo ""
}

# Affichage de l'aide
show_help() {
    echo "Usage: $0 [EMAIL] [DOMAIN]"
    echo ""
    echo "Configure automatiquement SSL avec Let's Encrypt pour votre API RAG"
    echo ""
    echo "Arguments:"
    echo "  EMAIL     Email pour Let's Encrypt (optionnel si SSL_EMAIL défini)"
    echo "  DOMAIN    Domaine à certifier (défaut: api-rag.onexus.tech)"
    echo ""
    echo "Variables d'environnement:"
    echo "  SSL_EMAIL  Email par défaut pour Certbot"
    echo "  DOMAIN     Domaine par défaut"
    echo ""
    echo "Exemples:"
    echo "  $0                                    # Utilise les valeurs par défaut"
    echo "  $0 admin@example.com                 # Email personnalisé"
    echo "  $0 admin@example.com mon-api.com     # Email et domaine personnalisés"
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
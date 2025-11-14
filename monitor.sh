#!/bin/bash

# Script de monitoring complet RAG API
# Usage: ./monitor.sh [--continuous] [--logs] [--stats]

set -e

# Configuration
REFRESH_INTERVAL=5
DOMAIN="${DOMAIN:-api-rag.onexus.tech}"

# Couleurs pour les messages
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Fonctions utilitaires
log() {
    echo -e "${GREEN}[MONITOR]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

header() {
    echo -e "${CYAN}=== $1 ===${NC}"
}

# Fonction pour effacer l'écran
clear_screen() {
    if [ "$CONTINUOUS" = "true" ]; then
        clear
    fi
}

# Fonction pour afficher l'en-tête
show_header() {
    echo "🔍 Monitoring RAG API - $(date)"
    echo "Domain: $DOMAIN"
    echo "Refresh: ${REFRESH_INTERVAL}s (en mode continu)"
    echo ""
}

# Fonction pour vérifier l'état des conteneurs
check_containers() {
    header "ÉTAT DES CONTENEURS"
    
    if ! command -v docker-compose &> /dev/null; then
        error "Docker Compose non installé"
        return 1
    fi

    if [ ! -f "docker-compose.yml" ]; then
        error "docker-compose.yml non trouvé"
        return 1
    fi

    # État des conteneurs
    docker-compose ps

    echo ""
    
    # Santé des conteneurs
    local containers=$(docker-compose ps --services)
    for container in $containers; do
        local status=$(docker-compose ps $container | tail -n +3 | awk '{print $3}')
        local health=$(docker inspect --format='{{.State.Health.Status}}' "$(docker-compose ps -q $container 2>/dev/null)" 2>/dev/null || echo "N/A")
        
        if [ "$status" = "Up" ]; then
            if [ "$health" = "healthy" ]; then
                log "✅ $container: $status ($health)"
            elif [ "$health" = "unhealthy" ]; then
                error "❌ $container: $status ($health)"
            else
                warn "⚠️  $container: $status (health: $health)"
            fi
        else
            error "❌ $container: $status"
        fi
    done
    echo ""
}

# Fonction pour vérifier les services
check_services() {
    header "TESTS DE SERVICE"
    
    # Test API local
    info "Test API local..."
    if curl -f -s http://localhost:8000/health/ > /dev/null 2>&1; then
        log "✅ API locale accessible"
    else
        error "❌ API locale inaccessible"
    fi

    # Test API via nginx local
    info "Test API via nginx local..."
    if curl -f -s http://localhost:8080/health/ > /dev/null 2>&1; then
        log "✅ API via nginx local accessible"
    else
        error "❌ API via nginx local inaccessible"
    fi

    # Test API publique (si domaine configuré)
    if [ "$DOMAIN" != "api-rag.onexus.tech" ] || ping -c 1 $DOMAIN &> /dev/null; then
        info "Test API publique HTTPS..."
        if curl -f -s https://$DOMAIN/health/ > /dev/null 2>&1; then
            log "✅ API publique HTTPS accessible"
        else
            error "❌ API publique HTTPS inaccessible"
        fi

        info "Test API publique HTTP..."
        if curl -I -s http://$DOMAIN/ | grep -q "30[12]"; then
            log "✅ Redirection HTTP → HTTPS fonctionnelle"
        else
            warn "⚠️  Redirection HTTP → HTTPS non détectée"
        fi
    else
        warn "⚠️  Domaine $DOMAIN non résolvable - skip tests publics"
    fi
    echo ""
}

# Fonction pour afficher les ressources système
show_system_resources() {
    header "RESSOURCES SYSTÈME"
    
    # CPU et mémoire
    echo "CPU et Mémoire:"
    if command -v htop &> /dev/null; then
        htop -n 1 | head -4 | tail -3
    else
        top -bn1 | head -5 | tail -2
    fi
    echo ""

    # Espace disque
    echo "Espace disque:"
    df -h | grep -E "(Filesystem|/dev/|tmpfs)" | head -5
    echo ""

    # Docker stats
    echo "Statistiques des conteneurs:"
    if docker ps --filter "name=rag" --format "table {{.Names}}\t{{.Status}}" | grep -q "rag"; then
        docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" $(docker ps --filter "name=rag" -q) 2>/dev/null || echo "Aucun conteneur rag en cours"
    else
        echo "Aucun conteneur rag en cours d'exécution"
    fi
    echo ""
}

# Fonction pour afficher les logs récents
show_recent_logs() {
    header "LOGS RÉCENTS (dernières 10 lignes)"
    
    echo "🔸 Logs API:"
    docker-compose logs --tail=5 rag-api 2>/dev/null | tail -5 || echo "Logs API non disponibles"
    echo ""
    
    echo "🔸 Logs Nginx:"
    docker-compose logs --tail=5 nginx 2>/dev/null | tail -5 || echo "Logs Nginx non disponibles"
    echo ""
}

# Fonction pour afficher les métriques de performance
show_performance_metrics() {
    header "MÉTRIQUES DE PERFORMANCE"
    
    # Test de temps de réponse
    local start_time=$(date +%s.%3N)
    if curl -f -s http://localhost:8000/health/ > /dev/null 2>&1; then
        local end_time=$(date +%s.%3N)
        local response_time=$(echo "$end_time - $start_time" | bc 2>/dev/null || echo "N/A")
        log "⚡ Temps de réponse API: ${response_time}s"
    else
        error "❌ Impossible de mesurer le temps de réponse"
    fi

    # Uptime des conteneurs
    echo ""
    echo "Uptime des conteneurs:"
    docker ps --filter "name=rag" --format "table {{.Names}}\t{{.Status}}" 2>/dev/null || echo "Aucun conteneur en cours"
    echo ""
}

# Fonction pour afficher les alertes
show_alerts() {
    header "ALERTES ET WARNINGS"
    
    local alert_count=0
    
    # Vérifier l'espace disque
    local disk_usage=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
    if [ "$disk_usage" -gt 80 ]; then
        warn "⚠️  Espace disque faible: ${disk_usage}% utilisé"
        ((alert_count++))
    fi

    # Vérifier la mémoire
    local mem_usage=$(free | grep Mem | awk '{printf "%.0f", $3/$2 * 100.0}')
    if [ "$mem_usage" -gt 80 ]; then
        warn "⚠️  Utilisation mémoire élevée: ${mem_usage}%"
        ((alert_count++))
    fi

    # Vérifier les conteneurs arrêtés
    local stopped_containers=$(docker-compose ps | grep -c "Exit\|Down" || echo "0")
    if [ "$stopped_containers" -gt 0 ]; then
        warn "⚠️  $stopped_containers conteneur(s) arrêté(s)"
        ((alert_count++))
    fi

    # Vérifier les certificats SSL
    if [ -f "ssl/$DOMAIN.crt" ]; then
        local cert_days=$(openssl x509 -in "ssl/$DOMAIN.crt" -noout -checkend 604800 2>/dev/null && echo "OK" || echo "EXPIRE")
        if [ "$cert_days" = "EXPIRE" ]; then
            warn "⚠️  Certificat SSL expire dans moins de 7 jours"
            ((alert_count++))
        fi
    fi

    if [ "$alert_count" -eq 0 ]; then
        log "✅ Aucune alerte détectée"
    else
        warn "⚠️  $alert_count alerte(s) détectée(s)"
    fi
    echo ""
}

# Fonction pour le monitoring en continu
continuous_monitoring() {
    CONTINUOUS=true
    log "Mode monitoring continu activé (Ctrl+C pour arrêter)"
    echo ""
    
    while true; do
        clear_screen
        show_header
        check_containers
        check_services
        show_system_resources
        show_alerts
        
        echo "Actualisation dans ${REFRESH_INTERVAL}s... (Ctrl+C pour arrêter)"
        sleep $REFRESH_INTERVAL
    done
}

# Fonction pour afficher seulement les logs
logs_only() {
    header "LOGS EN TEMPS RÉEL"
    docker-compose logs -f
}

# Fonction pour afficher seulement les stats
stats_only() {
    header "STATISTIQUES EN TEMPS RÉEL"
    if docker ps --filter "name=rag" -q | head -1 > /dev/null; then
        docker stats $(docker ps --filter "name=rag" -q)
    else
        error "Aucun conteneur rag en cours d'exécution"
    fi
}

# Fonction de monitoring complet (une fois)
full_monitoring() {
    show_header
    check_containers
    check_services
    show_system_resources
    show_performance_metrics
    show_alerts
    
    if [ "$SHOW_LOGS" = "true" ]; then
        show_recent_logs
    fi
}

# Fonction d'aide
show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Script de monitoring pour RAG API"
    echo ""
    echo "Options:"
    echo "  --continuous, -c    Mode monitoring continu"
    echo "  --logs, -l          Afficher les logs en temps réel"
    echo "  --stats, -s         Afficher les statistiques en temps réel"
    echo "  --include-logs      Inclure les logs récents dans le rapport"
    echo "  --help, -h          Afficher cette aide"
    echo ""
    echo "Variables d'environnement:"
    echo "  DOMAIN              Domaine à tester (défaut: api-rag.onexus.tech)"
    echo "  REFRESH_INTERVAL    Intervalle de rafraîchissement en secondes (défaut: 5)"
    echo ""
    echo "Exemples:"
    echo "  $0                  # Monitoring ponctuel"
    echo "  $0 --continuous     # Monitoring continu"
    echo "  $0 --logs           # Logs en temps réel"
    echo "  $0 --stats          # Stats en temps réel"
    echo ""
}

# Traitement des arguments
CONTINUOUS=false
SHOW_LOGS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --continuous|-c)
            continuous_monitoring
            exit 0
            ;;
        --logs|-l)
            logs_only
            exit 0
            ;;
        --stats|-s)
            stats_only
            exit 0
            ;;
        --include-logs)
            SHOW_LOGS=true
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            error "Option inconnue: $1"
            show_help
            exit 1
            ;;
    esac
done

# Monitoring par défaut
full_monitoring 
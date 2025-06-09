# Guide de Déploiement - RAG API

Ce guide vous accompagne pour déployer votre API RAG sur un VPS Debian avec le domaine `api-rag.onexus.tech`.

## 📋 Prérequis

- VPS Debian avec accès root/sudo
- Domaine `api-rag.onexus.tech` pointant vers votre VPS
- Clé API OpenAI

## 🚀 Étapes de Déploiement

### 1. Préparation du VPS

```bash
# Mise à jour du système
sudo apt update && sudo apt upgrade -y

# Installation des outils de base
sudo apt install -y curl wget git unzip
```

### 2. Transfert des fichiers

Transférez tous les fichiers de votre projet sur le VPS :

```bash
# Exemple avec scp
scp -r /path/to/your/project/ user@your-vps-ip:/home/user/rag-api/

# Ou avec git
git clone https://github.com/votre-repo/rag-api.git
cd rag-api
```

### 3. Configuration DNS

Assurez-vous que votre domaine `api-rag.onexus.tech` pointe vers l'IP de votre VPS :

```
Type: A
Nom: api-rag
Valeur: [IP_DE_VOTRE_VPS]
TTL: 3600
```

### 4. Obtention du certificat SSL

#### Option A: Let's Encrypt (Recommandé)

```bash
# Installation de Certbot
sudo apt install -y certbot

# Obtention du certificat
sudo certbot certonly --standalone -d api-rag.onexus.tech

# Copie des certificats
sudo mkdir -p ssl/
sudo cp /etc/letsencrypt/live/api-rag.onexus.tech/fullchain.pem ssl/api-rag.onexus.tech.crt
sudo cp /etc/letsencrypt/live/api-rag.onexus.tech/privkey.pem ssl/api-rag.onexus.tech.key
sudo chown -R $USER:$USER ssl/
```

#### Option B: Certificat auto-signé (Pour test)

```bash
mkdir -p ssl/
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout ssl/api-rag.onexus.tech.key \
    -out ssl/api-rag.onexus.tech.crt \
    -subj "/C=FR/ST=France/L=Paris/O=Onexus/OU=IT/CN=api-rag.onexus.tech"
```

### 5. Configuration du pare-feu

```bash
# Installation d'ufw
sudo apt install -y ufw

# Configuration des règles
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Activation du pare-feu
sudo ufw enable
```

### 6. Déploiement avec le script automatique

```bash
# Rendre le script exécutable
chmod +x deploy.sh

# Lancer le déploiement
./deploy.sh
```

### 7. Configuration du renouvellement SSL automatique

```bash
# Ajouter une tâche cron pour le renouvellement
sudo crontab -e

# Ajouter cette ligne :
0 12 * * * /usr/bin/certbot renew --quiet && /usr/local/bin/docker-compose -f /home/user/rag-api/docker-compose.yml restart nginx
```

## 🔧 Configuration Avancée

### Variables d'environnement

Créez un fichier `.env` :

```bash
# .env
OPENAI_API_KEY=your_openai_api_key_here
PYTHONPATH=/app
PYTHONUNBUFFERED=1
```

Modifiez le `docker-compose.yml` :

```yaml
rag-api:
  # ... autres configurations
  env_file:
    - .env
```

### Monitoring et Logs

```bash
# Voir les logs en temps réel
docker-compose logs -f

# Voir les logs d'un service spécifique
docker-compose logs -f rag-api
docker-compose logs -f nginx

# Monitoring de l'usage système
htop
docker stats
```

## 📊 Test de l'API

### 1. Test de base

```bash
curl https://api-rag.onexus.tech/
```

### 2. Upload d'un fichier

```bash
curl -X POST https://api-rag.onexus.tech/upload/ \
  -F "file=@/path/to/your/document.pdf"
```

### 3. Construction de l'index

```bash
curl -X POST https://api-rag.onexus.tech/build_index/ \
  -F "openai_api_key=your_api_key_here"
```

### 4. Poser une question

```bash
curl -X POST https://api-rag.onexus.tech/ask/ \
  -F "question=Quelle est la principale information du document ?" \
  -F "openai_api_key=your_api_key_here"
```

## 🛠️ Commandes de Maintenance

### Redémarrage des services

```bash
docker-compose restart
```

### Mise à jour de l'application

```bash
# Arrêter les services
docker-compose down

# Mettre à jour le code
git pull origin main

# Reconstruire et redémarrer
docker-compose up --build -d
```

### Sauvegarde des données

```bash
# Sauvegarde du dossier data
tar -czf backup-data-$(date +%Y%m%d).tar.gz data/

# Sauvegarde de la base de données vectorielle (si persistante)
docker-compose exec rag-api tar -czf /tmp/vectordb-backup.tar.gz /app/vectordb/
docker cp rag-api:/tmp/vectordb-backup.tar.gz ./
```

### Nettoyage

```bash
# Supprimer les conteneurs arrêtés
docker container prune

# Supprimer les images inutilisées
docker image prune

# Supprimer les volumes inutilisés
docker volume prune
```

## 🔍 Résolution de Problèmes

### L'API ne répond pas

```bash
# Vérifier l'état des conteneurs
docker-compose ps

# Vérifier les logs
docker-compose logs rag-api

# Redémarrer les services
docker-compose restart
```

### Erreur SSL

```bash
# Vérifier les certificats
ls -la ssl/

# Renouveler le certificat Let's Encrypt
sudo certbot renew --force-renewal
```

### Problème de mémoire

```bash
# Vérifier l'utilisation des ressources
docker stats

# Ajuster la configuration dans docker-compose.yml
services:
  rag-api:
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 1G
```

## 📈 Optimisations Production

### 1. Configuration Nginx avancée

Modifiez `nginx/api-rag.onexus.tech.conf` pour ajouter :

```nginx
# Cache des réponses statiques
location ~* \.(jpg|jpeg|png|gif|ico|css|js)$ {
    expires 1y;
    add_header Cache-Control "public, immutable";
}

# Compression Brotli (si disponible)
brotli on;
brotli_comp_level 6;
brotli_types text/plain text/css application/json application/javascript;
```

### 2. Monitoring avec Prometheus

Ajoutez au `docker-compose.yml` :

```yaml
prometheus:
  image: prom/prometheus
  ports:
    - "9090:9090"
  volumes:
    - ./prometheus.yml:/etc/prometheus/prometheus.yml
```

### 3. Limite de taux (Rate Limiting)

Configuration dans Nginx :

```nginx
# Dans nginx.conf
http {
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    
    # Dans le server block
    limit_req zone=api burst=20 nodelay;
}
```

## 📞 Support

Si vous rencontrez des problèmes :

1. Vérifiez les logs : `docker-compose logs -f`
2. Vérifiez l'état des services : `docker-compose ps`
3. Consultez la documentation FastAPI
4. Vérifiez la configuration DNS

## 🔄 Mise à Jour

Pour mettre à jour l'application :

1. `git pull origin main`
2. `docker-compose down`
3. `docker-compose up --build -d`

---

**Note**: Remplacez `your_api_key_here` par votre vraie clé API OpenAI et `your-vps-ip` par l'IP réelle de votre VPS. 
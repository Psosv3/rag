# 🚀 Guide de Déploiement RAG_ONEXUS - A à Z

Ce guide vous accompagne pour dockeriser et déployer votre application RAG_ONEXUS sur votre VPS `api-rag.onexus.tech` chez Infomaniak.

## 📋 Prérequis

### Sur votre machine locale :
- Git installé
- Accès SSH à votre VPS
- Clés API (OpenAI, Mistral, Supabase)

### Sur votre VPS :
- Ubuntu/Debian 20.04+
- Accès root ou sudo
- DNS configuré pour `api-rag.onexus.tech` pointant vers votre IP VPS

## 🔧 Étape 1 : Configuration locale

### 1.1 Configuration des variables d'environnement

1. Copiez le template d'environnement :
```bash
cp env.template .env
```

2. Éditez le fichier `.env` avec vos vraies valeurs :
```bash
nano .env
```

**Variables OBLIGATOIRES à remplir :**
- `OPENAI_API_KEY` : Votre clé API OpenAI
- `MISTRAL_API_KEY` : Votre clé API Mistral  
- `SUPABASE_URL` : URL de votre projet Supabase
- `SUPABASE_ANON_KEY` : Clé publique Supabase
- `SUPABASE_JWT_SECRET` : Secret JWT Supabase
- `SSL_EMAIL` : Votre email pour les certificats SSL

### 1.2 Test local (optionnel)

```bash
# Tester localement avant déploiement
docker-compose up --build -d
curl http://localhost:18000/health/
docker-compose down
```

## 🖥️ Étape 2 : Préparation du VPS

### 2.1 Connexion au VPS

```bash
ssh root@votre-ip-vps
# ou
ssh votre-utilisateur@votre-ip-vps
```

### 2.2 Installation automatique

Exécutez le script d'installation sur votre VPS :

```bash
# Télécharger et exécuter le script d'installation
curl -fsSL https://raw.githubusercontent.com/votre-repo/RAG_ONEXUS/main/vps-setup.sh | bash
```

**Ou installation manuelle :**

```bash
# Mise à jour du système
sudo apt update && sudo apt upgrade -y

# Installation de Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Installation de Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Installation de Git
sudo apt install -y git curl nano

# Redémarrer la session pour appliquer les groupes
newgrp docker
```

### 2.3 Configuration du répertoire de projet

```bash
# Créer le répertoire du projet
mkdir -p /opt/rag-project
cd /opt/rag-project

# Donner les permissions appropriées
sudo chown -R $USER:$USER /opt/rag-project
```

## 📡 Étape 3 : Configuration Git et Déploiement

### 3.1 Configuration Git sur le VPS

```bash
# Cloner votre repository (première fois)
git clone https://github.com/votre-username/votre-repo.git .

# Ou initialiser si vous n'avez pas encore de repo Git
git init
git remote add origin https://github.com/votre-username/votre-repo.git
```

### 3.2 Configuration des credentials Git

```bash
# Configurer Git
git config --global user.name "Votre Nom"
git config --global user.email "votre-email@domain.com"

# Pour l'authentification, utilisez un token GitHub
git config --global credential.helper store
```

### 3.3 Copier les fichiers d'environnement

```bash
# Copier le template et le configurer
cp env.template .env
nano .env
# Remplir avec vos vraies valeurs
```

## 🚢 Étape 4 : Workflow de Déploiement

### 4.1 Depuis votre machine locale

```bash
# 1. Commiter vos changements
git add .
git commit -m "Update: description de vos changements"

# 2. Pousser vers le repository
git push origin main
```

### 4.2 Sur le VPS

```bash
# Se rendre dans le répertoire du projet
cd /opt/rag-project

# Exécuter le script de déploiement automatique
./git-deploy.sh
```

**Ou manuellement :**

```bash
# 1. Arrêter les conteneurs
docker-compose down

# 2. Récupérer les dernières modifications
git pull origin main

# 3. Reconstruire et démarrer
docker-compose up --build -d

# 4. Vérifier le statut
docker-compose ps
docker-compose logs -f --tail=50
```

## 🔒 Étape 5 : Configuration SSL avec Certbot

### 5.1 Installation de Certbot

```bash
# Installer Certbot
sudo apt install -y certbot

# Arrêter temporairement nginx pour libérer le port 80
docker-compose stop nginx
```

### 5.2 Génération du certificat SSL

```bash
# Générer le certificat SSL
sudo certbot certonly --standalone \
  --preferred-challenges http \
  --email votre-email@domain.com \
  --agree-tos \
  --no-eff-email \
  -d api-rag.onexus.tech

# Copier les certificats vers le projet
sudo mkdir -p ssl
sudo cp /etc/letsencrypt/live/api-rag.onexus.tech/fullchain.pem ssl/api-rag.onexus.tech.crt
sudo cp /etc/letsencrypt/live/api-rag.onexus.tech/privkey.pem ssl/api-rag.onexus.tech.key
sudo chown -R $USER:$USER ssl/
```

### 5.3 Redémarrage avec SSL

```bash
# Redémarrer avec SSL configuré
docker-compose up -d

# Vérifier que HTTPS fonctionne
curl -k https://api-rag.onexus.tech/health/
```

### 5.4 Auto-renouvellement SSL

```bash
# Ajouter une tâche cron pour le renouvellement automatique
sudo crontab -e

# Ajouter cette ligne pour renouveler tous les mois
0 0 1 * * /usr/bin/certbot renew --quiet && cd /opt/rag-project && docker-compose restart nginx
```

## 🔧 Étape 6 : Configuration du Pare-feu

```bash
# Configurer UFW (Ubuntu Firewall)
sudo ufw enable
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 8080/tcp  # HTTP externe
sudo ufw allow 8443/tcp  # HTTPS externe
sudo ufw status
```

## 📊 Étape 7 : Vérification et Tests

### 7.1 Tests de santé

```bash
# Test endpoint de santé
curl https://api-rag.onexus.tech/health/

# Test endpoint principal
curl https://api-rag.onexus.tech/

# Vérifier les logs
docker-compose logs -f
```

### 7.2 Tests fonctionnels

```bash
# Test upload (nécessite authentification)
curl -X POST "https://api-rag.onexus.tech/upload/" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -F "file=@test.pdf"

# Test question publique
curl -X POST "https://api-rag.onexus.tech/ask_public/" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Test question",
    "company_id": "your-company-id",
    "langue": "Français"
  }'
```

## 🔄 Workflows de Maintenance

### Déploiement rapide

```bash
# Sur votre machine locale
./quick-deploy.sh "Message de commit"

# Ou manuellement
git add . && git commit -m "Update" && git push origin main
```

### Mise à jour sur le VPS

```bash
# Sur le VPS
cd /opt/rag-project
./git-deploy.sh
```

### Surveillance

```bash
# Voir les logs en temps réel
docker-compose logs -f

# Voir le statut des conteneurs
docker-compose ps

# Voir l'utilisation des ressources
docker stats

# Redémarrer un service spécifique
docker-compose restart rag-api
docker-compose restart nginx
```

## 🆘 Dépannage

### Problèmes courants

1. **Erreur de port occupé :**
```bash
sudo lsof -i :80
sudo lsof -i :443
# Arrêter le processus qui occupe le port
```

2. **Problème de certificat SSL :**
```bash
# Regénérer le certificat
sudo certbot renew --force-renewal
```

3. **Problème de permissions :**
```bash
sudo chown -R $USER:$USER /opt/rag-project
```

4. **Conteneurs qui ne démarrent pas :**
```bash
docker-compose logs rag-api
docker-compose logs nginx
```

### Sauvegarde

```bash
# Sauvegarder les données
tar -czf backup-$(date +%Y%m%d).tar.gz data/ ssl/ .env

# Sauvegarder sur un stockage externe (optionnel)
rsync -av /opt/rag-project/ backup-server:/path/to/backup/
```

## 🎯 Points importants

1. **Sécurité :** Toujours utiliser HTTPS en production
2. **Sauvegarde :** Sauvegarder régulièrement les données et configurations
3. **Monitoring :** Surveiller les logs et performances
4. **Mise à jour :** Maintenir Docker et le système à jour
5. **Variables d'environnement :** Ne jamais commiter le fichier `.env`

## 📞 Support

En cas de problème :
1. Vérifiez les logs : `docker-compose logs -f`
2. Vérifiez le statut : `docker-compose ps`
3. Redémarrez : `docker-compose restart`
4. Consultez ce guide de dépannage

---

**🎉 Félicitations !** Votre API RAG est maintenant déployée et accessible via `https://api-rag.onexus.tech` 
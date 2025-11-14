# 🚀 RAG_ONEXUS - Guide de Déploiement Complet

> **Système de déploiement automatisé pour l'API RAG avec Docker sur VPS Infomaniak**

## 📁 Fichiers de Configuration Créés

Voici tous les fichiers créés pour automatiser votre déploiement :

### 🔧 Configuration
- **`env.template`** - Template des variables d'environnement
- **`docker-compose.yml`** - Configuration Docker améliorée avec healthchecks
- **`GUIDE_DEPLOIEMENT.md`** - Guide détaillé étape par étape

### 🛠️ Scripts d'Automatisation
- **`vps-setup.sh`** - Installation initiale automatique du VPS
- **`quick-deploy.sh`** - Déploiement rapide depuis votre machine locale
- **`git-deploy.sh`** - Déploiement automatique sur le VPS
- **`ssl-setup.sh`** - Configuration SSL automatique avec Certbot
- **`monitor.sh`** - Monitoring complet du système

### 📄 Documentation
- **`README_DEPLOIEMENT.md`** - Ce fichier (résumé général)
- **Dockerfile** et **nginx/** - Configuration existante optimisée

## 🎯 Workflow de Déploiement Recommandé

### 1️⃣ Première Installation (Une seule fois)

```bash
# Sur votre VPS
curl -fsSL https://raw.githubusercontent.com/votre-repo/RAG_ONEXUS/main/vps-setup.sh | bash

# Configuration du projet
cd /opt/rag-project
git clone https://github.com/votre-username/votre-repo.git .
cp env.template .env
nano .env  # Remplir avec vos vraies valeurs

# Configuration SSL
./ssl-setup.sh votre-email@domain.com

# Premier déploiement
./git-deploy.sh
```

### 2️⃣ Déploiements Suivants (Quotidien)

```bash
# Sur votre machine locale
./quick-deploy.sh "Votre message de commit"

# Sur le VPS (automatiquement ou manuellement)
./git-deploy.sh
```

### 3️⃣ Monitoring et Maintenance

```bash
# Monitoring en temps réel
./monitor.sh --continuous

# Vérification ponctuelle
./monitor.sh

# Logs en temps réel
./monitor.sh --logs

# Sauvegarde
./backup.sh
```

## 🔑 Variables d'Environnement Importantes

Assurez-vous de configurer ces variables dans votre fichier `.env` :

```bash
# API Keys (OBLIGATOIRES)
OPENAI_API_KEY=sk-your-openai-api-key
MISTRAL_API_KEY=your-mistral-api-key

# Supabase (OBLIGATOIRES)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIs...
SUPABASE_JWT_SECRET=your-jwt-secret

# Configuration SSL
SSL_EMAIL=votre-email@domain.com
DOMAIN=api-rag.onexus.tech
```

## 🌐 URLs d'Accès

Une fois déployé, votre API sera accessible via :

- **Production HTTPS :** `https://api-rag.onexus.tech/`
- **Health Check :** `https://api-rag.onexus.tech/health/`
- **Documentation :** `https://api-rag.onexus.tech/docs`
- **Debug local :** `http://localhost:18000/`

## 📋 Checklist de Déploiement

### ✅ Prérequis
- [ ] VPS Ubuntu/Debian chez Infomaniak
- [ ] DNS configuré (`api-rag.onexus.tech` → IP du VPS)
- [ ] Clés API (OpenAI, Mistral, Supabase)
- [ ] Accès SSH au VPS

### ✅ Installation Initiale
- [ ] Exécution de `vps-setup.sh`
- [ ] Configuration du fichier `.env`
- [ ] Premier déploiement avec `git-deploy.sh`
- [ ] Configuration SSL avec `ssl-setup.sh`
- [ ] Test de l'API

### ✅ Tests de Validation
- [ ] `curl https://api-rag.onexus.tech/health/` retourne `{"status": "healthy"}`
- [ ] Upload de fichier fonctionne
- [ ] Questions publiques fonctionnent
- [ ] Authentification JWT fonctionne
- [ ] Monitoring avec `./monitor.sh`

## 🛠️ Commandes Utiles

```bash
# Voir les logs
docker-compose logs -f

# Redémarrer un service
docker-compose restart rag-api
docker-compose restart nginx

# Voir l'état des conteneurs
docker-compose ps

# Monitoring complet
./monitor.sh

# Déploiement rapide
./quick-deploy.sh "Fix bug"

# Backup
./backup.sh

# Renouveler SSL manuellement
sudo certbot renew
```

## 🆘 Dépannage Rapide

### Problème: API ne répond pas
```bash
# Vérifier les conteneurs
docker-compose ps

# Voir les logs
docker-compose logs rag-api

# Redémarrer
docker-compose restart rag-api
```

### Problème: SSL ne fonctionne pas
```bash
# Regénérer le certificat
./ssl-setup.sh

# Vérifier nginx
docker-compose logs nginx
```

### Problème: Erreur de déploiement
```bash
# Vérifier Git
git status
git pull origin main

# Redéployer
./git-deploy.sh
```

## 📊 Architecture du Système

```
┌─────────────────┐    ┌──────────────┐    ┌─────────────┐
│   Utilisateur   │────│    Nginx     │────│   API RAG   │
│                 │    │  (Port 443)  │    │ (Port 8000) │
└─────────────────┘    └──────────────┘    └─────────────┘
                               │
                       ┌──────────────┐
                       │  Let's Encrypt│
                       │ Certificates  │
                       └──────────────┘
```

## 🔄 Workflow Git

1. **Développement local** → Modifications du code
2. **`quick-deploy.sh`** → Commit + Push automatique
3. **`git-deploy.sh`** sur VPS → Pull + Build + Deploy
4. **`monitor.sh`** → Vérification du déploiement

## 📈 Monitoring et Alertes

Le script `monitor.sh` surveille :
- ✅ État des conteneurs
- ✅ Santé des services
- ✅ Utilisation des ressources
- ✅ Certificats SSL
- ✅ Connectivité réseau
- ✅ Temps de réponse

## 🔐 Sécurité

- 🔒 HTTPS obligatoire avec Let's Encrypt
- 🔑 Authentification JWT avec Supabase
- 🛡️ Firewall UFW configuré
- 📝 Logs sécurisés
- 🔄 Renouvellement automatique des certificats

## 📞 Support

En cas de problème :

1. **Consultez les logs :** `./monitor.sh --logs`
2. **Vérifiez l'état :** `./monitor.sh`
3. **Consultez la documentation :** `GUIDE_DEPLOIEMENT.md`
4. **Redémarrez si nécessaire :** `docker-compose restart`

---

## 🎉 Félicitations !

Votre système RAG_ONEXUS est maintenant entièrement automatisé et prêt pour la production ! 

**API accessible à :** `https://api-rag.onexus.tech/`

Pour toute question ou amélioration, n'hésitez pas à consulter le guide détaillé dans `GUIDE_DEPLOIEMENT.md`. 
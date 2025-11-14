# 🚀 API RAG Publique - Mise à jour

## ✨ Nouveautés

Votre système RAG supporte maintenant **l'accès public sans authentification** ! Vous pouvez intégrer des chatbots externes qui utilisent vos documents d'entreprise.

## 🔄 Ce qui a changé

### ✅ Ajouté
- **Endpoint public `/ask_public/`** - Questions sans authentification
- **Gestion des sessions publiques** - Historique des conversations
- **Support du `company_id`** - Isolation par entreprise
- **`external_user_id`** - Identification des utilisateurs externes
- **Exemples d'intégration** - Python, JavaScript, PHP
- **Interface web de test** - `exemple-chatbot-web.html`

### 🔒 Conservé
- **API authentifiée `/ask/`** - Pour le dashboard existant
- **Système Supabase** - Sessions et messages persistants
- **Isolation des données** - Sécurité par entreprise
- **Toutes les fonctionnalités** existantes

## 🚀 Démarrage rapide

### 1. Lancer le serveur
```bash
cd RAG_ONEXUS
uvicorn app:app --reload
```

### 2. Test simple avec curl
```bash
curl -X POST "http://localhost:8000/ask_public/" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Présentez-moi votre entreprise",
    "company_id": "b28cfe88-807b-49de-97f7-fd974cfd0d17"
  }'
```

### 3. Test avec Python
```bash
python exemple-usage.py
```

### 4. Test avec interface web
Ouvrez `exemple-chatbot-web.html` dans votre navigateur.

## 📊 Endpoints disponibles

| Endpoint | Authentification | Description |
|----------|------------------|-------------|
| `POST /ask/` | ✅ JWT requis | Dashboard interne |
| `POST /ask_public/` | ❌ Aucune | Chatbots externes |
| `GET /sessions_public/{company_id}` | ❌ Aucune | Lister les sessions |
| `GET /messages_public/{session_id}` | ❌ Aucune | Historique des messages |

## 🔧 Utilisation dans vos projets

### Python
```python
import requests

def ask_question(question, company_id):
    response = requests.post("http://localhost:8000/ask_public/", json={
        "question": question,
        "company_id": company_id,
        "external_user_id": "mon_app_user_123"
    })
    return response.json()["answer"]

# Utilisation
answer = ask_question("Comment ça marche ?", "votre-company-id")
print(answer)
```

### JavaScript
```javascript
async function askQuestion(question, companyId) {
    const response = await fetch("http://localhost:8000/ask_public/", {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            question: question,
            company_id: companyId,
            external_user_id: "web_user_456"
        })
    });
    const result = await response.json();
    return result.answer;
}

// Utilisation
const answer = await askQuestion("Vos tarifs ?", "votre-company-id");
console.log(answer);
```

## 🏢 Comment obtenir votre company_id

### Option 1: Depuis le dashboard
1. Connectez-vous au dashboard `/dashboard`
2. L'ID s'affiche dans l'URL ou les outils de développement

### Option 2: Depuis la base de données
```sql
SELECT id, name FROM companies;
```

### Option 3: Via l'API authentifiée
```bash
curl -X GET "http://localhost:8000/stats/" \
  -H "Authorization: Bearer votre-jwt-token"
```

## 📋 Cas d'usage

### 1. Widget de chat sur site web
```html
<!-- Intégrez le chatbot sur votre site -->
<script src="votre-chatbot.js"></script>
<div id="chatbot" data-company-id="votre-company-id"></div>
```

### 2. Bot WhatsApp/Telegram
```python
# Exemple pour Telegram
@bot.message_handler(commands=['ask'])
def handle_ask(message):
    question = message.text.replace('/ask ', '')
    answer = ask_question(question, COMPANY_ID)
    bot.reply_to(message, answer)
```

### 3. API tierce
```python
# Votre API expose l'intelligence de votre entreprise
@app.route('/api/knowledge', methods=['POST'])
def knowledge_api():
    question = request.json.get('question')
    answer = ask_question(question, COMPANY_ID)
    return {'answer': answer}
```

## ⚙️ Configuration avancée

### Variables d'environnement
```bash
# .env
SUPABASE_URL=https://votre-projet.supabase.co
SUPABASE_ANON_KEY=votre_cle_anon
SUPABASE_JWT_SECRET=votre_jwt_secret
OPENAI_API_KEY=votre_cle_openai
MISTRAL_API_KEY=votre_cle_mistral
```

### CORS pour production
```python
# app.py - Configurez les origines autorisées
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://votre-site.com", "https://app.exemple.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

## 🔒 Sécurité

### ✅ Protections en place
- **Isolation par entreprise** - Chaque `company_id` est isolé
- **Validation des données** - Vérification de l'existence de l'entreprise
- **Pas d'accès aux autres entreprises** - Sécurité garantie

### ⚠️ À implémenter pour la production
- **Rate limiting** - Limitez les requêtes par IP/utilisateur
- **Monitoring** - Surveillez l'usage et les coûts
- **Base de données** - Persistance des sessions (actuellement en mémoire)
- **Logs** - Tracez les accès pour le debugging

## 📝 Fichiers créés/modifiés

```
RAG_ONEXUS/
├── app.py                          # ✏️ Modifié - Nouveaux endpoints publics
├── exemple-usage.py                # ✏️ Mis à jour - Exemples API publique  
├── exemple-chatbot-web.html        # ✨ Nouveau - Interface web de test
├── API_PUBLIQUE.md                 # ✨ Nouveau - Documentation complète
└── README_API_PUBLIQUE.md          # ✨ Nouveau - Ce fichier
```

## 🆘 Résolution de problèmes

### Erreur 404 "Entreprise non trouvée"
- Vérifiez que le `company_id` existe
- Assurez-vous que l'entreprise a des documents uploadés
- Construisez l'index avec `/build_index/` (authentifié)

### Erreur de connexion
- Vérifiez que le serveur tourne sur `http://localhost:8000`
- Testez avec `/health/` pour vérifier la disponibilité
- Consultez les logs du serveur

### Pas de réponse intelligente
- Vérifiez que l'index est construit pour cette entreprise
- Testez d'abord avec l'API authentifiée `/ask/`
- Vérifiez les clés API (OpenAI/Mistral) dans `.env`

## 🎯 Prochaines étapes

1. **Testez** avec vos vraies données d'entreprise
2. **Intégrez** dans votre application externe
3. **Personnalisez** les exemples selon vos besoins
4. **Déployez** en production avec les sécurités appropriées
5. **Monitorez** l'usage et optimisez si nécessaire

---

🎉 **Votre API RAG est maintenant publique et prête pour l'intégration externe !**

Pour toute question : consultez `API_PUBLIQUE.md` pour la documentation complète. 
# API RAG Publique - Documentation

## 🌟 Introduction

L'API RAG publique permet d'intégrer des chatbots intelligents dans vos applications externes sans authentification. Vous pouvez poser des questions sur les documents d'une entreprise spécifique en passant simplement son `company_id`.

## 🚀 Endpoints Publics Disponibles

### 1. POST `/ask_public/` - Poser une question

**Description** : Pose une question au système RAG pour une entreprise spécifique.

**Paramètres** :
```json
{
  "question": "Votre question ici",
  "company_id": "uuid-de-l-entreprise", 
  "session_id": "uuid-session-optionnel",
  "external_user_id": "identifiant-utilisateur-externe-optionnel",
  "langue": "Français"
}
```

**Réponse** :
```json
{
  "answer": "Réponse générée par l'IA",
  "company_id": "uuid-de-l-entreprise",
  "session_id": "uuid-de-la-session",
  "external_user_id": "identifiant-utilisateur-externe"
}
```

**Exemple d'utilisation** :
```bash
curl -X POST "http://localhost:8000/ask_public/" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Qu'\''est-ce qu'\''Onexia ?",
    "company_id": "b28cfe88-807b-49de-97f7-fd974cfd0d17",
    "external_user_id": "user_123"
  }'
```

### 2. GET `/sessions_public/{company_id}` - Lister les sessions

**Description** : Récupère toutes les sessions de chat pour une entreprise.

**Paramètres** :
- `company_id` (path) : UUID de l'entreprise
- `external_user_id` (query, optionnel) : Filtrer par utilisateur externe

**Réponse** :
```json
{
  "sessions": [
    {
      "session_id": "uuid-session",
      "company_id": "uuid-entreprise",
      "external_user_id": "user_123",
      "title": "Conversation publique 15/01/2024 14:30",
      "created_at": "2024-01-15T14:30:00"
    }
  ],
  "company_id": "uuid-entreprise",
  "total": 1
}
```

### 3. GET `/messages_public/{session_id}` - Récupérer les messages

**Description** : Récupère tous les messages d'une session de chat.

**Paramètres** :
- `session_id` (path) : UUID de la session

**Réponse** :
```json
{
  "messages": [
    {
      "message_id": "uuid-message",
      "session_id": "uuid-session",
      "content": "Qu'est-ce qu'Onexia ?",
      "role": "user",
      "created_at": "2024-01-15T14:30:00"
    },
    {
      "message_id": "uuid-message-2",
      "session_id": "uuid-session", 
      "content": "Onexia est une plateforme...",
      "role": "assistant",
      "created_at": "2024-01-15T14:30:05"
    }
  ],
  "session": { /* détails de la session */ },
  "total": 2
}
```

## 🔧 Intégrations

### Python

```python
import requests

class PublicRAGClient:
    def __init__(self, api_url="http://localhost:8000"):
        self.api_url = api_url
        self.session_id = None
    
    def ask(self, question, company_id, external_user_id=None):
        payload = {
            "question": question,
            "company_id": company_id,
            "session_id": self.session_id,
            "external_user_id": external_user_id
        }
        
        response = requests.post(f"{self.api_url}/ask_public/", json=payload)
        result = response.json()
        
        # Sauvegarder le session_id
        if not self.session_id:
            self.session_id = result.get("session_id")
            
        return result

# Utilisation
client = PublicRAGClient()
response = client.ask(
    "Présentez-moi votre entreprise",
    "b28cfe88-807b-49de-97f7-fd974cfd0d17",
    "chatbot_user_456"
)
print(response["answer"])
```

### JavaScript/Web

```javascript
class PublicRAGClient {
    constructor(apiUrl = "http://localhost:8000") {
        this.apiUrl = apiUrl;
        this.sessionId = null;
    }
    
    async ask(question, companyId, externalUserId = null) {
        const payload = {
            question: question,
            company_id: companyId,
            session_id: this.sessionId,
            external_user_id: externalUserId
        };
        
        const response = await fetch(`${this.apiUrl}/ask_public/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const result = await response.json();
        
        // Sauvegarder le session_id
        if (!this.sessionId) {
            this.sessionId = result.session_id;
        }
        
        return result;
    }
}

// Utilisation
const client = new PublicRAGClient();
const response = await client.ask(
    "Comment utiliser vos services ?", 
    "b28cfe88-807b-49de-97f7-fd974cfd0d17",
    "web_user_789"
);
console.log(response.answer);
```

### PHP

```php
<?php
class PublicRAGClient {
    private $apiUrl;
    private $sessionId;
    
    public function __construct($apiUrl = "http://localhost:8000") {
        $this->apiUrl = $apiUrl;
        $this->sessionId = null;
    }
    
    public function ask($question, $companyId, $externalUserId = null) {
        $payload = [
            'question' => $question,
            'company_id' => $companyId,
            'session_id' => $this->sessionId,
            'external_user_id' => $externalUserId
        ];
        
        $ch = curl_init();
        curl_setopt($ch, CURLOPT_URL, $this->apiUrl . '/ask_public/');
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($payload));
        curl_setopt($ch, CURLOPT_HTTPHEADER, ['Content-Type: application/json']);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        
        $response = curl_exec($ch);
        curl_close($ch);
        
        $result = json_decode($response, true);
        
        // Sauvegarder le session_id
        if (!$this->sessionId && isset($result['session_id'])) {
            $this->sessionId = $result['session_id'];
        }
        
        return $result;
    }
}

// Utilisation
$client = new PublicRAGClient();
$response = $client->ask(
    "Quels sont vos tarifs ?",
    "b28cfe88-807b-49de-97f7-fd974cfd0d17",
    "php_user_101"
);
echo $response['answer'];
?>
```

## 📋 Cas d'usage

### 1. Widget de chat sur site web
Intégrez un chatbot intelligent sur votre site qui répond aux questions basées sur votre documentation.

### 2. Chatbot WhatsApp/Telegram
Créez un bot qui utilise vos documents pour répondre aux clients sur les messageries.

### 3. API tierce
Permettez à d'autres applications d'interroger votre base de connaissances.

### 4. Support client automatisé
Répondez automatiquement aux questions fréquentes en utilisant vos documents internes.

## 🔒 Sécurité et Limites

### Sécurité
- **Aucune authentification requise** pour les endpoints publics
- Les données sont **isolées par entreprise** via le `company_id`
- **Validation** du `company_id` - l'entreprise doit exister et avoir des documents

### Limites actuelles
- **Stockage en mémoire** : Les sessions sont perdues au redémarrage du serveur
- **Pas de rate limiting** : Implémentez vos propres limites si nécessaire
- **Pas de permissions granulaires** : Accès à tous les documents de l'entreprise

### Recommandations pour la production
1. **Implémenter une base de données** pour la persistance des sessions
2. **Ajouter du rate limiting** pour éviter l'abus
3. **Configurer CORS** correctement pour vos domaines
4. **Monitorer l'usage** et les coûts API
5. **Ajouter des logs** pour le debugging

## 🔄 Comparaison API Authentifiée vs Publique

| Fonctionnalité | API Authentifiée (`/ask/`) | API Publique (`/ask_public/`) |
|---|---|---|
| **Authentification** | JWT Token requis | Aucune |
| **Company ID** | Extrait du token | Passé en paramètre |
| **Sessions** | Supabase (persistant) | Mémoire (temporaire) |
| **Utilisateur** | User ID Supabase | External User ID optionnel |
| **Sécurité** | RLS + Permissions | Validation company_id |
| **Usage** | Dashboard interne | Intégrations externes |

## 🧪 Test rapide

1. **Démarrer le serveur** :
   ```bash
   cd RAG_ONEXUS
   uvicorn app:app --reload
   ```

2. **Tester avec curl** :
   ```bash
   curl -X POST "http://localhost:8000/ask_public/" \
     -H "Content-Type: application/json" \
     -d '{
       "question": "Bonjour, pouvez-vous vous présenter ?",
       "company_id": "b28cfe88-807b-49de-97f7-fd974cfd0d17"
     }'
   ```

3. **Utiliser l'exemple Python** :
   ```bash
   python exemple-usage.py
   ```

4. **Ouvrir l'exemple web** :
   Ouvrez `exemple-chatbot-web.html` dans votre navigateur.

## 📞 Support

Pour toute question ou problème :
1. Vérifiez que votre `company_id` existe et a des documents
2. Consultez les logs du serveur pour les erreurs
3. Testez d'abord avec l'API authentifiée pour valider vos données
4. Utilisez les exemples fournis comme base pour votre intégration

---

✨ **Votre API RAG est maintenant publique et prête pour l'intégration dans vos applications externes !** 
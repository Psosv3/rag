#!/usr/bin/env python3
"""
Exemple d'utilisation de l'API RAG publique
Montre comment utiliser l'endpoint /ask_public/ sans authentification
"""

import requests
import json
from typing import Optional

# Configuration
API_BASE_URL = "http://localhost:8000"

class PublicRAGClient:
    """Client pour interagir avec l'API RAG publique."""
    
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url
        self.session_id = None
        
    def ask_question(self, question: str, company_id: str, external_user_id: Optional[str] = None, langue: str = "Français"):
        """
        Pose une question à l'API RAG publique.
        
        Args:
            question: La question à poser
            company_id: L'ID de l'entreprise pour laquelle chercher des réponses
            external_user_id: Identifiant optionnel de l'utilisateur externe
            langue: Langue de la réponse (défaut: Français)
        """
        try:
            data = {
                "question": question,
                "company_id": company_id,
                "session_id": self.session_id,
                "external_user_id": external_user_id,
                "langue": langue
            }
            
            response = requests.post(f"{self.base_url}/ask_public/", json=data)
            
            if response.status_code == 200:
                result = response.json()
                
                # Sauvegarder le session_id pour les prochaines questions
                if not self.session_id:
                    self.session_id = result.get("session_id")
                
                print(f"✅ Question: {question}")
                print(f"🏢 Entreprise: {company_id}")
                print(f"📝 Réponse: {result['answer']}")
                print(f"🔗 Session ID: {result.get('session_id')}")
                if external_user_id:
                    print(f"👤 Utilisateur externe: {external_user_id}")
                print("-" * 50)
                
                return result
            else:
                print(f"❌ Erreur {response.status_code}: {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ Erreur: {e}")
            return None
    
    def get_sessions(self, company_id: str, external_user_id: Optional[str] = None):
        """Récupère la liste des sessions pour une entreprise."""
        try:
            params = {}
            if external_user_id:
                params["external_user_id"] = external_user_id
                
            response = requests.get(f"{self.base_url}/sessions_public/{company_id}", params=params)
            
            if response.status_code == 200:
                result = response.json()
                print(f"📋 Sessions pour l'entreprise {company_id}:")
                for session in result["sessions"]:
                    print(f"  - {session['title']} ({session['session_id']})")
                return result
            else:
                print(f"❌ Erreur {response.status_code}: {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ Erreur: {e}")
            return None
    
    def get_messages(self, session_id: str):
        """Récupère les messages d'une session."""
        try:
            response = requests.get(f"{self.base_url}/messages_public/{session_id}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"💬 Messages de la session {session_id}:")
                for message in result["messages"]:
                    role_icon = "👤" if message["role"] == "user" else "🤖"
                    print(f"  {role_icon} {message['content']}")
                return result
            else:
                print(f"❌ Erreur {response.status_code}: {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ Erreur: {e}")
            return None

def exemple_utilisation_simple():
    """Exemple d'utilisation simple."""
    print("🚀 Exemple d'utilisation simple de l'API RAG publique")
    print("=" * 60)
    
    # Remplacez par un vrai company_id de votre système
    COMPANY_ID = "b28cfe88-807b-49de-97f7-fd974cfd0d17"  # ID d'exemple
    
    client = PublicRAGClient()
    
    # Poser quelques questions
    questions = [
        "Qu'est-ce qu'Onexia ?",
        "Comment fonctionne le système d'agents ?",
        "Quelles sont les fonctionnalités principales ?"
    ]
    
    for question in questions:
        client.ask_question(question, COMPANY_ID)
    
    # Récupérer l'historique de la session
    if client.session_id:
        print("\n📖 Historique de la conversation:")
        client.get_messages(client.session_id)

def exemple_utilisation_multitenancy():
    """Exemple d'utilisation avec plusieurs entreprises."""
    print("\n🏢 Exemple d'utilisation multi-tenant")
    print("=" * 60)
    
    # Différentes entreprises (remplacez par vos vrais IDs)
    companies = {
        "entreprise_a": "b28cfe88-807b-49de-97f7-fd974cfd0d17",
        "entreprise_b": "autre-company-id-exemple"
    }
    
    for company_name, company_id in companies.items():
        print(f"\n🏢 Questions pour {company_name} ({company_id}):")
        client = PublicRAGClient()
        
        # Question spécifique à chaque entreprise
        client.ask_question(
            f"Présentez-moi votre entreprise", 
            company_id,
            external_user_id=f"user_external_{company_name}"
        )

def exemple_chatbot_externe():
    """Exemple d'utilisation comme chatbot externe."""
    print("\n🤖 Simulation d'un chatbot externe")
    print("=" * 60)
    
    COMPANY_ID = "b28cfe88-807b-49de-97f7-fd974cfd0d17"
    EXTERNAL_USER_ID = "chatbot_widget_user_123"
    
    client = PublicRAGClient()
    
    # Simulation d'une conversation utilisateur
    conversation = [
        "Bonjour, pouvez-vous me parler de vos services ?",
        "Comment puis-je utiliser Onexia ?",
        "Quels sont les avantages de votre solution ?"
    ]
    
    print(f"💭 Conversation simulée pour l'utilisateur {EXTERNAL_USER_ID}")
    
    for question in conversation:
        response = client.ask_question(
            question, 
            COMPANY_ID, 
            external_user_id=EXTERNAL_USER_ID
        )
        
        if not response:
            break

def tester_api_status():
    """Teste si l'API est disponible."""
    try:
        response = requests.get(f"{API_BASE_URL}/health/")
        if response.status_code == 200:
            print("✅ API disponible")
            
            # Tester la page d'accueil pour voir les nouveaux endpoints
            response = requests.get(f"{API_BASE_URL}/")
            if response.status_code == 200:
                info = response.json()
                print(f"📊 Version de l'API: {info.get('version')}")
                print(f"🔓 Endpoints publics: {info.get('public_endpoints')}")
            return True
        else:
            print("❌ API non disponible")
            return False
    except Exception as e:
        print(f"❌ Impossible de joindre l'API: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Test de l'API RAG publique")
    print("=" * 60)
    
    # Vérifier que l'API est disponible
    if not tester_api_status():
        print("\n⚠️  Assurez-vous que le backend RAG fonctionne sur http://localhost:8000")
        print("   Commande: cd RAG_ONEXUS && uvicorn app:app --reload")
        exit(1)
    
    print("\n" + "=" * 60)
    
    # Exemple d'utilisation simple
    exemple_utilisation_simple()
    
    # Exemple multi-tenant (commenté par défaut car nécessite plusieurs entreprises)
    # exemple_utilisation_multitenancy()
    
    # Exemple chatbot externe
    exemple_chatbot_externe()
    
    print("\n✅ Tests terminés !")
    print("\n📝 Notes d'utilisation:")
    print("- Remplacez 'b28cfe88-807b-49de-97f7-fd974cfd0d17' par un vrai company_id")
    print("- L'API conserve l'historique des conversations par session")
    print("- Vous pouvez spécifier un external_user_id pour identifier vos utilisateurs")
    print("- Les sessions sont stockées en mémoire (perdues au redémarrage du serveur)") 
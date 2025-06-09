#!/usr/bin/env python3
"""
Exemple d'utilisation de l'API RAG déployée sur api-rag.onexus.tech
"""

import requests
import json
import os
from pathlib import Path

# Configuration
API_BASE_URL = "https://api-rag.onexus.tech"
OPENAI_API_KEY = "your_openai_api_key_here"  # Remplacez par votre vraie clé

def test_api_connection():
    """Test de connexion à l'API"""
    try:
        response = requests.get(f"{API_BASE_URL}/")
        if response.status_code == 200:
            print("✅ Connexion à l'API réussie")
            print(f"Réponse: {response.json()}")
            return True
        else:
            print(f"❌ Erreur de connexion: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Erreur de connexion: {e}")
        return False

def upload_file(file_path):
    """Upload d'un fichier vers l'API"""
    if not os.path.exists(file_path):
        print(f"❌ Fichier non trouvé: {file_path}")
        return False
    
    try:
        with open(file_path, 'rb') as f:
            files = {'file': f}
            response = requests.post(f"{API_BASE_URL}/upload/", files=files)
        
        if response.status_code == 200:
            print(f"✅ Fichier uploadé avec succès: {response.json()}")
            return True
        else:
            print(f"❌ Erreur upload: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Erreur upload: {e}")
        return False

def build_index():
    """Construction de l'index vectoriel"""
    try:
        data = {'openai_api_key': OPENAI_API_KEY}
        response = requests.post(f"{API_BASE_URL}/build_index/", data=data)
        
        if response.status_code == 200:
            print(f"✅ Index construit avec succès: {response.json()}")
            return True
        else:
            print(f"❌ Erreur construction index: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Erreur construction index: {e}")
        return False

def ask_question(question):
    """Poser une question à l'API"""
    try:
        data = {
            'question': question,
            'openai_api_key': OPENAI_API_KEY
        }
        response = requests.post(f"{API_BASE_URL}/ask/", data=data)
        
        if response.status_code == 200:
            answer = response.json().get('answer', 'Pas de réponse')
            print(f"✅ Question: {question}")
            print(f"📝 Réponse: {answer}")
            return answer
        else:
            print(f"❌ Erreur question: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Erreur question: {e}")
        return None

def main():
    """Fonction principale de démonstration"""
    print("🚀 Test de l'API RAG")
    print("=" * 50)
    
    # Test de connexion
    print("\n1. Test de connexion à l'API...")
    if not test_api_connection():
        return
    
    # Upload de fichier (optionnel si vous voulez tester avec un nouveau fichier)
    print("\n2. Upload d'un fichier (optionnel)...")
    # upload_file("path/to/your/document.pdf")
    print("⏩ Skip - utilisation des fichiers déjà présents")
    
    # Construction de l'index
    print("\n3. Construction de l'index...")
    if not build_index():
        return
    
    # Questions d'exemple
    questions = [
        "Quelle est la principale information du document ?",
        "Pouvez-vous résumer le contenu principal ?",
        "Quels sont les points clés mentionnés ?",
        "Y a-t-il des recommandations spécifiques ?"
    ]
    
    print("\n4. Test des questions...")
    for i, question in enumerate(questions, 1):
        print(f"\n--- Question {i} ---")
        ask_question(question)
        print("-" * 30)
    
    print("\n🎉 Tests terminés !")

def interactive_mode():
    """Mode interactif pour poser des questions"""
    print("🤖 Mode interactif - Posez vos questions à l'API RAG")
    print("Tapez 'quit' pour quitter")
    print("=" * 50)
    
    # Vérification de la connexion
    if not test_api_connection():
        return
    
    # Construction de l'index
    print("\nConstruction de l'index...")
    if not build_index():
        return
    
    print("\n✨ Prêt à répondre à vos questions !")
    
    while True:
        question = input("\n🙋 Votre question: ").strip()
        
        if question.lower() in ['quit', 'exit', 'q']:
            print("👋 Au revoir !")
            break
        
        if not question:
            print("⚠️  Veuillez poser une question valide")
            continue
        
        ask_question(question)

if __name__ == "__main__":
    # Configuration
    if OPENAI_API_KEY == "your_openai_api_key_here":
        print("⚠️  N'oubliez pas de remplacer OPENAI_API_KEY par votre vraie clé !")
        OPENAI_API_KEY = input("Entrez votre clé API OpenAI: ").strip()
    
    # Menu de choix
    print("Choisissez un mode:")
    print("1. Test automatique")
    print("2. Mode interactif")
    
    choice = input("Votre choix (1 ou 2): ").strip()
    
    if choice == "1":
        main()
    elif choice == "2":
        interactive_mode()
    else:
        print("Choix invalide") 
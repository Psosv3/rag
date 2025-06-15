# Système RAG (Retrieval-Augmented Generation)

Ce projet est un système RAG simple qui permet de :
1. Uploader des documents PDF ou DOCX
2. Construire un index de recherche
3. Poser des questions sur le contenu des documents

## Prérequis

- Python 3.9 ou plus
- Une clé API OpenAI

## Installation

1. Clonez ce dépôt :
```bash
git clone <votre-repo>
cd RAG
```

2. Installez les dépendances :
```bash
pip install -r requirements.txt
```

3. Créez un fichier `.env` à la racine du projet et ajoutez votre clé API OpenAI :
```
OPENAI_API_KEY=votre-clé-api-ici
```

## Utilisation

1. Lancez le serveur :
```bash
uvicorn app:app --reload
```

2. Accédez à l'interface Swagger UI :
```
http://localhost:8000/docs
```

3. Utilisez les endpoints dans cet ordre :
   - `/upload/` : Uploader vos documents PDF ou DOCX
   - `/build_index/` : Construire l'index de recherche
   - `/ask/` : Poser des questions sur vos documents

## Déploiement sur un serveur Debian

1. Installez les dépendances système :
```bash
sudo apt update
sudo apt install python3 python3-pip git
```

2. Clonez le projet :
```bash
git clone <votre-repo>
cd RAG
```

3. Installez les dépendances Python :
```bash
pip3 install -r requirements.txt
```

4. Lancez le serveur :
```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```
4. Lancez le serveur en MODE DEV:
```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```


[Swagger UI](http://localhost:8000/docs)


## Sécurité

- Ne partagez jamais votre clé API OpenAI
- En production, configurez correctement CORS
- Utilisez HTTPS
- Ajoutez une authentification si nécessaire

## Structure du projet

```
RAG/
│
├── app.py                # Application FastAPI
├── rag_utils.py          # Fonctions utilitaires RAG
├── requirements.txt      # Dépendances Python
├── .env                 # Variables d'environnement
├── data/                # Dossier pour les documents
└── README.md
``` 
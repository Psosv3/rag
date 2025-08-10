import os
import jwt
import uuid
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from rag_utils import build_index, get_answer, get_company_data_dir, get_company_stats, clear_company_cache
from dotenv import load_dotenv
import models
import httpx
from typing import Optional, Dict
from pydantic import BaseModel

# Charger les variables d'environnement
load_dotenv()

app = FastAPI(title="RAG API", description="API pour le système RAG avec multitenancy")

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En production, spécifiez les origines autorisées
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# Configuration Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

security = HTTPBearer()

class AuthUser:
    def __init__(self, user_id: str, company_id: str, role: str):
        self.user_id = user_id
        self.company_id = company_id
        self.role = role

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> AuthUser:
    """Vérifie le token JWT et retourne les informations utilisateur."""
    try:
        token = credentials.credentials
        
        # Décoder le token JWT
        payload = jwt.decode(
            token, 
            SUPABASE_JWT_SECRET, 
            algorithms=["HS256"],
            audience="authenticated"
        )
        
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token invalide")
        
        # Récupérer les informations utilisateur depuis Supabase
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/user_profiles",
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                params={"user_id": f"eq.{user_id}", "select": "company_id,role"}
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Utilisateur non trouvé")
            
            user_data = response.json()
            if not user_data:
                raise HTTPException(status_code=401, detail="Profil utilisateur non trouvé")
            
            return AuthUser(
                user_id=user_id,
                company_id=user_data[0]["company_id"],
                role=user_data[0]["role"]
            )
            
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expiré")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalide")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Erreur d'authentification: {str(e)}")

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> AuthUser:
    """Dependency pour obtenir l'utilisateur actuel."""
    return await verify_token(credentials)

@app.post("/upload/")
async def upload_file(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    current_user: AuthUser = Depends(get_current_user)
):
    """Endpoint pour uploader un fichier PDF ou DOCX pour l'entreprise de l'utilisateur."""
    if not file.filename.endswith(('.pdf', '.docx')):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF et DOCX sont acceptés")
    
    # Répertoire spécifique à l'entreprise
    company_data_dir = get_company_data_dir(current_user.company_id, DATA_DIR)
    file_path = os.path.join(company_data_dir, file.filename)
    
    try:
        # Enregistrer le fichier dans le répertoire de l'entreprise
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # Enregistrer les métadonnées dans la base de données
        # Récupérer le token depuis la requête actuelle
        from fastapi import Request
        from starlette.requests import Request as StarletteRequest
        
        # Note: Pour l'instant, on skip l'enregistrement automatique en DB
        # car on a besoin du token original de la requête
        # Le frontend va enregistrer directement dans Supabase
        
        # async with httpx.AsyncClient() as client:
        #     await client.post(
        #         f"{SUPABASE_URL}/rest/v1/documents",
        #         headers={
        #             "apikey": SUPABASE_ANON_KEY,
        #             "Authorization": f"Bearer {user_token}",  # TODO: récupérer le vrai token
        #             "Content-Type": "application/json"
        #         },
        #         json={
        #             "name": file.filename,
        #             "file_path": file_path,
        #             "file_size": len(content),
        #             "mime_type": file.content_type,
        #             "company_id": current_user.company_id,
        #             "uploaded_by": current_user.user_id,
        #             "processed": False
        #         }
        #     )
        
        # Reconstruire l'index en arrière-plan
        background_tasks.add_task(rebuild_company_index, current_user.company_id)
        
        return {
            "message": f"Fichier {file.filename} uploadé avec succès pour l'entreprise {current_user.company_id}",
            "company_id": current_user.company_id,
            "file_path": file_path
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'upload: {str(e)}")

def rebuild_company_index(company_id: str):
    """Fonction pour reconstruire l'index d'une entreprise (utilisée en arrière-plan)."""
    try:
        build_index(company_id, DATA_DIR, HTTPException)
        print(f"Index reconstruit avec succès pour l'entreprise {company_id}")
    except Exception as e:
        print(f"Erreur lors de la reconstruction de l'index pour l'entreprise {company_id}: {e}")

@app.post("/build_index/")
async def express_build_index(current_user: AuthUser = Depends(get_current_user)):
    """Construit l'index vectoriel pour l'entreprise de l'utilisateur."""
    try:
        vectordb = build_index(current_user.company_id, DATA_DIR, HTTPException)
        return {
            "message": f"Index construit avec succès pour l'entreprise {current_user.company_id}",
            "company_id": current_user.company_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la construction de l'index: {str(e)}")

class QuestionRequest(BaseModel):
    question: str
    langue: str = "Français"

class PublicQuestionRequest(BaseModel):
    question: str
    company_id: str
    session_id: Optional[str] = None
    external_user_id: Optional[str] = None  # Identifiant de l'utilisateur externe (optionnel)
    langue: str = "Français"

class PublicChatSession(BaseModel):
    session_id: str
    company_id: str
    external_user_id: Optional[str] = None
    title: str
    created_at: str

class PublicChatMessage(BaseModel):
    message_id: str
    session_id: str
    content: str
    role: str  # 'user' ou 'assistant'
    created_at: str

# Stockage en mémoire des sessions publiques (en production, utilisez une base de données)
public_sessions = {}
public_messages = {}

async def create_public_session(company_id: str, external_user_id: Optional[str] = None) -> PublicChatSession:
    """Crée une nouvelle session de chat publique."""
    session_id = str(uuid.uuid4())
    title = f"Conversation publique {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    
    session = PublicChatSession(
        session_id=session_id,
        company_id=company_id,
        external_user_id=external_user_id,
        title=title,
        created_at=datetime.now().isoformat()
    )
    
    public_sessions[session_id] = session
    public_messages[session_id] = []
    
    return session

async def add_public_message(session_id: str, content: str, role: str) -> PublicChatMessage:
    """Ajoute un message à une session publique."""
    message_id = str(uuid.uuid4())
    message = PublicChatMessage(
        message_id=message_id,
        session_id=session_id,
        content=content,
        role=role,
        created_at=datetime.now().isoformat()
    )
    
    if session_id not in public_messages:
        public_messages[session_id] = []
    
    public_messages[session_id].append(message)
    return message

@app.post("/ask/")
async def ask_question(
    request: QuestionRequest,
    current_user: AuthUser = Depends(get_current_user)
):
    """Endpoint pour poser une question en utilisant les documents de l'entreprise (authentifié)."""
    try:
        question_with_language = request.question + f"\nRépond toujours en *{request.langue}*"
        answer = get_answer(
            question_with_language,
            current_user.company_id,
            models.mistral_llm,
            DATA_DIR
        )
        
        return {
            "answer": answer["answer"],
            "company_id": current_user.company_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la génération de la réponse: {str(e)}")

@app.post("/ask_public/")
async def ask_question_public(request: PublicQuestionRequest):
    """Endpoint public pour poser une question sans authentification."""
    try:
        # Vérifier que l'entreprise existe en vérifiant la présence de données
        company_data_dir = get_company_data_dir(request.company_id, DATA_DIR)
        if not os.path.exists(company_data_dir):
            raise HTTPException(
                status_code=404, 
                detail=f"Entreprise {request.company_id} non trouvée ou aucun document disponible"
            )
        
        # Créer ou récupérer la session
        session_id = request.session_id
        if not session_id or session_id not in public_sessions:
            session = await create_public_session(request.company_id, request.external_user_id)
            session_id = session.session_id
        else:
            session = public_sessions[session_id]
            # Vérifier que la session appartient à la bonne entreprise
            if session.company_id != request.company_id:
                raise HTTPException(status_code=400, detail="Session non compatible avec cette entreprise")
        
        # Ajouter la question utilisateur
        await add_public_message(session_id, request.question, "user")
        
        # Générer la réponse
        question_with_language = request.question + f"\nRépond toujours en *{request.langue}*"
        answer = get_answer(
            question_with_language,
            request.company_id,
            models.mistral_llm,
            DATA_DIR
        )
        
        assistant_response = answer["answer"]
        
        # Ajouter la réponse de l'assistant
        await add_public_message(session_id, assistant_response, "assistant")
        
        return {
            "answer": assistant_response,
            "company_id": request.company_id,
            "session_id": session_id,
            "external_user_id": request.external_user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la génération de la réponse: {str(e)}")

@app.get("/sessions_public/{company_id}")
async def get_public_sessions(company_id: str, external_user_id: Optional[str] = None):
    """Récupère les sessions publiques pour une entreprise (et optionnellement un utilisateur externe)."""
    try:
        filtered_sessions = []
        for session in public_sessions.values():
            if session.company_id == company_id:
                if external_user_id is None or session.external_user_id == external_user_id:
                    filtered_sessions.append(session)
        
        return {
            "sessions": filtered_sessions,
            "company_id": company_id,
            "total": len(filtered_sessions)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des sessions: {str(e)}")

@app.get("/messages_public/{session_id}")
async def get_public_messages(session_id: str):
    """Récupère les messages d'une session publique."""
    try:
        if session_id not in public_messages:
            raise HTTPException(status_code=404, detail="Session non trouvée")
        
        messages = public_messages[session_id]
        session = public_sessions.get(session_id)
        
        return {
            "messages": messages,
            "session": session,
            "total": len(messages)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des messages: {str(e)}")

@app.get("/stats/")
async def get_stats(current_user: AuthUser = Depends(get_current_user)):
    """Retourne les statistiques de l'entreprise de l'utilisateur."""
    try:
        stats = get_company_stats(current_user.company_id, DATA_DIR)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des statistiques: {str(e)}")

@app.delete("/documents/{filename}")
async def delete_document(
    filename: str,
    background_tasks: BackgroundTasks,
    current_user: AuthUser = Depends(get_current_user)
):
    """Supprime un document physique du système de fichiers de l'entreprise."""
    try:
        # Répertoire spécifique à l'entreprise
        company_data_dir = get_company_data_dir(current_user.company_id, DATA_DIR)
        file_path = os.path.join(company_data_dir, filename)
        
        # Vérifier que le fichier existe
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Fichier {filename} non trouvé")
        
        # Vérifier que c'est bien un fichier de document (sécurité)
        if not filename.endswith(('.pdf', '.docx')):
            raise HTTPException(status_code=400, detail="Seuls les fichiers PDF et DOCX peuvent être supprimés")
        
        # Supprimer le fichier physique
        os.remove(file_path)
        
        # Reconstruire l'index en arrière-plan (pour supprimer le document de l'index)
        background_tasks.add_task(rebuild_company_index, current_user.company_id)
        
        return {
            "message": f"Document {filename} supprimé avec succès",
            "company_id": current_user.company_id,
            "filename": filename
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la suppression du document: {str(e)}")

@app.delete("/clear_cache/")
async def clear_cache(current_user: AuthUser = Depends(get_current_user)):
    """Vide le cache vectorstore de l'entreprise (admin uniquement)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
    
    try:
        clear_company_cache(current_user.company_id)
        return {
            "message": f"Cache vidé pour l'entreprise {current_user.company_id}",
            "company_id": current_user.company_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors du vidage du cache: {str(e)}")

@app.get("/documents/")
async def list_documents(current_user: AuthUser = Depends(get_current_user)):
    """Liste les documents de l'entreprise."""
    try:
        # Note: Pour l'instant, on recommande d'utiliser directement Supabase depuis le frontend
        # car c'est plus simple et sécurisé. Si vous voulez vraiment récupérer depuis le backend,
        # il faut implémenter un système pour passer le token original de l'utilisateur.
        
        # Récupérer les documents depuis le système de fichiers local
        company_data_dir = get_company_data_dir(current_user.company_id, DATA_DIR)
        documents = []
        
        if os.path.exists(company_data_dir):
            for filename in os.listdir(company_data_dir):
                if filename.endswith(('.pdf', '.docx')):
                    file_path = os.path.join(company_data_dir, filename)
                    file_size = os.path.getsize(file_path)
                    documents.append({
                        "name": filename,
                        "file_path": file_path,
                        "file_size": file_size,
                        "mime_type": "application/pdf" if filename.endswith('.pdf') else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    })
        
        return {
            "documents": documents,
            "company_id": current_user.company_id,
            "total": len(documents)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des documents: {str(e)}")

@app.get("/health/")
async def health_check():
    """Endpoint de vérification de l'état de l'API."""
    return {
        "status": "healthy",
        "message": "API RAG avec multitenancy fonctionnelle"
    }

@app.get("/")
async def root():
    """Page d'accueil de l'API."""
    return {
        "message": "Bienvenue sur l'API RAG avec multitenancy",
        "version": "2.0",
        "endpoints": {
            "/upload/": "Uploader un fichier PDF ou DOCX (authentification requise)",
            "/build_index/": "Construire l'index pour votre entreprise (authentification requise)",
            "/ask/": "Poser une question (authentification requise)",
            "/ask_public/": "Poser une question publique (aucune authentification requise)",
            "/sessions_public/{company_id}": "Lister les sessions publiques (aucune authentification requise)",
            "/messages_public/{session_id}": "Récupérer les messages d'une session publique (aucune authentification requise)",
            "/stats/": "Statistiques de votre entreprise (authentification requise)",
            "/documents/": "Lister les documents de votre entreprise (authentification requise)",
            "DELETE /documents/{filename}": "Supprimer un document physique (authentification requise)",
            "/clear_cache/": "Vider le cache (admin uniquement)",
            "/health/": "Vérification de l'état de l'API"
        },
        "public_endpoints": ["/ask_public/", "/sessions_public/", "/messages_public/", "/health/", "/"],
        "auth_required": "Bearer token JWT requis pour tous les endpoints sauf les endpoints publics"
    } 
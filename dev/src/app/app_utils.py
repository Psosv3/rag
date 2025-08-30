import os
import jwt
import uuid
from datetime import datetime
from fastapi import HTTPException, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
import httpx
from typing import Optional, Dict
from pydantic import BaseModel
from typing import Any
from llm_model.julia import julia_planner, julia_executor, PlannerOutput
import asyncio
from typing import Any, Dict, Optional
import asyncio
import json

############################################################ Variable d'Env ############################################################
load_dotenv()

# Configuration
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# Configuration Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

############################################################ Def des différentes classes ############################################################

class QuestionRequest(BaseModel):
    question: str
    langue: str = "Français"

class PublicQuestionRequest(BaseModel):
    question: str
    company_id: str
    session_id: Optional[str] = None
    external_user_id: Optional[str] = None  # Identifiant de l'utilisateur externe (optionnel)
    dry_run: Optional[str] = False
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

class AuthUser:
    def __init__(self, user_id: str, company_id: str, role: str):
        self.user_id = user_id
        self.company_id = company_id
        self.role = role

class ExecConfirmationRequest(BaseModel):
    session_id: str
    confirm: bool
    exec_plan: Dict[str, Any]  # returned from planner step
    

############################################################ Def des différentes fonctions ############################################################

def get_session_lock(session_id, session_locks) -> asyncio.Lock:
    if session_id not in session_locks:
        session_locks[session_id] = asyncio.Lock()
    return session_locks[session_id]


def load_intern_contact(company_id : str, SUPABASE_URL : str, SUPABASE_ANON_KEY : str) :
    """Charge l'ensemble des information decontact pour company_id"""
    try:
        with httpx.Client() as client:
            response = client.get(
                f"{SUPABASE_URL}/rest/v1/contacts",
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
                    "Content-Type": "application/json"
                },
                params={"company_id": f"eq.{company_id}", "select": "name,email,role,description"}
            )
            response.raise_for_status()
            rows = response.json()
            return str(rows)
    except Exception as e:
        print(f"Erreur lors du chargement des contacts: {e}")


async def load_all_companies_id(SUPABASE_URL : str, SUPABASE_ANON_KEY : str) :
    """Charge l'ensemble des unformation company id et company name"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/companies",
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
                    "Content-Type": "application/json"
                },
                params={"select": "id,name"}
            )
            response.raise_for_status()
            rows = response.json()
            companies_by_id = {
                str(row["id"]): str(row["name"]).strip()
                for row in rows
                if isinstance(row, dict) and row.get("id") is not None and row.get("name") is not None
            }
            return companies_by_id
    except Exception as e:
        print(f"Erreur lors du chargement des companies: {e}")


async def run_exec_plan_now(session_id: Optional[str], company_id: str, plan: Dict[str, Any], SUPABASE_URL : str, SUPABASE_ANON_KEY : str) -> Dict[str, Any]:
    plan = dict(plan or {})
    list_contact = load_intern_contact(company_id, SUPABASE_URL, SUPABASE_ANON_KEY)
    print(type(list_contact))
    exec_instruct = plan["exec_inst"]+f"\n\n### LISTE DES CONTACTES INTERNES ###\n\n Voici la liste des contactes dans votre entreprises. Ne l'utilisez que si vous en avez besoin, comme envoyer un email par exemple. Choisissez bien convenablement la bonne personne en fonction de son poste et de sa description de poste : \n\n<list_contact>\n"+ list_contact +"</list_contact>\n\n"
    out = await julia_executor(exec_instruct)
    out = out.replace("\\", "")
    #log_audit({"type": "executor_run_inline", "plan": plan, "result": out['message'], "session_id": session_id, "company_id": company_id}, AUDIT_LOGS)
    try :
        out = json.loads(out) 
        
        return_reponse = out['message'] + out['ask'] if  out['ask'].lower() not in ["null", "none",""] else out['message']
        if session_id:
            await add_public_message(session_id, return_reponse, "assistant")
        return return_reponse
    except : 
        return
    

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())) -> AuthUser:
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


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())) -> AuthUser:
    """Dependency pour obtenir l'utilisateur actuel."""
    return AuthUser(user_id="61dd73ab-711c-42c8-8241-d64a78fc633d",company_id="f40b912a-959d-472e-bbab-1628f04910d7",role="admin") #await verify_token(credentials) #


async def create_public_session(company_id: str, public_sessions : dict, public_messages : dict, external_user_id: Optional[str] = None) -> PublicChatSession:
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
    
    # Sauvegarder en mémoire (pour compatibilité)
    public_sessions[session_id] = session
    public_messages[session_id] = []

    # Sauvegarder dans Supabase
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SUPABASE_URL}/rest/v1/public_chat_sessions",
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                json={
                    "session_id": session_id,
                    "company_id": company_id,
                    "external_user_id": external_user_id,
                    "title": title,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat()
                }
            )
            
            if response.status_code in [200, 201]:
                print(f"Session publique sauvegardée dans Supabase: {session_id}")
            else:
                print(f"Erreur lors de la sauvegarde de la session dans Supabase: {response.status_code} - {response.text}")
                
    except Exception as e:
        print(f"Erreur lors de la sauvegarde de la session dans Supabase: {e}")
    
    return (session, public_sessions, public_messages)


async def add_public_message(session_id: str, content: str, role: str, public_messages : dict) -> PublicChatMessage:
    """Ajoute un message à une session publique."""
    message_id = str(uuid.uuid4())
    message = PublicChatMessage(
        message_id=message_id,
        session_id=session_id,
        content=content,
        role=role,
        created_at=datetime.now().isoformat()
    )
    
    # Sauvegarder en mémoire (pour compatibilité)
    if session_id not in public_messages:
        public_messages[session_id] = []
    
    public_messages[session_id].append(message)
    
    # Sauvegarder dans Supabase
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SUPABASE_URL}/rest/v1/public_chat_messages",
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                json={
                    "message_id": message_id,
                    "session_id": session_id,
                    "content": content,
                    "role": role,
                    "created_at": datetime.now().isoformat()
                }
            )
            
            if response.status_code in [200, 201]:
                print(f"Message public sauvegardé dans Supabase: {message_id}")
            else:
                print(f"Erreur lors de la sauvegarde du message dans Supabase: {response.status_code} - {response.text}")
                
    except Exception as e:
        print(f"Erreur lors de la sauvegarde du message dans Supabase: {e}")
    
    return message


async def load_public_session_from_supabase(session_id: str, public_sessions: dict, public_messages: dict) -> Optional[PublicChatSession]:
    """Charge une session publique depuis Supabase."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SUPABASE_URL}/rest/v1/public_chat_sessions",
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
                    "Content-Type": "application/json"
                },
                params={"session_id": f"eq.{session_id}"}
            )
            
            if response.status_code == 200:
                sessions_data = response.json()
                if sessions_data:
                    session_data = sessions_data[0]
                    session = PublicChatSession(
                        session_id=session_data["session_id"],
                        company_id=session_data["company_id"],
                        external_user_id=session_data.get("external_user_id"),
                        title=session_data["title"],
                        created_at=session_data["created_at"]
                    )
                    
                    # Charger en mémoire pour compatibilité
                    public_sessions[session_id] = session
                    
                    # Charger les messages
                    messages_response = await client.get(
                        f"{SUPABASE_URL}/rest/v1/public_chat_messages",
                        headers={
                            "apikey": SUPABASE_ANON_KEY,
                            "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
                            "Content-Type": "application/json"
                        },
                        params={
                            "session_id": f"eq.{session_id}",
                            "order": "created_at.asc"
                        }
                    )
                    
                    if messages_response.status_code == 200:
                        messages_data = messages_response.json()
                        messages = []
                        for msg_data in messages_data:
                            message = PublicChatMessage(
                                message_id=msg_data["message_id"],
                                session_id=msg_data["session_id"],
                                content=msg_data["content"],
                                role=msg_data["role"],
                                created_at=msg_data["created_at"]
                            )
                            messages.append(message)
                        
                        public_messages[session_id] = messages
                    
                    # print(f"Session publique chargée depuis Supabase: {session_id}")
                    return (session, public_sessions, public_messages)
                    
    except Exception as e:
        print(f"Erreur lors du chargement de la session depuis Supabase: {e}")
    
    return None
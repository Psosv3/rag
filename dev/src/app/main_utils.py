import os
import json
import uuid
import hashlib
import asyncio
import aiofiles
from pathlib import Path
from typing import Optional, List, Any, Dict, Optional, Annotated
from operator import itemgetter
from dotenv import load_dotenv
# FastAPI
from fastapi import FastAPI, Depends, UploadFile, HTTPException, Request, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
# Pydantic
from pydantic import BaseModel, AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
# DataBase
from redis.asyncio import Redis, ConnectionPool
from supabase import AsyncClient
import jwt
# Models
from llm_model.julia import julia_planner, julia_executor, PlannerOutput
# Utils
from utils.utils import extract_emails, extract_intern_emails, check_difference, strip_emails

###################################################### Class definitions ######################################################
load_dotenv()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    SUPABASE_URL: str = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    REDIS_URL: str = os.getenv("REDIS_URL")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM")
    JWT_SECRET: str = os.getenv("JWT_SECRET")
    JWT_AUDIENCE: Optional[str] = None
    JWT_ISSUER: Optional[str] = None
    ALLOW_ORIGINS: List[AnyHttpUrl] = os.getenv("ALLOW_ORIGINS")
    HEARTBEAT_SEC: int = os.getenv("HEARTBEAT_SEC")
    TASK_TIMEOUT_SEC: int = os.getenv("TASK_TIMEOUT_SEC")
    MAX_UPLOAD_MB: int = os.getenv("MAX_UPLOAD_MB")
    ALLOWED_UPLOAD_EXTS: tuple = (".pdf", ".docx")

class AuthUser(BaseModel):
    sub: str
    company_id: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None

class PublicQuestionRequest(BaseModel):
    company_id: str
    external_user_id: Optional[str] = None
    question: str
    langue: Optional[str] = None


###################################################### Table names ######################################################
TABLE_SESSION = "public_chat_sessions"
TABLE_MESSAGE = "public_chat_messages"
TABLE_COMPANY = "companies"
TABLE_CONTACTS = "contacts"
TOOL_SEND_EMAIL= "smtp_email_sender"

###################################################### Other consts : Keys and helpers ######################################################
EXT_SESS_KEY = "ext_sess:{company_id}"          # HSET external_user_id -> session_id
BAN_SET_KEY  = "ban:{company_id}"               # SET of banned session_ids
RAG_CTX_KEY  = "rag:ctx:{company_id}:{qhash}"   # SETEX with doc snippets
AUDIT_LIST_KEY = "audit_logs"                   # LPUSH audit events
_DEFAULT_Q_MAX = 1_024  
LIST_TEMP_RESP = [
    "D'accord. Je regarde un instant et je reviens vers vous.",
    "Très bien. Un instant, je reviens vers vous.",
    "Entendu. Je regarde un instant.",
    "D'accord. Je fais le point et je vous reviens.",
    "OK. Je vérifie en interne et je reviens vers vous.",
    "Entendu. Laissez-moi un instant, je reviens vers vous.",
    "Très bien. Je me charge de cela et je vous tiens informé.",
    "Ok. Je reviens vers vous rapidement.",
    "D'accord. Je vois de mon côté et je reviens vers vous au plus vite.",
]
LIST_TEMP_ATTENTE = [
    "Merci de patienter encore un instant.",
    "J'y arrive, merci de votre patience.",
    "Encore un petit moment, svp.",
    "Je finalise, merci d'attendre.",
    "Ça arrive, laissez-moi encore quelques minute svp, merci.",
    "Laissez-moi encore quelques minute svp, merci.",
    "Un court instant supplémentaire, merci."
]

###################################################### settings ######################################################
settings = Settings()


###################################################### Redis (async, shared pool) ######################################################
redis_pool = ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True, max_connections=200)
redis_client = Redis(connection_pool=redis_pool)

async def get_redis() -> Redis:
    return redis_client


###################################################### Security (JWT) ######################################################
security = HTTPBearer(auto_error=True)

def decode_jwt_token(token: str) -> dict:
    options = {"verify_signature": True, "verify_exp": True}
    decode_kwargs = {"algorithms": [settings.JWT_ALGORITHM], "options": options}
    if settings.JWT_AUDIENCE:
        decode_kwargs["audience"] = settings.JWT_AUDIENCE
    if settings.JWT_ISSUER:
        decode_kwargs["issuer"] = settings.JWT_ISSUER
    payload = jwt.decode(token, settings.JWT_SECRET, **decode_kwargs)
    return payload

async def get_current_user(credentials: Annotated[HTTPAuthorizationCredentials, Security(security)]) -> AuthUser:
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid auth scheme")
    try:
        payload = decode_jwt_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    sub = payload.get("sub") or payload.get("user_id")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing sub claim")
    return AuthUser(
        sub=sub,
        company_id=payload.get("company_id"),
        role=payload.get("role") or payload.get("app_role"),
        email=payload.get("email"),
    )

###################################################### Supabase ######################################################
async def get_supabase(request: Request) -> AsyncClient:
    spbase: AsyncClient = request.app.state.spbase  # type: ignore[attr-defined]
    return spbase

async def get_or_create_session(
    spbase: AsyncClient, r: Redis, company_id: str, external_user_id: Optional[str]
) -> dict:
    # Fast path via Redis
    if external_user_id:
        session_id = await r.hget(EXT_SESS_KEY.format(company_id=company_id), external_user_id)
        if session_id:
            res = await spbase.table(TABLE_SESSION).select("*").eq("session_id", session_id).limit(1).execute()
            row = first_row(res)
            if row:
                return row[0]

    # Lookup existing
    if external_user_id:
        res = await spbase.table(TABLE_SESSION)\
            .select("*")\
            .eq("company_id", company_id)\
            .eq("external_user_id", external_user_id)\
            .limit(1)\
            .execute()
        existing = first_row(res)
        if existing:
            await r.hset(EXT_SESS_KEY.format(company_id=company_id), external_user_id, existing["session_id"])
            return existing

    # Create new
    ins = await spbase.table(TABLE_SESSION)\
        .insert({"company_id": company_id, "external_user_id": external_user_id})\
        .execute()
    sess = first_row(ins)
    if not sess:
        raise HTTPException(status_code=500, detail="Invalid session object")
    if external_user_id:
        await r.hset(EXT_SESS_KEY.format(company_id=company_id), external_user_id, sess["session_id"])
    return sess


async def save_supabase_message(spbase: AsyncClient, session_id: str, role: str, content: str) -> dict:
    message_id = str(uuid.uuid4())
    res = await spbase.table(TABLE_MESSAGE)\
        .insert({"message_id": message_id, "session_id": session_id, "role": role, "content": content})\
        .execute()
    return first_row(res) or {}


async def list_messages(spbase: AsyncClient, session_id: str, limit: int = 200) -> List[dict]:
    res = await spbase.table(TABLE_MESSAGE)\
        .select("role,content,created_at")\
        .eq("session_id", session_id)\
        .order("created_at", desc=False)\
        .limit(limit)\
        .execute()
    return res.data or []

###################################################### Conversation utils ######################################################

def validate_question(question: str, max_len: int = _DEFAULT_Q_MAX) -> str:
    """
    Basic abuse-prevention for LLM prompts.
    • Strips leading/trailing whitespace.
    • Collapses internal new-lines to single spaces.
    • Enforces max length.
    """
    if not question or not question.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Demande utilisateur vide")

    cleaned = " ".join(question.strip().split())

    if len(cleaned) > max_len:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"La question dépasse la limite autorisée de {max_len} caractères")

    return cleaned

async def is_banned(r: Redis, company_id: str, session_id: str) -> bool:
    return bool(await r.sismember(BAN_SET_KEY.format(company_id=company_id), session_id))


async def forbiden_session(r: Redis, company_id: str, session_id: str):
    await r.sadd(BAN_SET_KEY.format(company_id=company_id), session_id)


###################################################### Cache rag ######################################################

async def cache_rag_docs(r: Redis, company_id: str, question: str, docs: list, ttl_seconds: int = 300):
    key = RAG_CTX_KEY.format(company_id=company_id, qhash=qhash(question))
    await r.setex(key, ttl_seconds, json.dumps(docs))

async def get_cached_rag_docs(r: Redis, company_id: str, question: str) -> Optional[list]:
    key = RAG_CTX_KEY.format(company_id=company_id, qhash=qhash(question))
    raw = await r.get(key)
    return json.loads(raw) if raw else None

###################################################### Keys and helpers ######################################################
def qhash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

async def log_audit(r: Redis, event: dict) -> None:
    await r.lpush(AUDIT_LIST_KEY, json.dumps(event)[:4000])

def first_row(obj):
    """Normalize Supabase responses to a single dict row."""
    data = getattr(obj, "data", obj)
    if isinstance(data, list):
        return data if data else None
    if isinstance(data, dict):
        return data
    return None


###################################################### Companies cache ######################################################
async def refresh_companies_into_state(app: FastAPI):
    spbase: AsyncClient = app.state.spbase  # type: ignore[attr-defined]
    res = await spbase.table(TABLE_COMPANY).select("id, name").execute()
    data = res.data or []
    companies = {
        row["id"]: row["name"]
        for row in data
        if row and row.get("id") and row.get("name")
    }
    app.state.companies = companies
    # Update Redis with pipelined delete + hset to reduce RTTs
    if companies:
        pipe = redis_client.pipeline()
        pipe.delete("companies")
        pipe.hset("companies", mapping=companies)
        await pipe.execute()
    else:
        await redis_client.delete("companies")

async def get_company_name(app: FastAPI, company_id: str) -> str:
    if hasattr(app.state, "companies") and company_id in app.state.companies:
        return app.state.companies[company_id]
    name = await redis_client.hget("companies", company_id)
    return name or "votre entreprise"


###################################################### Upload helpers ######################################################
def sanitize_filename(original: str) -> str:
    ext = Path(original).suffix.lower()
    name = uuid.uuid4().hex
    return f"{name}{ext}"

async def safe_write_file(final_path: Path, up: UploadFile, max_bytes: int) -> None:
    """Persist an UploadFile to disk without blocking the event-loop."""

    tmp_path = final_path.with_suffix(final_path.suffix + ".part")
    total = 0

    async with aiofiles.open(tmp_path, "wb") as f:
        while True:
            chunk = await up.read(1_048_576) # Streams data in 1 MiB increments using aiofiles.
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes: # Enforces a per-file size limit (max_bytes).
                await f.close() # Abort early, delete partial file, propagate error
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"Fichier trop volumineux. Taille max : {max_bytes/(1024*1024)} MB")
            await f.write(chunk)

    tmp_path.replace(final_path)

###################################################### Upload helpers ######################################################
async def run_executor_agent(supabase,
                            session_id: Optional[str],
                            company_id: str,
                            exec_plan: Dict[str, Any],
                            ) -> Dict[str, Any]:
    exec_plan = dict(exec_plan or {})
    exec_instruct = exec_plan["exec_inst"] 
    if TOOL_SEND_EMAIL in [d.name for d in exec_plan['tools_to_call']]  :
        list_contact = await load_intern_contact(supabase, company_id)
        instruct_email_list = extract_emails(exec_instruct) or []
        intern_email_list = list(map(itemgetter("email"), list_contact)) #extract_intern_emails(str(list_contact)) or []
        verif, list_intrus = check_difference(instruct_email_list, intern_email_list)         # verification des emails authorisés 
        if verif :
            exec_instruct = strip_emails(exec_instruct) + f"\n\n### LISTE DES CONTACTS INTERNES ###\n\n Voici la liste des contacts privés dans votre entreprise. Ne l'utilisez que si vous en avez besoin, comme contacter un responsable ou envoyer un email par exemple. Choisissez bien convenablement la bonne personne en fonction de son poste et de sa description de poste : \n\n<list_contact>\n"+ str(list_contact) +"\n</list_contact>\n\n"
        else :
            await save_supabase_message(supabase, session_id, "assistant", f"Je suis désolé, je me rends compte que je ne suis pas autorisé à envoyer l'email au destinataire : {', '.join(intru for intru in list_intrus)}.")
            return
    print(f"++++{exec_instruct}")
    out = await julia_executor(exec_instruct)
    try :
        out = json.loads(out) 
        return_reponse = out['message'] + out['ask'] if  out['ask'].lower() not in ["null", "none",""] else out['message']
        if session_id:
            await save_supabase_message(supabase, session_id, "assistant", return_reponse)
        return return_reponse
    except Exception as e:
        print(f"Erreur output julia: {e}")

def sse_data(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    #return f"{json.dumps(payload, ensure_ascii=False)}"

async def load_intern_contact(sp: AsyncClient, company_id: str) -> List[Dict[str, Any]]:
    """
    Charge les contacts internes pour une entreprise donnée (async, une seule requête).
    Retourne une liste de dictionnaires: [{name, email, role, description}, ...].
    """
    res = await sp.table(TABLE_CONTACTS) \
                  .select("name,email,role,description") \
                  .eq("company_id", company_id) \
                  .execute()
    return res.data or []
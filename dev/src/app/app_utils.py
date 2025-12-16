import os
import json
import shutil
import uuid
import hashlib
import aiofiles
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Any, Dict, Optional
from operator import itemgetter
from io import BytesIO
import docx
from PyPDF2 import PdfReader
from dotenv import load_dotenv
from zipfile import BadZipFile
# FastAPI
from fastapi import FastAPI, Depends, UploadFile, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.concurrency import run_in_threadpool
# Pydantic
from pydantic import BaseModel, AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
# DataBase
from redis.asyncio import Redis, ConnectionPool
from redis.exceptions import RedisError
from supabase import AsyncClient
import jwt
# Models
from llm_model.onexia import onexia_executor, onexia_escalator
from llm_model.model_file import _save_upload_file_streaming, generate_image_path, _delete_saved_image
from llm_model.model_server import image_model, image_core_model, voice_core_model, voice_model
# Rag
from rag.rag import rewrite_rag_augmentor
# Utils
from utils.utils import encode_image, save_to_pdf, save_to_docx, extract_emails, sanitize_translate, check_difference, strip_emails, maintenant_fr, ZoneInfo
# security encrypt/decrypt message
from security.security import encrypt, decrypt

###################################################### Class definitions ######################################################
load_dotenv()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    SUPABASE_URL: str = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    SUPABASE_JWT_SECRET: str = os.getenv("SUPABASE_JWT_SECRET")    
    REDIS_URL: str = os.getenv("REDIS_URL")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM")
    JWT_AUDIENCE: Optional[str] = "authenticated"
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
    messenger: Optional[bool] = False
    file: Optional[UploadFile] = None
    audio: Optional[UploadFile] = None

class FeedbackRequest(BaseModel):
    session_id: str
    message_id: str
    feedback: str  # 'like' ou 'dislike'
    company_id: str


###################################################### Table names ######################################################
TABLE_SESSION = "public_chat_sessions"
TABLE_MESSAGE = "public_chat_messages"
TABLE_COMPANY = "companies"
TABLE_COMPANY_INTEGRATIONS = "company_integrations"
TABLE_CONTACTS = "contacts"
TABLE_USER_PROFILES = "user_profiles"
TOOL_SEND_EMAIL= "smtp_email_sender"

###################################################### Other consts : Keys and helpers ######################################################
EXT_SESS_KEY = "ext_sess:{company_id}"          # HSET external_user_id -> session_id
BAN_KEY  = "ban:{company_id}:{session_id}"  # SET of banned session_ids
RAG_CTX_KEY  = "rag:ctx:{company_id}:{qhash}"   # SETEX with doc snippets
ESCALATE_SET_KEY = "escalate:{company_id}"      # SET of escalated session_ids

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
LIST_ESCALATE_RESP =[
    "D'accord. Je vais transférer votre demande à mon responsable. Mais avant, pourriez-vous me communiquer votre nom ainsi que vos coordonnées (adresse e-mail et/ou numéro de téléphone) ?",
    "Très bien, je vais transférer votre demande à un responsable. Afin de la transférer dans les meilleures conditions, auriez-vous l’amabilité de me donner votre nom et vos coordonnées (adresse e-mail et/ou numéro de téléphone) ?",
    "Ok. Je vais transférer votre demande à mon responsable. Pour assurer un suivi efficace, puis-je avoir votre nom et vos coordonnées (adresse e-mail et/ou numéro de téléphone) ?",
    "D'accord. Je vais contacter mon responsable pour qu'il prenne votre cas en charge. Mais avant de passer le relais, puis-je avoir votre nom et vos coordonnées (adresse e-mail et/ou numéro de téléphone) ?",
    "C'est noté. Je vais transférer votre demande à mon responsable. Pourriez-vous, s’il vous plaît, me partager votre nom et vos coordonnées (adresse e-mail et/ou numéro de téléphone) pour faciliter la suivie ?",
    "Pour faciliter la prise en charge par mon responsable, merci de me communiquer votre nom ainsi que vos coordonnées (adresse e-mail et/ou numéro de téléphone).",
    "Je vais transmettre votre demande à mon responsable ; pourriez-vous d’abord m’indiquer votre nom et vos coordonnées (adresse e-mail et/ou numéro de téléphone) ?"
]

ALLOWED_FILES_TYPES: Dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

###################################################### settings ######################################################
settings = Settings()


###################################################### Redis (async, shared pool) ######################################################
redis_pool = ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True, max_connections=200)
redis_client = Redis(connection_pool=redis_pool)

async def get_redis() -> Redis:
    return redis_client


###################################################### Security (JWT) ######################################################
security = HTTPBearer()

def decode_jwt_token(token: str) -> dict:
    options = {"verify_signature": True, "verify_exp": True}
    decode_kwargs = {"algorithms": [settings.JWT_ALGORITHM], "options": options}
    if settings.JWT_AUDIENCE:
        decode_kwargs["audience"] = settings.JWT_AUDIENCE
    if settings.JWT_ISSUER:
        decode_kwargs["issuer"] = settings.JWT_ISSUER
    payload = jwt.decode(token, settings.SUPABASE_JWT_SECRET, **decode_kwargs)
    return payload

async def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> AuthUser:
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid auth scheme")
    try:
        payload = decode_jwt_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    sub = payload.get("sub") or payload.get("user_id")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing sub claim")
    spbase: AsyncClient = request.app.state.spbase
    response = await spbase.table(TABLE_USER_PROFILES) \
                  .select("company_id,role") \
                  .eq("user_id", sub) \
                  .execute()
    current_user = AuthUser(
        sub=sub,
        company_id=response.data[0]["company_id"],
        role=response.data[0]["role"],
        email=payload.get("email"),
    )

    return current_user

###################################################### Supabase #######################################################
async def get_supabase(request: Request) -> AsyncClient:
    spbase: AsyncClient = request.app.state.spbase  # type: ignore[attr-defined]
    return spbase

async def get_or_create_session(spbase : AsyncClient, redis: Redis, company_id: str, external_user_id: str | None, messenger: bool = False) -> dict:

    key = EXT_SESS_KEY.format(company_id=company_id)

    # 1) Fast path via Redis (tolerate cache outages)
    session_id = None
    if external_user_id:
        try:
            session_id = await redis.hget(key, str(external_user_id))
        except RedisError:
            session_id = None  # degrade to DB path

    if session_id:
        try:
            res = (
                await spbase.table(TABLE_SESSION)
                .select("*")
                .eq("session_id", session_id)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            if rows:
                return rows[0]
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Session lookup failed : {str(e)}")

    # 2) DB lookup by composite key
    existing = None
    if external_user_id:
        try:
            res = (
                await spbase.table(TABLE_SESSION)
                .select("*")
                .eq("company_id", company_id)
                .eq("external_user_id", external_user_id)
                .limit(1)
                .execute()
            )
            rows = getattr(res, "data", None) or []
            existing = rows[0] if rows else None
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Session query failed : {str(e)}")

        if existing:
            try:
                await redis_client.hset(key, str(external_user_id), str(existing["session_id"]))
                # Optional TTL to control growth:
                # await redis_client.expire(key, 7200)
            except RedisError:
                pass  # do not fail the request on cache errors
            return existing

    # 3) Create or update atomically (idempotent)
    try:
        title = f"Conversation publique {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        # Requires UNIQUE(company_id, external_user_id) in DB schema
        ins = (
            await spbase.table(TABLE_SESSION)
            .upsert(
                {"company_id": company_id,
                 "external_user_id": external_user_id,
                 "session_id": str(uuid.uuid4()),
                 "title": title,
                 "messenger": messenger,
                 "created_at": datetime.now().isoformat(),
                 "updated_at": datetime.now().isoformat()
                 },
                ignore_duplicates=False,
                returning="representation", 
            )
            .execute()
        )
        data = getattr(ins, "data", None) or []
        session = data[0] if data else None
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Session upsert failed : {str(e)}")

    if not session:
        raise HTTPException(status_code=500, detail="Invalid session object")

    if external_user_id:
        try:
            await redis.hset(key, str(external_user_id), str(session["session_id"]))
            # Optional TTL:
            # await redis_client.expire(key, 7200)
        except RedisError:
            pass

    return session


async def save_supabase_message(spbase: AsyncClient,
                                session_id: str,
                                role: str,
                                content: str,
                                original_content: str,
                                user_language: str,
                                manual_response: bool=False,
                                stop_discuss_reason: Optional[str] = None) -> dict:
    message_id = str(uuid.uuid4())
    res = await spbase.table(TABLE_MESSAGE)\
        .insert({"message_id": message_id,
                 "session_id": session_id,
                 "role": role,
                 "content": encrypt(content),
                 "original_content": encrypt(original_content),
                 "user_language": user_language,
                 "stop_discuss_reason": encrypt(stop_discuss_reason) if stop_discuss_reason else ""})\
        .execute()
    
    if manual_response:
        await spbase.table(TABLE_SESSION)\
            .update({"manual_response": manual_response})\
            .eq("session_id", session_id)\
            .execute()

    result = first_row(res)
    if isinstance(result, list) and result:
        result = result[0]  # Prendre le premier élément de la liste
    elif not result:
        result = {}
    result["message_id"] = message_id  # S'assurer que le message_id est retourné
    return result

async def create_notification(
    spbase: AsyncClient,
    company_id: str,
    notification_type: str,
    title: str,
    content: str,
    session_id: Optional[str] = None,
    message_id: Optional[str] = None,
    priority: str = "normal",
    metadata: Optional[Dict[str, Any]] = None,
    action_url: Optional[str] = None,
    action_label: Optional[str] = None
) -> dict:
    """
    Fonction flexible pour créer n'importe quel type de notification
    
    Args:
        spbase: Client Supabase
        company_id: ID de l'entreprise
        notification_type: Type de notification (ex: 'manual_response_required', 'negative_feedback')
        title: Titre court
        content: Description détaillée
        session_id: ID de session (optionnel)
        message_id: ID de message (optionnel)
        priority: Priorité ('low', 'normal', 'high', 'urgent')
        metadata: Données supplémentaires en JSON
        action_url: URL d'action (optionnel)
        action_label: Label du bouton d'action (optionnel)
    """
    notification_data = {
        "company_id": company_id,
        "type": notification_type,
        "title": title,
        "content": content,
        "priority": priority,
        "read": False,
        "created_at": datetime.now().isoformat()
    }
    
    # Ajouter les champs optionnels seulement s'ils sont fournis
    if session_id:
        notification_data["session_id"] = session_id
    if message_id:
        notification_data["message_id"] = message_id
    if metadata:
        notification_data["metadata"] = metadata
    if action_url:
        notification_data["action_url"] = action_url
    if action_label:
        notification_data["action_label"] = action_label
    
    try:
        res = await spbase.table("notifications").insert(notification_data).execute()
        result = first_row(res)
        if isinstance(result, list) and result:
            return result[0]
        return result if result else {}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur lors de la création de la notification: {str(e)}")


async def get_or_write_company_resume(spbase: AsyncClient, company_id: str, action: str, resume_text: Optional[str] = None) :
    if action == "get":
        res = await spbase.table(TABLE_COMPANY_INTEGRATIONS)\
            .select("company_resume")\
            .eq("company_id", company_id)\
            .execute()
        data = res.data or []
        return data[0].get("company_resume") if data else None
    
    elif action == "write":
        if resume_text:
            await spbase.table(TABLE_COMPANY_INTEGRATIONS)\
                .update({"company_resume": resume_text})\
                .eq("company_id", company_id)\
                .execute()
        return None
    
    else:
        return None

async def list_messages(spbase: AsyncClient, session_id: str, limit: int = 200) -> List[dict]:
    res = await spbase.table(TABLE_MESSAGE)\
        .select("message_id,role,content,created_at")\
        .eq("session_id", session_id)\
        .order("created_at", desc=False)\
        .limit(limit)\
        .execute()
    rows = res.data or []
    rows = [
        {**row, "content": decrypt(row.get("content"))}for row in rows]
    return rows


async def messenger_wait_human(sp: AsyncClient, session_id: str) ->  bool:
    """ Check si la session est une session messenger en attente d'un humain """
    res = await sp.table(TABLE_SESSION) \
                  .select("manual_response,messenger") \
                  .eq("session_id", session_id) \
                  .execute()
    data = res.data or []
    if data and data[0].get("manual_response") == True and data[0].get("messenger") == True:
        return True
    return False

async def stop_chatbot(sp: AsyncClient, company_id: str) ->  bool:
    """ Retrieve the chatbot status of the company """
    res = await sp.table(TABLE_COMPANY_INTEGRATIONS) \
                  .select("general_manual_response") \
                  .eq("company_id", company_id) \
                  .execute()
    data = res.data or []
    if data and data[0].get("general_manual_response") == True:
        return True
    return False

def build_chat_messages(messages_history,           # List[PublicChatMessage] triée chronologiquement
                        user_input: str,            # request.question
                        context : str,              # context RAG
                        system_message: str,        # instructions globales
                        dev_message: str,           # developper messsage
                        max_history_pairs: int = 100 # garde-fou contexte
                        ):

    # 0) a) System
    messages = [{"role": "system", "content": system_message.strip()}]
    # 0) b) Developper
    _dev_message = dev_message.strip()+ f"###\n\n Voici le contexte RAG contenant des informations de votre entreprise pour répondre à la question du client. \n\n<CONTEXT_RAG>\n" + context +"\n</CONTEXT_RAG>\n\n"
    
    messages.append({"role": "developer", "content": _dev_message})

    # 1) Historique récent (on tronque si trop long)
    # On garde les derniers N messages (hors system - par construction supabase). Affinge possible avec une mesure de tokens.
    hist = messages_history[-(max_history_pairs*2):-1] if max_history_pairs else messages_history[:-1]

    for msg in hist:
        r = msg["role"].lower()
        if r == "user":
            messages.append({"role": "user", "content": msg["content"]})
        elif r == "assistant":
            messages.append({"role": "assistant", "content": msg["content"]})
        # Si tu supportes un jour des messages "tool" persistés, ajoute leur mapping ici.

    # 2) Tour courant user
    messages.append({"role": "user", "content": user_input})

    return messages


###################################################### Conversation utils & redis ######################################################

def validate_quest_length(question: str, max_len: int = _DEFAULT_Q_MAX) -> str:
    """
    Basic abuse-prevention for long LLM prompts.
    """
    if not question or not question.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Demande utilisateur vide")
    cleaned = " ".join(question.strip().split())
    return (len(cleaned) > max_len, cleaned)


###################################################### files processing ######################################################

async def process_file(upload_file: UploadFile, max_size_mb: int, allowed_types: Optional[dict]) -> str:
    ext = Path(upload_file.filename).suffix.lower()
    mime_guess, _ = mimetypes.guess_type(upload_file.filename)
    mime_hint = (mime_guess or upload_file.content_type or "").lower()

    if upload_file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Unsupported image type")
    if (ext == ".jpg" or ext == ".jpeg") and "jpeg" not in mime_hint: # Make sure the extension and MIME type agree
        raise HTTPException(status_code=400, detail="MIME type mismatch for jpeg/jpg")
    if ext == ".png" and "png" not in mime_hint:
        raise HTTPException(status_code=400, detail="MIME type mismatch for png")
    if ext == ".webp" and "webp" not in mime_hint:
        raise HTTPException(status_code=400, detail="MIME type mismatch for webp")
    
    dest_path = generate_image_path(upload_file.content_type, allowed_types)
    # Offload blocking file I/O to threadpool for high concurrency.
    try:
        await run_in_threadpool(_save_upload_file_streaming, upload_file, dest_path, max_size_mb * 1024 * 1024)
    finally:
        # Always close and delete the underlying file descriptor.
        upload_file.file.close()

    base64_image = encode_image(dest_path)
    chat_completion = await image_model.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Liste moi en détail ce que tu vois dans cette image. Sois concis, précis mais complet. Interdiction d'inventer et de donner des informations non présentes dans l'image."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{upload_file.content_type};base64,{base64_image}",
                        },
                    },
                ],
            }
        ],
        model=image_core_model,
    )
    content_file = chat_completion.choices[0].message.content
    _delete_saved_image(dest_path)
    return content_file


async def transcribe_audio_to_text(filepath, audio, client=voice_model, core_model=voice_core_model) -> str:
    try:
        # Save uploaded audio to a temporary file
        with filepath.open("wb") as f:
            while True:
                chunk = await audio.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                f.write(chunk)

        await audio.close()

        with open(filepath, "rb") as file:
            transcription = await client.audio.transcriptions.create(file=(filepath, file.read()),
                                                                     model=core_model,
                                                                     temperature=0,
                                                                     response_format="verbose_json",
                                                                     )
            return str(transcription.text).strip()
    except Exception as e:  
            raise HTTPException(status_code=500, detail=f"Audio transcription failed: {str(e)}")


###################################################### Conversation helpers ######################################################

async def prep_input_embed(conv_history: List[dict], user_question: str, len_hist: int = 3) -> str:
    """
    Prépare l'historique de conversation pour l'embedding.
    Concatène les N dernières messages de l'utilisateur en une seule chaîne de texte à embeder + rajout x2 de la question courante pour la donner plus de poids.
    objectif: ne pas perdre le contexte récent.
    """
    messages = []
    for msg in conv_history[-len_hist*2:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            messages.append(f"{content}")
    return " ".join(messages)+" "+str(user_question).strip() if len(conv_history[-len_hist*2:]) >= len_hist*2 else " ".join(messages)

async def is_banned(r: Redis, company_id: str, session_id: str) -> bool:
    return bool(await r.exists(BAN_KEY.format(company_id=company_id, session_id=session_id)))

async def forbiden_session(r: Redis, company_id: str, session_id: str):
    await r.set(BAN_KEY.format(company_id=company_id, session_id=session_id), "1", ex=86400)

async def add_escalate_session(r: Redis, company_id: str, session_id: str):
    await r.sadd(ESCALATE_SET_KEY.format(company_id=company_id), session_id)

async def is_ready_to_escalate(r: Redis, company_id: str, session_id: str) -> bool:
    return bool(await r.sismember(ESCALATE_SET_KEY.format(company_id=company_id), session_id))

async def remove_escalate_session(r: Redis, company_id: str, session_id: str) -> bool:
    await r.srem(ESCALATE_SET_KEY.format(company_id=company_id), session_id)

###################################################### Cache rag ######################################################

async def cache_rag_docs(r: Redis, company_id: str, question: str, docs: list, ttl_seconds: int = 300):
    key = RAG_CTX_KEY.format(company_id=company_id, qhash=qhash(question))
    await r.setex(key, ttl_seconds, json.dumps(docs))

async def get_cached_rag_docs(r: Redis, company_id: str, question: str) -> Optional[list]:
    key = RAG_CTX_KEY.format(company_id=company_id, qhash=qhash(question))
    raw = await r.get(key)
    return json.loads(raw) if raw else None

async def clear_all_cached_rag_docs(redis, company_id: str) -> int:
    """
    Supprime tous les caches RAG d'une entreprise (toutes questions).
    Retourne le nombre de clés supprimées.
    """
    pattern = RAG_CTX_KEY.format(company_id=company_id, qhash="*")
    deleted = 0
    async for key in redis.scan_iter(match=pattern):
        deleted += await redis.unlink(key)
    return deleted



###################################################### Keys and helpers ######################################################
def qhash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

async def log_audit(r: Redis, event: dict) -> None:
    await r.lpush(AUDIT_LIST_KEY, json.dumps(event, ensure_ascii=False)[:4000])

def first_row(obj):
    """Normalize Supabase responses to a single dict row."""
    data = getattr(obj, "data", obj)
    if isinstance(data, list):
        return data if data else None
    if isinstance(data, dict):
        return data
    return None


###################################################### Companies cache ######################################################
async def refresh_companies_into_state(app: FastAPI) -> None:
    """
    Recharge companies & resumes en mémoire et dans Redis.
    """
    spbase = getattr(app.state, "spbase", None)
    if spbase is None:
        return

    try:
        res = await spbase.table(TABLE_COMPANY_INTEGRATIONS).select("company_id, companies(name), company_resume, chatbot_signature, extra_prompt").execute()
        rows = res.data or []

        companies = {r["company_id"]: str(r["companies"]["name"]) for r in rows if r and r.get("company_id") and r.get("companies") and r["companies"].get("name")}
        company_resumes = {r["company_id"]: str(r["company_resume"]) for r in rows if r and r.get("company_id") and r.get("company_resume")}
        company_signatures = {r["company_id"]: str(r["chatbot_signature"]) for r in rows if r and r.get("company_id") and r.get("chatbot_signature")}
        company_extra_prompt = {r["company_id"]: str(r["extra_prompt"]) for r in rows if r and r.get("company_id") and r.get("extra_prompt")}

        # État en mémoire
        app.state.companies = companies
        app.state.company_resumes = company_resumes
        app.state.company_signatures = company_signatures
        app.state.company_extra_prompt = company_extra_prompt

        # Redis: delete puis (re)write, en 1 pipeline
        pipe = redis_client.pipeline()
        pipe.delete("companies", "company_resumes", "company_signatures", "company_extra_prompt")
        if companies:
            pipe.hset("companies", mapping=companies)
        if company_resumes:
            pipe.hset("company_resumes", mapping=company_resumes)
        if company_signatures:
            pipe.hset("company_signatures", mapping=company_signatures)
        if company_extra_prompt:
            pipe.hset("company_extra_prompt", mapping=company_extra_prompt)
        await pipe.execute()
    except Exception as e:
        print(e)
        return 

async def get_company_name_resume_prompt_signature(app: FastAPI, company_id: str) -> tuple[str, Optional[str]]:
    companies = getattr(app.state, "companies", {})
    resumes = getattr(app.state, "company_resumes", {})
    extra_prompts = getattr(app.state, "company_extra_prompt", {})
    signatures = getattr(app.state, "company_signatures", {})
    name = companies.get(company_id)
    resume = resumes.get(company_id)
    extra_prompt = extra_prompts.get(company_id)
    signature = signatures.get(company_id)
    if name is None:
        name = await redis_client.hget("companies", company_id) or "votre entreprise"
    if resume is None:
        resume = await redis_client.hget("company_resumes", company_id)
    if extra_prompt is None:
        extra_prompt = await redis_client.hget("company_extra_prompt", company_id)
    if signature is None:
        signature = await redis_client.hget("company_signatures", company_id)
    return name, resume, extra_prompt, signature

async def get_company_resume(app: FastAPI, company_id: str) -> str:
    if hasattr(app.state, "company_resumes") and company_id in app.state.company_resumes:
        return app.state.company_resumes[company_id]
    name = await redis_client.hget("companies", company_id)
    return name or "votre entreprise"

async def get_company_chatbot_signature(spbase: AsyncClient, company_id: str) -> Optional[str]:
    """
    Récupère la signature du chatbot pour une entreprise donnée.
    Essaie d'abord depuis le cache Redis, puis depuis Supabase.
    """
    # Essayer depuis Redis
    signature = await redis_client.hget("company_signatures", company_id)
    if signature:
        return signature
    
    # Si pas dans Redis, récupérer depuis Supabase
    try:
        res = await spbase.table(TABLE_COMPANY_INTEGRATIONS)\
            .select("chatbot_signature")\
            .eq("company_id", company_id)\
            .execute()
        data = res.data or []
        if data and data[0].get("chatbot_signature"):
            signature = data[0]["chatbot_signature"]
            # Mettre en cache dans Redis
            await redis_client.hset("company_signatures", company_id, signature)
            return signature
    except Exception as e:
        pass
    
    return None


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

def save_upload_file(upload_file: UploadFile, destination: Path) -> None:
    """
    Save an UploadFile to the given destination path in a streaming way.
    """
    with destination.open("wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)

###################################################### Upload helpers ######################################################

async def run_executor_agent(supabase,
                            session_id: Optional[str],
                            company_id: str,
                            exec_plan: Dict[str, Any],
                            user_language: str,
                            ) -> Dict[str, Any]:
    exec_plan = dict(exec_plan or {})
    exec_instruct = exec_plan["exec_inst"] 
    if TOOL_SEND_EMAIL in [d.name for d in exec_plan['tools_to_call']]  :
        list_contact = await load_intern_contact(supabase, company_id)
        instruct_email_list = extract_emails(exec_instruct) or []
        intern_email_list = list(map(itemgetter("email"), list_contact)) #extract_intern_emails(str(list_contact)) or []
        verif, list_intrus = check_difference(instruct_email_list, intern_email_list)         # verification des emails authorisés 
        if verif :
            exec_instruct = strip_emails(exec_instruct) + f"\n\n### LISTE DES CONTACTS INTERNES ###\n\nVoici la liste des contacts privés dans votre entreprise. Ne l'utilisez que si vous en avez besoin, comme contacter un responsable ou envoyer un email par exemple. Choisissez bien convenablement la bonne personne en fonction de son poste et de sa description de poste. Attention, le rôle peut ne pas correspondre exactement à ce que vous cherchez. Se référer plutôt à la descritption du poste pour le choix de la meilleure personne : \n\n<list_contact>\n"+ str(list_contact) +"\n</list_contact>\n\n"
        else :
            denied_answer = f"Je suis désolé, je me rends compte que je ne suis pas autorisé à envoyer l'email au destinataire : {', '.join(intru for intru in list_intrus)}."
            if user_language.lower() in ["malagasy", "malgache", "mg"]:
                target_denied_answer = f"Miala tsiny tompoko, tsy manana alàlana handefa mailaka amin'ity na ireto aho: {', '.join(intru for intru in list_intrus)}."
            else:
                target_denied_answer = denied_answer
            await save_supabase_message(supabase, session_id, "assistant", denied_answer, target_denied_answer, user_language)
            return target_denied_answer

    out = await onexia_executor(exec_instruct)
    try :
        out = json.loads(out) 
        return_reponse = out['message'] + out['ask'] if  out['ask'].lower() not in ["null", "none",""] else out['message']
        target_return_reponse = return_reponse if user_language.lower() not in ["malagasy", "malgache", "mg"] else await sanitize_translate(return_reponse, "fr", "mg")
        if session_id:
            await save_supabase_message(supabase, session_id, "assistant", return_reponse, target_return_reponse, user_language) # save assistant message
        return target_return_reponse
    except Exception as e:
        return "Je suis désolé, j'ai subi une petite déconnexion. Pourriez-vous répéter svp ?"


async def escalate_to_humans(conv_history, spbase, session_id, request, langue="Français"):

    escalate_conv_hist ="\n".join([f"{partie['role']}: {partie['content']}" for partie in conv_history])
    list_contact = await load_intern_contact(spbase, request.company_id)

    escalate_msg_inst = f"""
### CONTEXTE
Votre discussion courante avec le client nécessite une escalade humaine.
Exécutez la tâche en utilisant l'outil tool='escalate_to_humans'.
Date et heure de la demande : {maintenant_fr(ZoneInfo("Europe/Paris"))}

Voici l'historique de votre conversation:

----------------------------------------------------------------------------
{escalate_conv_hist.replace("assistant","Vous ").replace("user","Le client ")}
----------------------------------------------------------------------------

### TACHE
A partir de l'historique de votre conversation  :
1) Identifiez le Nom du client : l'insérer dans le paramètre "nom_du_client" du tool.
2) Identifiez le contact du client : l'insérer dans le paramètre "contact_du_client" du tool
3) Veuillez faire une synthèse claire, concise et auto-suffisante de la conversation et l'insérer dans le paramètre "synthèse_situation" du tool.
4) Veuillez en faire également un résumé détaillé et l'insérer dans le paramètre "résumé_détaillé" du tool:
    - Objectif du client
    - Description du problème du client
    - Éléments clés
    - Tentatives de résolution réalisées
    - Points d'attention
5) L'ID de session du client est {session_id} : à reseigner dans le paramètre "session_id_client" du tool.

### CONTRAINTES
Veillez à renseigner tous les paramètres requis par l'outil : aucun paramètre vide.
Toujours répondre et exécuter les tâches en {langue}.\n
"""

    list_contact_msg = f"""
### LISTE DES CONTACTS INTERNES
Voici la liste des contacts privés dans votre entreprise pour alimenter les paramètres "nom_du_responsable_humain" et "adresse_email_destinataire".
Choisissez la meilleure personne en fonction de son poste et de sa description :

<list_contact>
{list_contact}
</list_contact>
"""

    input_escalate = escalate_msg_inst + list_contact_msg
    await onexia_escalator(input_escalate)
    return


def sse_data(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


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


async def safe_write_augmented_file(filename: str,
                                    filecontent: str,
                                    destination: Path,
                                    augment_rag: bool) -> None:
    """Reads an uploaded file, optionally augments its text via AugmentRAG, and saves it to destination."""
    ext = (Path(filename).suffix or "").lower()
    if ext not in {".pdf", ".docx"}:
        raise HTTPException(status_code=400, detail=f"Unsupported file extension: {ext}")

    if not filecontent:
        raise HTTPException(status_code=422, detail="File empty or unreadable")

    if ext == ".pdf":
        try:
            reader = PdfReader(BytesIO(filecontent))
            original_text = "".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Invalid or unreadable PDF") from exc
    else:  # .docx
        try:
            document = docx.Document(BytesIO(filecontent))
            original_text = "\n".join(p.text for p in document.paragraphs)
        except BadZipFile as exc:
            raise HTTPException(status_code=422, detail="Invalid or unreadable DOCX") from exc

    if not original_text.strip():
        raise HTTPException(status_code=422, detail="File empty or unreadable")

    if augment_rag:
        try:
            final_text = await rewrite_rag_augmentor(original_text)
        except Exception:
            final_text = original_text
    else:
        final_text = original_text

    if ext == ".pdf":
        save_to_pdf(final_text, destination)
    else:  # .docx
        save_to_docx(final_text, destination)


# main.py
import os
import json
import uuid
import random
import mimetypes
import hashlib
import contextlib
from pathlib import Path
from typing import Optional, List, AsyncGenerator, Annotated
from contextlib import asynccontextmanager
import asyncio
from dotenv import load_dotenv
# FastAPI
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, UploadFile, File, Request, status, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
# Pydantic
from pydantic import BaseModel, AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
# DataBase
from redis.asyncio import Redis, ConnectionPool
from supabase import create_async_client, AsyncClient
# Utilities
from utils.utils import system_message, safety_post_filter, build_chat_messages, controlled_fallback_response
from .main_utils import (
    # Constant
    TABLE_SESSION,
    AUDIT_LIST_KEY,
    LIST_TEMP_RESP,
    LIST_TEMP_ATTENTE,
    # Variable
    redis_pool,
    redis_client,
    settings,
    # Class
    AuthUser,
    PublicQuestionRequest,
    # Functions
    refresh_companies_into_state,
    get_current_user,
    sanitize_filename,
    safe_write_file,
    get_supabase,
    get_redis,
    get_or_create_session,
    is_banned,
    save_supabase_message,
    get_cached_rag_docs,
    cache_rag_docs,
    get_company_name,
    list_messages,
    forbiden_session,
    log_audit,
    sse_data,
    run_executor_agent,
    validate_question
    )
# rag & models
from rag.rag import get_rag_context, rebuild_company_index, build_index, get_company_data_dir, get_company_stats, clear_company_cache
from llm_model.julia import julia_planner, julia_executor, PlannerOutput

load_dotenv()


###################################################### Paths and env ######################################################
BASE = Path(__file__).resolve().parent
DATA_DIR = (BASE / ".." / ".." / "data").resolve()
os.makedirs(DATA_DIR, exist_ok=True)


###################################################### FastAPI app + lifespan ######################################################
VECTORSTORES_CACHE = {}


###################################################### FastAPI app + lifespan ######################################################
app = FastAPI(title="Julia_Onexus", description="API RAG multitenant (Supabase Data API + Redis + JWT)")

@asynccontextmanager
async def lifespan(app: FastAPI):
    spbase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    app.state.spbase = spbase
    app.state.companies = {}
    await refresh_companies_into_state(app)
    try:
        yield
    finally:
        await redis_client.aclose()
        await redis_pool.aclose()


app.router.lifespan_context = lifespan


###################################################### CORS ######################################################
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


###################################################### Endpoints ######################################################
@app.get("/refresh_companies/")
async def refresh_companies():
    await refresh_companies_into_state(app)
    return {"message": "companies refreshed", "count": len(app.state.companies)}


@app.post("/upload/")
async def upload_file(file: UploadFile = File(...),
                      background_tasks: BackgroundTasks = None,
                      current_user: AuthUser = Depends(get_current_user),
                      ):
    """Endpoint pour uploader un fichier PDF ou DOCX pour l'entreprise de l'utilisateur."""
    ext = Path(file.filename).suffix.lower()
    if ext not in settings.ALLOWED_UPLOAD_EXTS:
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF et DOCX sont acceptés.")
    mime_guess, _ = mimetypes.guess_type(file.filename)
    mime_hint = (mime_guess or file.content_type or "").lower()
    if ext == ".pdf" and "pdf" not in mime_hint: # Make sure the extension and MIME type agree
        raise HTTPException(status_code=400, detail="MIME type mismatch for PDF")
    if ext == ".docx" and ("word" not in mime_hint and "officedocument" not in mime_hint):
        raise HTTPException(status_code=400, detail="MIME type mismatch for DOCX")

    company_id = current_user.company_id
    company_dir = (DATA_DIR / company_id)
    company_dir.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_filename(file.filename)
    destination = company_dir / safe_name
    await safe_write_file(destination, file, settings.MAX_UPLOAD_MB * 1024 * 1024)

    if background_tasks:
        await refresh_companies_into_state(app)
        background_tasks.add_task(rebuild_company_index, company_id, DATA_DIR, HTTPException)

    return {
        "message": f"file {safe_name} uploaded",
        "company_id": company_id,
        "file": safe_name,
    }


@app.post("/build_index/")
async def express_build_index(current_user: AuthUser = Depends(get_current_user)):
    try:
        build_index(current_user.company_id, DATA_DIR, HTTPException)
        return {
            "message": f"Index construit avec succès pour l'entreprise {current_user.company_id}",
            "company_id": current_user.company_id,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la construction de l'index: {str(e)}")


@app.post("/ask_public/")
async def ask_question_public(req: Request,
                              request: PublicQuestionRequest,
                              spbase: AsyncClient = Depends(get_supabase),
                              redis: Redis = Depends(get_redis),
                              ):
    
    user_question = validate_question(request.question) # check length abuse

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            # 1) Resolve/create session
            session = await get_or_create_session(spbase, redis, request.company_id, request.external_user_id)
            if not isinstance(session, dict) or "session_id" not in session:
                raise HTTPException(status_code=500, detail="Invalid session object")
            session_id = session["session_id"]

            # 2) Ban check
            if await is_banned(redis, request.company_id, session_id):
                yield sse_data({
                    "answer": None,
                    "company_id": request.company_id,
                    "session_id": session_id,
                    "external_user_id": request.external_user_id,
                })
                return

            # 3) Persist user message
            await save_supabase_message(spbase, session_id, "user", user_question)

            # 4) RAG context with Redis cache
            docs = await get_cached_rag_docs(redis, request.company_id, user_question)
            
            if docs is None:
                vectordb, docs = get_rag_context(user_question, request.company_id, VECTORSTORES_CACHE)
                if request.company_id not in VECTORSTORES_CACHE:
                    VECTORSTORES_CACHE[request.company_id] = vectordb
                await cache_rag_docs(redis, request.company_id, user_question, docs, ttl_seconds=300)

            # 5) Build messages for LLM/agents
            company_name = await get_company_name(app, request.company_id)
            syst_msg = system_message(company_name)
            history = await list_messages(spbase, session_id, limit=60)
            msgs = build_chat_messages(
                messages_history=history,
                user_input=user_question,
                context=docs,
                system_message=syst_msg,
                langue=request.langue,
                max_history_pairs=30,
            )

            # 6) Planner
            planner_out: PlannerOutput = await julia_planner(msgs)

            if not planner_out.continue_discussion:
                await forbiden_session(redis, request.company_id, session_id)
                payload = {
                    "answer": "Je conclus ici pour aujourd'hui, en vous remerciant chaleureusement. Prenez bien soin de vous.",
                    "company_id": request.company_id,
                    "session_id": session_id,
                    "external_user_id": request.external_user_id,
                }
                await save_supabase_message(spbase, session_id, "assistant", payload["answer"])
                await log_audit(redis, {"type": "planner_block", "session_id": session_id, "company_id": request.company_id})
                yield sse_data(payload)
                return


            # 7) Simple branches
            async def respond_and_log(text: str) -> dict: # Helper to log assistant text
                safe = safety_post_filter(text)
                await save_supabase_message(spbase, session_id, "assistant", safe)
                return {
                    "answer": safe,
                    "company_id": request.company_id,
                    "session_id": session_id,
                    "external_user_id": request.external_user_id,
                    }

            if planner_out.action_type == "reject":
                reject = planner_out.user_visible_answer or "Désolé, je ne suis pas en mesure de vous aider sur ce point."
                yield sse_data(await respond_and_log(reject))
                return
            
            if planner_out.action_type == "clarify":
                clarif = planner_out.user_visible_answer or (
                    "D'accord. Mais je ne suis pas sûr de clairement comprendre votre demande. "
                    "Pouvez-vous détailler encore un peu plus svp ?"
                )
                yield sse_data(await respond_and_log(clarif))
                return
            
            if planner_out.action_type in ("answer",):
                if not planner_out.user_visible_answer:
                    yield sse_data(await respond_and_log("Pouvez-vous me fournir un peu plus de détail svp ?"))
                    return
                yield sse_data(await respond_and_log(planner_out.user_visible_answer))
                return
            
            # 8) Tool branch: ack, run executor with timeout, stream heartbeats
            if planner_out.action_type == "tool":

                temp_resp = random.choice(LIST_TEMP_RESP)
                await save_supabase_message(spbase, session_id, "assistant", temp_resp)
                ack_payload = {
                    "answer": temp_resp,
                    "company_id": request.company_id,
                    "session_id": session_id,
                    "external_user_id": request.external_user_id,
                }
                yield sse_data(ack_payload)

                async def _run_executor():
                    return await run_executor_agent(spbase, session_id, request.company_id, planner_out)

                task = asyncio.create_task(_run_executor())

                try:
                    while True:
                        done, _ = await asyncio.wait({task}, timeout=settings.HEARTBEAT_SEC)
                        if await req.is_disconnected():
                            task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await task
                            return
                        if done:
                            break
                        # Heartbeat
                        yield sse_data({"event": "ping_disconnect"})
                    # Completed
                    result = await asyncio.wait_for(task, timeout=None)
                    final_text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
                    safe_final = safety_post_filter(final_text)
                    await save_supabase_message(spbase, session_id, "assistant", safe_final)
                    final_payload = {
                        "answer": safe_final or "C'est fait ! Merci pour votre attente.",
                        "company_id": request.company_id,
                        "session_id": session_id,
                        "external_user_id": request.external_user_id,
                    }
                    yield sse_data(final_payload)
                    return
                except asyncio.TimeoutError:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                    yield sse_data({"error": "Délai dépassé, veuillez réessayer."})
                    return

            # 9) Fallback
            lang = request.langue or "Français"
            yield sse_data(await respond_and_log(controlled_fallback_response(lang)))
            return

        except Exception as e:
            await log_audit(redis, {"type": "error", "at": "ask_public", "error": str(e)})
            yield sse_data({"error": f"Erreur lors de la génération de la réponse: {str(e)}"})

    # Single-generator SSE with heartbeat on timeout
    async def merged_stream():
        async_generator = event_stream()
        try:
            while True:
                if await req.is_disconnected():
                    break
                try:
                    chunk = await asyncio.wait_for(async_generator.__anext__(), timeout=settings.HEARTBEAT_SEC)
                    yield chunk
                except asyncio.TimeoutError:
                    yield sse_data({"event": "backend_still_working"})
                except StopAsyncIteration:
                    break
        finally:
            with contextlib.suppress(Exception):
                await async_generator.aclose()

    return StreamingResponse(
        merged_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/sessions_public/{company_id}")
async def get_public_sessions(company_id: str, external_user_id: Optional[str] = None, spbase: AsyncClient = Depends(get_supabase)):
    q = spbase.table(TABLE_SESSION).select("*").eq("company_id", company_id)
    if external_user_id:
        q = q.eq("external_user_id", external_user_id)
    res = await q.execute()
    sessions = res.data or []
    payload = [
        {
            "session_id": s.get("session_id"),
            "company_id": s.get("company_id"),
            "external_user_id": s.get("external_user_id"),
            "created_at": s.get("created_at"),
        } for s in sessions if isinstance(s, dict)
    ]
    return {"sessions": payload, "company_id": company_id, "total": len(payload)}

@app.get("/messages_public/{session_id}")
async def get_public_messages(session_id: str, spbase: AsyncClient = Depends(get_supabase)):
    msgs = await list_messages(spbase, session_id)
    return msgs

@app.get("/stats/")
async def get_stats_endpoint(current_user: AuthUser = Depends(get_current_user)):
    try:
        stats = get_company_stats(current_user.company_id or "default-company", DATA_DIR)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des statistiques: {str(e)}")

@app.delete("/documents/{filename}")
async def delete_document(
    filename: str,
    background_tasks: BackgroundTasks,
    current_user: AuthUser = Depends(get_current_user),
):
    try:
        company_id = current_user.company_id or "default-company"
        company_data_dir = get_company_data_dir(company_id, DATA_DIR)
        file_path = os.path.join(company_data_dir, filename)

        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Fichier {filename} non trouvé")

        if not filename.lower().endswith(('.pdf', '.docx')):
            raise HTTPException(status_code=400, detail="Seuls les fichiers PDF et DOCX peuvent être supprimés")

        os.remove(file_path)
        background_tasks.add_task(rebuild_company_index, company_id, DATA_DIR, HTTPException)

        return {
            "message": f"Document {filename} supprimé avec succès",
            "company_id": company_id,
            "filename": filename,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la suppression du document: {str(e)}")

@app.delete("/clear_cache/")
async def clear_cache_endpoint(current_user: AuthUser = Depends(get_current_user)):
    if (current_user.role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
    try:
        clear_company_cache(current_user.company_id or "default-company")
        return {
            "message": f"Cache vidé pour l'entreprise {current_user.company_id}",
            "company_id": current_user.company_id,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors du vidage du cache: {str(e)}")

@app.get("/documents/")
async def list_documents(current_user: AuthUser = Depends(get_current_user)):
    try:
        company_id = current_user.company_id or "default-company"
        company_data_dir = get_company_data_dir(company_id, DATA_DIR)
        documents = []
        if os.path.exists(company_data_dir):
            for fname in os.listdir(company_data_dir):
                if fname.lower().endswith(('.pdf', '.docx')):
                    fpath = os.path.join(company_data_dir, fname)
                    fsize = os.path.getsize(fpath)
                    documents.append({
                        "name": fname,
                        "file_path": fpath,
                        "file_size": fsize,
                        "mime_type": "application/pdf" if fname.lower().endswith('.pdf')
                        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    })
        return {
            "documents": documents,
            "company_id": company_id,
            "total": len(documents),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des documents: {str(e)}")

@app.get("/health/")
async def health_check():
    return {"status": "healthy", "message": "API RAG avec multitenancy fonctionnelle"}

@app.get("/audit_tail/")
async def audit_tail(n: int = 50, r: Redis = Depends(get_redis)):
    items = await r.lrange(AUDIT_LIST_KEY, 0, max(0, n - 1))
    return [json.loads(x) for x in items]

@app.get("/")
async def root():
    return {
        "message": "Bienvenue sur l'API RAG avec multitenancy",
        "version": "2.0",
        "endpoints": {
            "/upload/": "Uploader un fichier PDF ou DOCX (authentification requise)",
            "/build_index/": "Construire l'index pour votre entreprise (authentification requise)",
            "/ask_public/": "Poser une user_question publique (aucune authentification requise)",
            "/sessions_public/{company_id}": "Lister les sessions publiques (aucune authentification requise)",
            "/messages_public/{session_id}": "Récupérer les messages d'une session publique (aucune authentification requise)",
            "/stats/": "Statistiques de votre entreprise (authentification requise)",
            "/documents/": "Lister les documents de votre entreprise (authentification requise)",
            "DELETE /documents/{filename}": "Supprimer un document physique (authentification requise)",
            "/clear_cache/": "Vider le cache (admin uniquement)",
            "/health/": "Vérification de l'état de l'API",
            "/refresh_companies": "Recharger les entreprises connues",
            "/audit_tail/": "Derniers logs d'audit (limités)",
        },
        "public_endpoints": ["/ask_public/", "/sessions_public/", "/messages_public/", "/health/", "/", "/audit_tail/"],
        "auth_required": "Bearer token JWT requis pour les endpoints non publics",
    }

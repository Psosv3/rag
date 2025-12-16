# main app.py
import os
import json
import random
import mimetypes
import contextlib
from pathlib import Path
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
import asyncio
from docx import Document
from dotenv import load_dotenv
# FastAPI
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, UploadFile, File, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
# DataBase
from redis.asyncio import Redis
from supabase import create_async_client, AsyncClient
# Utilities
from utils.utils import developper_message, safety_post_filter, controlled_fallback_response, sanitize_translate, check_contact_and_name
from .app_utils import (
    # Constant
    TABLE_SESSION,
    AUDIT_LIST_KEY,
    LIST_TEMP_RESP,
    LIST_ESCALATE_RESP,
    ALLOWED_FILES_TYPES,
    # Variable
    redis_pool,
    redis_client,
    settings,
    # Class
    AuthUser,
    PublicQuestionRequest,
    FeedbackRequest,
    # Functions
    refresh_companies_into_state,
    get_current_user,
    get_supabase,
    get_redis,
    get_or_create_session,
    is_banned,
    save_supabase_message,
    create_notification,
    get_cached_rag_docs,
    cache_rag_docs,
    get_company_name_resume_prompt_signature,
    list_messages,
    forbiden_session,
    log_audit,
    sse_data,
    run_executor_agent,
    validate_quest_length,
    escalate_to_humans,
    add_escalate_session,
    remove_escalate_session,
    is_ready_to_escalate,
    clear_all_cached_rag_docs,
    safe_write_augmented_file,
    messenger_wait_human,
    prep_input_embed,
    get_or_write_company_resume,
    get_company_chatbot_signature,
    build_chat_messages,
    stop_chatbot,
    process_file,
    transcribe_audio_to_text,
    )
# rag & models
from rag.rag import get_rag_context, rebuild_company_index, build_index, get_company_data_dir, get_company_stats, clear_company_cache, rewrite_rag_augmentor
from llm_model.onexia import onexia_planner, PlannerOutput, planner_syst_instructions

load_dotenv()


###################################################### Paths and env ######################################################
BASE = Path(__file__).resolve().parent
DATA_DIR = BASE.parents[2] / "data"
os.makedirs(DATA_DIR, exist_ok=True)


###################################################### FastAPI app + lifespan ######################################################
VECTORSTORES_CACHE = {}


###################################################### FastAPI app + lifespan ######################################################
app = FastAPI(title="Onexia", description="API RAG multitenant (Supabase Data API + Redis + JWT)")

@asynccontextmanager
async def lifespan(app: FastAPI):
    spbase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    app.state.spbase = spbase
    app.state.companies = {}
    app.state.company_resumes = {}
    app.state.company_signatures = {}
    app.state.company_extra_prompt = {}
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
    allow_origins=["*"],
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
                      current_user: AuthUser = Depends(get_current_user),
                      augment_rag : bool = True):
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
    company_dir = DATA_DIR / ("company_"+company_id)
    company_dir.mkdir(parents=True, exist_ok=True)

    safe_name = file.filename # TODO : sanitize_filename(file.filename) 
    destination = company_dir / safe_name
    augm_dest = company_dir / ("gzel8!a3_" + safe_name)

    content = await file.read()
    await safe_write_augmented_file(file.filename, content, destination, False)
    if augment_rag:
        try:
            await safe_write_augmented_file(file.filename, content, augm_dest, True)
        except:
            await safe_write_augmented_file(file.filename, content, augm_dest, False)

    return {
        "message": f"file {safe_name} uploaded",
        "company_id": company_id,
        "file": safe_name,
    }


@app.post("/build_index/")
async def express_build_index(current_user: AuthUser = Depends(get_current_user),
                              redis: Redis = Depends(get_redis),
                              spbase: AsyncClient = Depends(get_supabase),
                              ):
    try:
        await clear_all_cached_rag_docs(redis, current_user.company_id)
        _, company_synth = await build_index(current_user.company_id, DATA_DIR, HTTPException)
        await get_or_write_company_resume(spbase, current_user.company_id, "write", company_synth)
        return {
            "message": f"Index construit avec succès pour l'entreprise {current_user.company_id}",
            "company_id": current_user.company_id,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la construction de l'index: {str(e)}")


@app.post("/ask_public/")
async def ask_question_public(req: Request,
                              company_id: str = Form(...),
                              question: Optional[str] = Form(...),
                              session_id: Optional[str] = Form(None),
                              external_user_id: Optional[str] = Form(None),
                              langue: str = Form('français'),
                              messenger: Optional[str] = Form(None),
                              file: Optional[UploadFile] = File(None),
                              audio: Optional[UploadFile] = File(None),
                              spbase: AsyncClient = Depends(get_supabase),
                              redis: Redis = Depends(get_redis),
                              ):
    # Reconstruire l'objet request pour garder le code existant
    request = PublicQuestionRequest(question=question,
                                    company_id=company_id,
                                    session_id=session_id,
                                    external_user_id=external_user_id,
                                    langue=langue,
                                    messenger=messenger,
                                    file=file,
                                    audio=audio,
                                    )

    # 0) Resolve/create session
    session = await get_or_create_session(spbase, redis, request.company_id, request.external_user_id, request.messenger)
    if not isinstance(session, dict) or "session_id" not in session:
        raise HTTPException(status_code=500, detail="Invalid session object")
    session_id = session["session_id"]

    # 1) a) validate question length
    is_rejected, original_question = validate_quest_length(request.question) if request.question else (False, "")
    if is_rejected : 
        return sse_data({"answer": "Owh! Vous êtes bien bavard. Je suis désolé, je ne peux accepter que les questions à 1000 caractères maximum.",
                        "company_id": request.company_id,
                        "session_id": session_id,
                        "external_user_id": request.external_user_id,
                        })        
    # 1) b) sanitize_malagasy_sentence, dict_abreviation_mg
    user_language = request.langue.lower() if request.langue else None

    if request.audio is not None:
        # Save uploaded audio to a temporary file
        temp_audio_path = DATA_DIR / f"temp_audio_{session_id}{Path(request.audio.filename).suffix}"
        original_question = await transcribe_audio_to_text(str(temp_audio_path), request.audio)
        # original_question = await transcribe_audio_to_text(temp_audio_path, request.audio)
        temp_audio_path.unlink(missing_ok=True)
         
    if user_language in ("malgache", "malagasy","mg"):
        user_text_question = await sanitize_translate(original_question.lower(), "mg", "fr")
    else:
        user_text_question = original_question

    # 2) event_stream
    async def event_stream() -> AsyncGenerator[str, None]:
        try:

            # 0) General_Stop chatbot check or Ban check or Messenger_waiting_human
            general_manual_response = await stop_chatbot(spbase, request.company_id)
            ban = await is_banned(redis, request.company_id, session_id)
            messenger_waiting_human = await messenger_wait_human(spbase, session_id)

            if general_manual_response or ban or messenger_waiting_human:
                yield sse_data({
                    "answer": None,
                    "company_id": request.company_id,
                    "session_id": session_id,
                    "external_user_id": request.external_user_id,
                })
                return

            # 1) process text and file, persist message, create notifications and escalate check
            # 1) a) process uploaded file (.png ou .jpg) if any 
            if request.file :
                if request.file.content_type not in ALLOWED_FILES_TYPES:
                    raise HTTPException(status_code=400 ,detail="Seuls les fichiers images PNG, JPG et WEBP sont acceptés.")
                try:
                    content_file = await process_file(request.file, settings.MAX_UPLOAD_MB, ALLOWED_FILES_TYPES)
                    user_question = f"L'utilisateur a envoyé un fichier externe {request.file.content_type}. Voici ce qu'il contient:\n\n<CONTENU_IMAGE> :\n{content_file}\n</CONTENU_IMAGE>. \n\nVoici le message de l'utilisateur : \n{user_text_question}"
                except Exception as e:
                    print(f"***** ERREUR process_file: {e}")
                    await save_supabase_message(spbase, session_id, "user", user_text_question, original_question, user_language)
                    error_file_answer = f"Oups.. je n'ai pas pu traiter le fichier que vous avez envoyé. Pouvez-vous vous assurer qu'il est bien valide ({settings.MAX_UPLOAD_MB} Mo max) et de me le renvoyer svp ? Merci! :)"
                    yield sse_data({
                        "answer": error_file_answer,
                        "company_id": request.company_id,
                        "session_id": session_id,
                        "external_user_id": request.external_user_id,
                    })
                    return
            else:
                user_question = user_text_question
 
            # 1) b) Persist user message & load conv history
            await save_supabase_message(spbase,
                                        session_id,
                                        "user",
                                        user_question,
                                        original_question,
                                        user_language,
                                        )
            conv_history = await list_messages(spbase, session_id)

            # 1) c) Créer une notification pour chaque nouveau message
            await create_notification(
                spbase=spbase,
                company_id=request.company_id,
                notification_type="new_message",
                title="Nouveau message reçu",
                content=f"Un utilisateur a envoyé un message : {user_question[:100]}{'...' if len(user_question) > 100 else ''}",
                session_id=session_id,
                priority="normal",
                metadata={
                    "external_user_id": request.external_user_id,
                    "messenger": request.messenger,
                    "message_time": datetime.now().isoformat(),
                    "question_length": len(user_question)
                },
                action_url=f"/dashboard/chat?session={session_id}",
                action_label="Voir la conversation"
            )

            # 1) d) Prioritize escalate-ready case
            if await is_ready_to_escalate(redis, request.company_id, session_id):
                go = check_contact_and_name(user_question)
                if go == "OK":
                    await remove_escalate_session(redis, request.company_id, session_id)
                    await escalate_to_humans(conv_history, spbase, session_id, request)
                    # Créer une notification pour le dashboard
                    await create_notification(
                        spbase=spbase,
                        company_id=request.company_id,
                        notification_type="manual_response_required",
                        title="Intervention manuelle requise",
                        content=f"Une conversation nécessite une réponse manuelle. Dernier message: {user_question[:100]}...",
                        session_id=session_id,
                        priority="high",
                        metadata={
                            "reason": "escalation_completed",
                            "last_user_message": user_question[:200],
                            "escalation_time": datetime.now().isoformat()
                        },
                        action_url=f"/dashboard/chat?session={session_id}",
                        action_label="Répondre maintenant"
                    )
                    answer_escalate = "C'est bon! Mon responsable a été informé. Il reviendra vers vous au plus vite."
                    if request.langue.lower() in ("malgache", "malagasy","mg") :
                        target_answer_escalate = "Misaotra tompoko. Efa lasa any amin'ny tompon'andraikitra ny hafatrao. Hifandray aminao arak'izay haingana izy."
                    else:
                        target_answer_escalate = answer_escalate
                    message_data = await save_supabase_message(spbase, session_id, "assistant", answer_escalate, target_answer_escalate, request.langue, manual_response=True)
                    escalate_payload = {
                        "answer": target_answer_escalate,
                        "company_id": request.company_id,
                        "session_id": session_id,
                        "external_user_id": request.external_user_id,
                        "message_id": message_data.get("message_id")
                    }
                    yield sse_data(escalate_payload)
                    return
                else:
                    clarif = "J'aurais besoin de vos coordonnées (email ou téléphone) svp pour que notre équipe puisse vous recontacter. Pourriez-vous me redonner ensemble vos coordonnées et votre nom complet svp ? Merci !" if go == "missing_contact" else "Il me faudrait aussi votre nom complet svp. Pourriez-vous me redonner ensemble vos coordonnées et votre nom complet svp ? Merci !"
                    
                    if request.langue.lower() in ("malgache", "malagasy","mg"):
                        target_clarif = "Azafady indrindra, mba mila ny anaranao feno sy ny adiresy mailaka na ny telefaoninao izahay azafady afahanay miverina miantso anao. Mba azonao alefa amiko miaraka ve ireo ? Misaotra tompoko."
                    else:
                        target_clarif = clarif
                    message_data = await save_supabase_message(spbase, session_id, "assistant", clarif, target_clarif, request.langue)
                    payload = {
                        "answer": target_clarif,
                        "company_id": request.company_id,
                        "session_id": session_id,
                        "external_user_id": request.external_user_id,
                        "message_id": message_data.get("message_id")
                    }
                    yield sse_data(payload)
                    return

            # 2) RAG context with Redis cache
            input_to_embed = await prep_input_embed(conv_history, user_question)
            docs = await get_cached_rag_docs(redis, request.company_id, input_to_embed)
            if docs is None:
                vectordb, docs = await get_rag_context(input_to_embed, request.company_id, VECTORSTORES_CACHE, HTTPException=HTTPException)
                if request.company_id not in VECTORSTORES_CACHE:
                    VECTORSTORES_CACHE[request.company_id] = vectordb
                await cache_rag_docs(redis, request.company_id, input_to_embed, docs, ttl_seconds=300)
                
            # 3) Build messages for LLM/agents
            company_name, company_resume, company_extra_prompt, company_signature = await get_company_name_resume_prompt_signature(app, request.company_id)
            syst_msg = planner_syst_instructions
            dev_msg = developper_message(company_name, company_resume, company_extra_prompt)
            msgs = build_chat_messages(messages_history=conv_history,
                                       user_input=user_question,
                                       context=docs,
                                       system_message=syst_msg,
                                       dev_message=dev_msg)
            # 4) Planner
            planner_out: PlannerOutput = await onexia_planner(msgs)

            if not planner_out.continue_discussion:
                await forbiden_session(redis, request.company_id, session_id)
                answer_mg = "Tena miala tsiny indrindra tompoko, voatery aho hamarana ny resantsika eto. Mankasitraka indrindra dia mirary soa."
                answer_fr = "Je suis vraiment désolé, je dois vous laisser ici pour aujourd'hui, en vous remerciant chaleureusement. Prenez bien soin de vous et à bientôt! :)"
                answer = answer_mg if request.langue.lower() == "malgache" else answer_fr
                payload = {
                    "answer": answer,
                    "company_id": request.company_id,
                    "session_id": session_id,
                    "external_user_id": request.external_user_id,
                }
                message_data = await save_supabase_message(spbase, session_id, "assistant", answer_fr, answer, request.langue, stop_discuss_reason=planner_out.explain_stop_discussion)
                await log_audit(redis, {"type": "planner_block", "session_id": session_id, "company_id": request.company_id})
                payload["message_id"] = message_data.get("message_id")
                yield sse_data(payload)
                return

            # 5) Simple branches
            async def respond_and_log(text: str, langue : str, signature: str) -> dict: # Helper to log assistant text + add final signature
                text += f"\n\n{signature}" if signature else ""
                safe_answer = safety_post_filter(text)
                if langue.lower() in ("malgache", "malagasy","mg"):
                    target_safe_answer = await sanitize_translate(safe_answer, "fr", "mg")
                else:
                    target_safe_answer = safe_answer
                message_data = await save_supabase_message(spbase,
                                                           session_id,
                                                           "assistant",
                                                           safe_answer,
                                                           target_safe_answer,
                                                           langue)
                return {
                        "answer": target_safe_answer,
                        "company_id": request.company_id,
                        "session_id": session_id,
                        "external_user_id": request.external_user_id,
                        "message_id": message_data.get("message_id"),
                        "signature": signature
                        }

            if planner_out.action_type == "reject":
                reject = planner_out.user_visible_answer or "Désolé, je ne suis pas en mesure de vous aider sur ce point."
                yield sse_data(await respond_and_log(reject, request.langue, company_signature))
                return
            
            if planner_out.action_type == "clarify":
                clarif = planner_out.user_visible_answer or (
                    "D'accord. Mais je ne suis pas sûr de clairement comprendre votre demande. "
                    "Pouvez-vous détailler encore un peu plus svp ?"
                )
                yield sse_data(await respond_and_log(clarif, request.langue, company_signature))
                return
            
            if planner_out.action_type == "answer":
                if not planner_out.user_visible_answer:
                    clarif_bis = "Pouvez-vous me fournir un peu plus de détail svp ?"
                    yield sse_data(await respond_and_log(clarif_bis, request.langue, company_signature))
                    return
                yield sse_data(await respond_and_log(planner_out.user_visible_answer, request.langue, company_signature))
                return
            
            if planner_out.action_type == "escalate":
                await add_escalate_session(redis, request.company_id, session_id)
                prep_escalate_resp = random.choice(LIST_ESCALATE_RESP)
                if request.langue.lower() in ("malgache", "malagasy","mg"):
                    target_prep_resp = "Ho hampiresahiko amin'ny tompon'andraikitra ianao fa mba azonao alefa amiko miaraka ve ny anaranao sy ny laharan-telefaoninao na ny adiresy mailaka ? Ilainay ireo afahan'ilay tompon'andraikitra miverina miantso anao. Misaotra tompoko."
                else:
                    target_prep_resp = prep_escalate_resp   
                message_data = await save_supabase_message(spbase, session_id, "assistant", prep_escalate_resp, target_prep_resp, request.langue)
                ack_payload = {
                    "answer": target_prep_resp,
                    "company_id": request.company_id,
                    "session_id": session_id,
                    "external_user_id": request.external_user_id,
                    "message_id": message_data.get("message_id")
                }
                yield sse_data(ack_payload)
                return

            # 6) Tool branch: ack, run executor with timeout, stream heartbeats
            if planner_out.action_type == "tool":

                temp_resp = random.choice(LIST_TEMP_RESP)
                yield sse_data(await respond_and_log(temp_resp, request.langue, company_signature))

                async def _run_executor():
                    return await run_executor_agent(spbase, session_id, request.company_id, planner_out, user_language)

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
                    
                    safe_final = safety_post_filter(final_text) or "C'est fait ! Merci pour votre attente."
                    if request.langue.lower() in ("malgache", "malagasy","mg"):
                        target_safe_final = "Vita soa tompoko! Misaotra indrindra tamin'ny faharetanao."
                    else:
                        target_safe_final = safe_final
                    message_data = await save_supabase_message(spbase, session_id, "assistant", safe_final, target_safe_final, request.langue)
                    
                    final_payload = {
                        "answer": target_safe_final,
                        "company_id": request.company_id,
                        "session_id": session_id,
                        "external_user_id": request.external_user_id,
                        "message_id": message_data.get("message_id")
                    }
                    
                    yield sse_data(final_payload)
                    return
                except asyncio.TimeoutError:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                    yield sse_data({"error": "Délai dépassé, veuillez réessayer."})
                    return

            # 7) Fallback
            lang = "Français"
            yield sse_data(await respond_and_log(controlled_fallback_response(lang, request.langue), request.langue, company_signature))
            return

        except Exception as e:
            await log_audit(redis, {"type": "error", "at": "ask_public", "error": str(e)})
            raise HTTPException(status_code=500, detail=f"Erreur lors de la génération de la réponse: {str(e)}")

    # 3) Single-generator SSE with heartbeat on timeout
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
                    yield sse_data({"event": "heartbeat"})
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

@app.get("/company_info_public/{company_id}")
async def get_company_info_public(company_id: str, spbase: AsyncClient = Depends(get_supabase)):
    """
    Endpoint public pour récupérer les informations d'une entreprise (notamment chatbot_signature et background_color).
    """
    try:
        signature = await get_company_chatbot_signature(spbase, company_id)
        
        # Récupérer le background_color depuis company_integrations
        background_color = "#4F46E5"  # Valeur par défaut
        try:
            integration_res = await spbase.table("company_integrations")\
                .select("background_color")\
                .eq("company_id", company_id)\
                .limit(1)\
                .execute()
            
            if integration_res.data and len(integration_res.data) > 0:
                background_color = integration_res.data[0].get("background_color", background_color)
        except Exception as e:
            # Si erreur lors de la récupération, on utilise la couleur par défaut
            pass
        
        return {
            "company_id": company_id,
            "chatbot_signature": signature,
            "background_color": background_color,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des informations: {str(e)}")

@app.get("/stats/")
async def get_stats_endpoint(current_user: AuthUser = Depends(get_current_user)):
    try:
        stats = get_company_stats(current_user.company_id, DATA_DIR)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des statistiques: {str(e)}")

@app.get("/documents/{filename}/content")
async def get_document_content(
    filename: str,
    current_user: AuthUser = Depends(get_current_user),
):
    """Récupère le contenu textuel d'un fichier DOCX"""
    try:     
        company_id = current_user.company_id or "default-company"
        company_data_dir = get_company_data_dir(company_id, DATA_DIR)
        file_path = os.path.join(company_data_dir, filename)
        
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Fichier {filename} non trouvé dans {company_data_dir}")

        if not filename.lower().endswith('.docx'):
            raise HTTPException(status_code=400, detail="Seuls les fichiers DOCX peuvent être lus pour édition")

        # Lire le contenu du fichier DOCX
        doc = Document(file_path)
        paragraphs = []
        for para in doc.paragraphs:
            paragraphs.append(para.text)
        
        content = "\n".join(paragraphs)
        
        return {
            "filename": filename,
            "content": content,
            "company_id": company_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[ERROR] Exception lors de la lecture du document:")
        print(f"  - Type: {type(e).__name__}")
        print(f"  - Message: {str(e)}")
        print(f"  - Traceback:")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erreur lors de la lecture du document: {str(e)}")


@app.put("/documents/{filename}/content")
async def update_document_content(filename: str,
                                  content: dict,
                                  background_tasks: BackgroundTasks,
                                  current_user: AuthUser = Depends(get_current_user),
                                  redis: Redis = Depends(get_redis),
                                  ):
    """Met à jour le contenu d'un fichier DOCX"""
    try:        
        company_id = current_user.company_id
        company_data_dir = get_company_data_dir(company_id, DATA_DIR)

        if not filename.lower().endswith('.docx'):
            raise HTTPException(status_code=400, detail="Seuls les fichiers DOCX peuvent être modifiés")

        new_content = content.get("content", "")
        if not new_content:
            raise HTTPException(status_code=400, detail="Le contenu ne peut pas être vide")
        new_augmented_content = await rewrite_rag_augmentor(new_content)

        # Créer un nouveau document avec le contenu mis à jour
        try:
            for _content, _name in [(new_content, filename), (new_augmented_content, "gzel8!a3_"+filename)]:
                file_path = os.path.join(company_data_dir, _name)
                if not os.path.exists(file_path):
                    continue # evite de de buguer si le doc n existe pas deja et passe au suivant
                doc = Document()
                for line in _content.split("\n"):
                    doc.add_paragraph(line)
                doc.save(file_path) # Sauvegarder le fichier
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur lors de la création du double-document: {str(e)}")
        
        # Vider le cache et reconstruire l'index en arrière-plan
        try:
            clear_company_cache(company_id, VECTORSTORES_CACHE) # Clear in-memory cache
            await clear_all_cached_rag_docs(redis, company_id)
            background_tasks.add_task(rebuild_company_index, company_id, DATA_DIR, HTTPException)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur lors de la mise à jour de l'index en arrière-plan: {str(e)}")

        
        return {
            "message": f"Document {filename} mis à jour avec succès",
            "filename": filename,
            "company_id": company_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la mise à jour du document: {str(e)}")


@app.get("/documents/{filename}/view")
async def view_document(
    filename: str,
    current_user: AuthUser = Depends(get_current_user),
):
    """Stream un fichier PDF pour visualisation"""
    try:
        company_id = current_user.company_id or "default-company"
        company_data_dir = get_company_data_dir(company_id, DATA_DIR)
        file_path = os.path.join(company_data_dir, filename)

        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Fichier {filename} non trouvé")

        if not filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Seuls les fichiers PDF peuvent être visualisés")

        # Streamer le fichier PDF
        def iterfile():
            with open(file_path, "rb") as f:
                yield from f

        return StreamingResponse(
            iterfile(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename={filename}",
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la visualisation du document: {str(e)}")


@app.get("/documents/{filename}/download")
async def download_document(
    filename: str,
    current_user: AuthUser = Depends(get_current_user),
):
    """Télécharge un fichier (PDF ou DOCX)"""
    try:
        company_id = current_user.company_id or "default-company"
        company_data_dir = get_company_data_dir(company_id, DATA_DIR)
        file_path = os.path.join(company_data_dir, filename)

        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Fichier {filename} non trouvé")

        if not filename.lower().endswith(('.pdf', '.docx')):
            raise HTTPException(status_code=400, detail="Seuls les fichiers PDF et DOCX peuvent être téléchargés")

        # Déterminer le MIME type
        mime_type = "application/pdf" if filename.lower().endswith('.pdf') else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

        # Streamer le fichier
        def iterfile():
            with open(file_path, "rb") as f:
                yield from f

        return StreamingResponse(
            iterfile(),
            media_type=mime_type,
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[ERROR] Exception lors du téléchargement:")
        print(f"  - Type: {type(e).__name__}")
        print(f"  - Message: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erreur lors du téléchargement du document: {str(e)}")


@app.delete("/documents/{filename}")
async def delete_document(
    filename: str,
    background_tasks: BackgroundTasks,
    current_user: AuthUser = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
):
    try:
        
        company_id = current_user.company_id

        clear_company_cache(company_id, VECTORSTORES_CACHE) # Clear in-memory cache
        await clear_all_cached_rag_docs(redis, company_id)  # Clear Redis cache

        company_data_dir = get_company_data_dir(company_id, DATA_DIR)

        for name in [filename, "gzel8!a3_" + filename]:
            try:
                file_path = os.path.join(company_data_dir, name)
                if not os.path.exists(file_path):
                    raise HTTPException(status_code=404, detail=f"Fichier non trouvé")
                os.remove(file_path)
            except:
                continue  # Try next name

        if os.listdir(company_data_dir):
            background_tasks.add_task(rebuild_company_index, company_id, DATA_DIR, HTTPException)
        
        return {
            "message": f"Document {filename} supprimé avec succès",
            "company_id": company_id,
            "filename": filename,
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la suppression du document: {str(e)}")

@app.delete("/clear_cache/")
async def clear_cache_endpoint(current_user: AuthUser = Depends(get_current_user)):
    if (current_user.role or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
    try:
        clear_company_cache(current_user.company_id, VECTORSTORES_CACHE)
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

@app.post("/feedback/")
async def submit_feedback(
    request: FeedbackRequest,
    spbase: AsyncClient = Depends(get_supabase)
):
    """
    Enregistre le feedback d'un utilisateur sur un message du chatbot
    """
    try:
        # Validation du feedback
        if request.feedback not in ['like', 'dislike']:
            raise HTTPException(
                status_code=400, 
                detail="Le feedback doit être 'like' ou 'dislike'"
            )
        
        # Mettre à jour le message dans Supabase
        result = await spbase.table('public_chat_messages').update({
            'user_feedback': request.feedback,
            'feedback_timestamp': 'now()'
        }).eq('session_id', request.session_id).eq('message_id', request.message_id).eq('role', 'assistant').execute()
        
        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="Message non trouvé ou non éligible au feedback"
            )
        
        # Créer une notification pour les feedbacks négatifs
        if request.feedback == 'dislike':
            # Compter le nombre de feedbacks négatifs dans cette session
            negative_feedback_count = await spbase.table('public_chat_messages')\
                .select('id', count='exact')\
                .eq('session_id', request.session_id)\
                .eq('user_feedback', 'dislike')\
                .execute()
            
            count = negative_feedback_count.count if negative_feedback_count.count else 1
            
            # Déterminer la priorité selon le nombre de feedbacks négatifs
            if count >= 3:
                priority = "urgent"
                title = f"⚠️ {count} feedbacks négatifs"
                content = f"Attention ! Cette conversation a reçu {count} feedbacks négatifs. Une intervention est recommandée."
            elif count >= 2:
                priority = "high"
                title = f"{count} feedbacks négatifs"
                content = f"Cette conversation a reçu {count} feedbacks négatifs."
            else:
                priority = "normal"
                title = "Feedback négatif reçu"
                content = "Un utilisateur a donné un feedback négatif sur une réponse."
            
            # Créer la notification
            await create_notification(
                spbase=spbase,
                company_id=request.company_id,
                notification_type="negative_feedback" if count < 3 else "multiple_negative_feedback",
                title=title,
                content=content,
                session_id=request.session_id,
                message_id=request.message_id,
                priority=priority,
                metadata={
                    "feedback_count": count,
                    "consecutive_negative": count >= 2
                },
                action_url=f"/dashboard/chat?session={request.session_id}",
                action_label="Analyser la conversation"
            )
        
        return {
            "success": True,
            "message": f"Feedback '{request.feedback}' enregistré avec succès",
            "session_id": request.session_id,
            "message_id": request.message_id,
            "feedback": request.feedback,
            "data": result.data[0] if result.data else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'enregistrement du feedback: {str(e)}"
        )

@app.post("/send_manual_message/")
async def send_manual_message(
    session_id: str = Form(...),
    content: str = Form(...),
    company_id: str = Form(...),
    langue: str = Form('français'),
    spbase: AsyncClient = Depends(get_supabase),
    current_user: AuthUser = Depends(get_current_user)
):
    """
    Endpoint pour envoyer un message manuel depuis le dashboard admin
    """
    try:
        # Vérifier que l'admin appartient à la même company
        if current_user.company_id != company_id:
            raise HTTPException(status_code=403, detail="Accès refusé à cette entreprise")
        
        # Sauvegarder le message dans Supabase
        message_data = await save_supabase_message(
            spbase=spbase,
            session_id=session_id,
            role="assistant",
            content=content,
            original_content=content,
            user_language=langue,
            manual_response=True
        )
        
        return {
            "success": True,
            "message": "Message envoyé avec succès",
            "message_id": message_data.get("message_id"),
            "session_id": session_id,
            "content": content
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'envoi du message: {str(e)}"
        )


@app.get("/listen_messages/{session_id}")
async def listen_messages(
    session_id: str,
    req: Request,
    spbase: AsyncClient = Depends(get_supabase)
):
    """
    Endpoint SSE pour écouter les nouveaux messages d'une session en temps réel
    """
    async def event_stream():
        # Récupérer le dernier message_id connu pour ne pas renvoyer les anciens messages
        messages = await list_messages(spbase, session_id)
        last_known_id = messages[-1].get("message_id") if messages else None
        
        try:
            while True:
                # Vérifier si le client est toujours connecté
                if await req.is_disconnected():
                    break
                
                # Récupérer les nouveaux messages
                new_messages = await list_messages(spbase, session_id)
                
                # Filtrer pour n'envoyer que les nouveaux messages
                if last_known_id:
                    new_messages = [m for m in new_messages if m.get("message_id") != last_known_id and 
                                   m.get("created_at", "") > (messages[-1].get("created_at", "") if messages else "")]
                
                # Envoyer les nouveaux messages via SSE
                for msg in new_messages:
                    if msg.get("role") == "assistant":  # Envoyer uniquement les messages assistant
                        yield sse_data({
                            "message_id": msg.get("message_id"),
                            "content": msg.get("content"),
                            "role": msg.get("role"),
                            "created_at": msg.get("created_at")
                        })
                        last_known_id = msg.get("message_id")
                
                # Mettre à jour la liste des messages
                if new_messages:
                    messages = await list_messages(spbase, session_id)
                
                # Envoyer un heartbeat toutes les 15 secondes
                await asyncio.sleep(2)
                yield sse_data({"event": "heartbeat"})
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            yield sse_data({"error": str(e)})
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/////////")
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
            "/feedback/": "Enregistrer le feedback sur un message (aucune authentification requise)",
            "/stats/": "Statistiques de votre entreprise (authentification requise)",
            "/documents/": "Lister les documents de votre entreprise (authentification requise)",
            "GET /documents/{filename}/content": "Récupérer le contenu d'un fichier DOCX (authentification requise)",
            "PUT /documents/{filename}/content": "Mettre à jour le contenu d'un fichier DOCX (authentification requise)",
            "GET /documents/{filename}/view": "Visualiser un fichier PDF (authentification requise)",
            "GET /documents/{filename}/download": "Télécharger un fichier PDF ou DOCX (authentification requise)",
            "DELETE /documents/{filename}": "Supprimer un document physique (authentification requise)",
            "/clear_cache/": "Vider le cache (admin uniquement)",
            "/health/": "Vérification de l'état de l'API",
            "/refresh_companies": "Recharger les entreprises connues",
            "/audit_tail/": "Derniers logs d'audit (limités)",
        },
        "public_endpoints": ["/ask_public/", "/sessions_public/", "/messages_public/", "/feedback/", "/health/", "/", "/audit_tail/"],
        "auth_required": "Bearer token JWT requis pour les endpoints non publics",
    }

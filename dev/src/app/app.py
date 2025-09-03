import os
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from utils.utils import system_message, safety_post_filter, build_chat_messages, controlled_fallback_response
from rag.rag import get_rag_context, rebuild_company_index, build_index, get_company_data_dir, get_company_stats, clear_company_cache
from dotenv import load_dotenv
from typing import Optional, Dict
from llm_model.julia import julia_planner, julia_executor, PlannerOutput
import asyncio
import random
from typing import Any, Dict, Optional
import asyncio
from contextlib import asynccontextmanager
from .app_utils import ExecConfirmationRequest, AuthUser, PublicChatMessage, PublicChatSession, PublicQuestionRequest, sse_event, load_public_session_from_supabase, add_public_message, create_public_session, run_exec_plan_now, get_current_user, load_all_companies_id
from pathlib import Path


from fastapi.responses import StreamingResponse
from fastapi import Request
import asyncio, inspect, json, os, random

############################################################ Variable d'Env ############################################################
load_dotenv()

# Configuration
BASE = Path(__file__).resolve().parent
DATA_DIR = BASE.parents[2] /"data" # 2 = profondeur depuis root
os.makedirs(DATA_DIR, exist_ok=True)

# Configuration Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

############################################################ Global Var ############################################################

security = HTTPBearer()
external_user_index = {}  # {company_id: {external_user_id: session_id}}
AUDIT_LOGS = []  # à remplacer par DB SUPABASE plus tard
public_sessions = {} # Stockage en mémoire des sessions publiques (en production, à remplacer par DB SUPABASE plus tard)
public_messages = {}
session_locks: Dict[str, asyncio.Lock] = {}
forbidden_user = []
COMPANIES_LIST = {}
VECTORSTORES_CACHE = {}
HEARTBEAT_SEC = 5
TASK_TIMEOUT_SEC = 120


############################################################ Parametrage FastAPI ############################################################

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Chargement de la liste des companies au démarrage de l'app."""
    global COMPANIES_LIST
    app.state.companies = await load_all_companies_id(SUPABASE_URL, SUPABASE_ANON_KEY)
    COMPANIES_LIST = app.state.companies
    yield

app = FastAPI(title="RAG API", description="API pour le système RAG avec multitenancy",lifespan=lifespan)

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En production, spécifiez les origines autorisées
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


############################################################ Def des Endpoints ############################################################

@app.get("/refresh_companies")
async def get_companies():
    global COMPANIES_LIST
    COMPANIES_LIST = await load_all_companies_id(SUPABASE_URL, SUPABASE_ANON_KEY)
    return

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
        
        # Reconstruire l'index en arrière-plan
        background_tasks.add_task(rebuild_company_index, current_user.company_id, DATA_DIR, HTTPException)
        
        return {
            "message": f"Fichier {file.filename} uploadé avec succès pour l'entreprise {current_user.company_id}",
            "company_id": current_user.company_id,
            "file_path": file_path
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'upload: {str(e)}")


@app.post("/build_index/")
async def express_build_index(current_user: AuthUser = Depends(get_current_user)):
    """Construit l'index vectoriel pour l'entreprise de l'utilisateur."""

    global VECTORSTORES_CACHE

    try:
        vectordb = build_index(current_user.company_id, DATA_DIR, HTTPException)
        VECTORSTORES_CACHE[current_user.company_id] = vectordb
        return {
            "message": f"Index construit avec succès pour l'entreprise {current_user.company_id}",
            "company_id": current_user.company_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la construction de l'index: {str(e)}")



@app.post("/ask_public/")
async def ask_question_public(request: PublicQuestionRequest):
    
    async def response_generator():

        global VECTORSTORES_CACHE, COMPANIES_LIST, public_sessions, public_messages

        try:
            # 1) Vérifier la société
            company_data_dir = get_company_data_dir(request.company_id, DATA_DIR)
            if not os.path.exists(company_data_dir):
                yield sse_event({"error": f"Entreprise {request.company_id} non trouvée ou aucun document disponible"})
                return

            session_id = None
            session = None

            # 2) Retrouver session existante (si external_user_id)
            if request.external_user_id:
                company_sessions = external_user_index.setdefault(request.company_id, {})
                if request.external_user_id in company_sessions:
                    possible_session_id = company_sessions[request.external_user_id]
                    if possible_session_id in public_sessions:
                        session_id = possible_session_id

            # 3) Créer session si nécessaire
            if not session_id:
                session, public_sessions, public_messages = await create_public_session(
                    request.company_id, public_sessions, public_messages, request.external_user_id
                )
                session_id = session.session_id
                if request.external_user_id:
                    external_user_index[request.company_id][request.external_user_id] = session_id
            else:
                session = public_sessions[session_id]
                if session.company_id != request.company_id:
                    yield sse_event({"error": "Session non compatible avec cette entreprise"})
                    return

            # 4) Verif si utilisateur banni
            if session_id + request.company_id in forbidden_user:
                yield sse_event(
                    {
                        "answer": None,
                        "company_id": request.company_id,
                        "session_id": session_id,
                        "external_user_id": request.external_user_id
                    })
                return

            # 5) Ajouter message utilisateur dans supabase
            await add_public_message(session_id, request.question, "user", public_messages)

            # 6) Contexte RAG + cache + nom
            vectordb, docs = get_rag_context(request.question, request.company_id, VECTORSTORES_CACHE)

            if request.company_id not in VECTORSTORES_CACHE:
                VECTORSTORES_CACHE[request.company_id] = vectordb

            company_name = COMPANIES_LIST.get(request.company_id, "votre entreprise")

            # 7) Historique + system + messages
            messages_history = public_messages.get(session_id, [])
            syst_msg = system_message(company_name)

            messages = build_chat_messages(
                messages_history=messages_history,
                user_input=request.question,
                context=docs,
                system_message=syst_msg,
                langue=request.langue,
                max_history_pairs=30
            )

            # 8) Planner
            planner_out: PlannerOutput = await julia_planner(messages)

            if not planner_out.continue_discussion:
                forbidden_user.append(session_id + request.company_id)
                yield sse_event(
                    {
                        "answer": "Je suis navré, je ne pourrai pas continuer cette discussion.",
                        "company_id": request.company_id,
                        "session_id": session_id,
                        "external_user_id": request.external_user_id
                    })
                return

            lang = request.langue or "Français"

            async def respond_and_log_payload(text: str) -> dict:
                safe = safety_post_filter(text)
                asyncio.create_task(add_public_message(session_id, safe, "assistant", public_messages))
                return {
                    "answer": safe,
                    "company_id": request.company_id,
                    "session_id": session_id,
                    "external_user_id": request.external_user_id
                }

            # 9) Branches “simples” => yield final puis fin
            if planner_out.action_type == "reject":
                reject = planner_out.user_visible_answer or "Désolé, je ne suis pas en mesure de vous aider sur ce point."
                yield sse_event(await respond_and_log_payload(reject))
                return

            if planner_out.action_type == "clarify":
                clarif = planner_out.user_visible_answer or (
                    "D'accord. Mais je ne suis pas sûr de clairement comprendre votre demande. "
                    "Pouvez-vous détailler encore un peu plus svp ?"
                )
                yield sse_event(await respond_and_log_payload(clarif))
                return

            if planner_out.action_type in ("answer",):
                print("je suis sous answer", sse_event(await respond_and_log_payload(planner_out.user_visible_answer)))
                if not planner_out.user_visible_answer:
                    yield sse_event(await respond_and_log_payload("Pouvez-vous me fournir un peu plus de détail svp ?"))
                    return

                print("end of answer",sse_event(await respond_and_log_payload(planner_out.user_visible_answer)))
                yield sse_event(await respond_and_log_payload(planner_out.user_visible_answer))
                return

            # 10) Cas 'tool' => ack immédiat puis exécution puis final, avec heartbeat et timeout
            if planner_out.action_type == "tool":
                list_temp_resp = [
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
                temp_resp = random.choice(list_temp_resp)

                await add_public_message(session_id, temp_resp, "assistant", public_messages)
                ack_payload = {
                    "answer": temp_resp,
                    "company_id": request.company_id,
                    "session_id": session_id,
                    "external_user_id": request.external_user_id
                }
                print("end of ack_payload",sse_event(ack_payload))
                yield sse_event(ack_payload)

                # Lancer la tâche (coroutine ou sync) en tâche asynchrone
                async def _run_task():
                    if inspect.iscoroutinefunction(run_exec_plan_now):
                        return await run_exec_plan_now(
                            session_id, request.company_id, planner_out, SUPABASE_URL, SUPABASE_ANON_KEY, public_messages
                        )
                    return await asyncio.to_thread(
                        run_exec_plan_now,
                        session_id, request.company_id, planner_out, SUPABASE_URL, SUPABASE_ANON_KEY, public_messages
                    )
                
                task = asyncio.create_task(_run_task())

                # task = asyncio.create_task(await run_exec_plan_now(session_id,
                #                                                    request.company_id,
                #                                                    planner_out,
                #                                                    SUPABASE_URL,
                #                                                    SUPABASE_ANON_KEY,
                #                                                    public_messages
                #                                                    )
                #                             )

                # Boucle de heartbeat + timeout + détection déconnexion
                try:
                    while True:
                        done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_SEC)
                        if done:
                            break
                    # Récupérer le résultat avec borne de temps
                    task_result = await task
                    final_payload = task_result if isinstance(task_result, dict) else {
                        "answer": task_result or "C'est fait !.",
                        "company_id": request.company_id,
                        "session_id": session_id,
                        "external_user_id": request.external_user_id
                    }
                    print("end of final_payload",sse_event(final_payload))
                    yield sse_event(final_payload)
                    return

                except asyncio.TimeoutError:
                    yield sse_event({"error": "Délai dépassé, veuillez réessayer."})
                    return

            # 11) Fallback par défaut
            yield sse_event(await respond_and_log_payload(controlled_fallback_response(lang)))
            return

        except Exception as e:
            yield sse_event({"error": f"Erreur lors de la génération de la réponse: {str(e)}"})
            return

            print("end of response_generator",sse_event(await respond_and_log_payload(controlled_fallback_response(lang))))

    return StreamingResponse(
        response_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no", # pour éviter le tamponnage
            "Connection": "keep-alive",
        },
    )



# @app.post("/ask_public/")
# async def ask_question_public(request: PublicQuestionRequest,
#                               background_tasks: BackgroundTasks = None,
#                               ):
    
#     """Endpoint public avec contexte basé sur external_user_id."""
    
#     global VECTORSTORES_CACHE, COMPANIES_LIST, public_sessions, public_messages

#     try:
#         # Vérification que l'entreprise existe
#         company_data_dir = get_company_data_dir(request.company_id, DATA_DIR)
#         if not os.path.exists(company_data_dir):
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"Entreprise {request.company_id} non trouvée ou aucun document disponible"
#             )

#         session_id = None
#         session = None

#         #1. Recherche auto de la session si external_user_id fourni
#         if request.external_user_id:
#             company_sessions = external_user_index.setdefault(request.company_id, {})
#             if request.external_user_id in company_sessions:
#                 possible_session_id = company_sessions[request.external_user_id]
#                 if possible_session_id in public_sessions:
#                     session_id = possible_session_id

#         #2. Création d'une session si nécessaire
#         if not session_id:
#             session, public_sessions, public_messages = await create_public_session(request.company_id, public_sessions, public_messages, request.external_user_id)
#             session_id = session.session_id
#             if request.external_user_id:
#                 external_user_index[request.company_id][request.external_user_id] = session_id
#         else:
#             session = public_sessions[session_id]
#             if session.company_id != request.company_id:
#                 raise HTTPException(status_code=400, detail="Session non compatible avec cette entreprise")

#         #3. On ajoute le message utilisateur à l'historique en mémoire
#             #3.a. Vérifie d'abord si la disussion est continuable
#         if session_id+request.company_id in forbidden_user :
#             return {
#                 "answer": None,
#                 "company_id": request.company_id,
#                 "session_id": session_id,
#                 "external_user_id": request.external_user_id
#             }
#             #3.b. ajoute ensuite le message utilisateur à l'historique en mémoire si continuable
#         await add_public_message(session_id, request.question, "user", public_messages)

#         #4. Recherche de contexte RAG + ajout vectorDB dans cache si besoin + nom companie
#             ##4.a Recherche de contexte RAG
#         vectordb, docs = get_rag_context(request.question, request.company_id, VECTORSTORES_CACHE)

#             ##4.b ajout vectorDB dans cache si besoin
#         if not request.company_id in VECTORSTORES_CACHE:
#             VECTORSTORES_CACHE[request.company_id] = vectordb

#             ##4.c Nom companie
#         company_name = COMPANIES_LIST.get(request.company_id,"votre entreprise")

#         #5. Construction du contexte de la conversation + system_message
#         messages_history = public_messages.get(session_id, [])
#         syst_msg = system_message(company_name)   

#         #6. On envoie toute la conversation au LLM
#         messages = build_chat_messages(messages_history=messages_history,
#                                        user_input=request.question,
#                                        context = docs,
#                                        system_message = syst_msg,
#                                        langue=request.langue,
#                                        max_history_pairs=30
#                                        )
        
#         #print(f"\n\n****************{messages}****************\n\n")

#         #7. Agent planner
#         # 7.1) Planner call
#         # planner_out: PlannerOutput = await julia_planner(prompt)
#         planner_out: PlannerOutput = await julia_planner(messages)

#         if not planner_out.continue_discussion :
#             forbidden_user.append(session_id+request.company_id)
#             return {
#                 "answer": "Je suis navré, je ne pourrai pas continuer cette discussion.",
#                 "company_id": request.company_id,
#                 "session_id": session_id,
#                 "external_user_id": request.external_user_id
#             }

#         # audit
#         #log_audit({"type": "planner_decision","company_id": request.company_id,"session_id": session_id,"action_type": planner_out.action_type,"safety_flags": planner_out.safety_flags},AUDIT_LOGS)

#         lang = request.langue or "Français"

#         def respond_and_log(text: str):
#             safe = safety_post_filter(text)
#             asyncio.create_task(add_public_message(session_id, safe, "assistant", public_messages))
#             #log_audit({"type": "assistant_answer","company_id": request.company_id,"session_id": session_id,"answer_len": len(safe)},AUDIT_LOGS)

#             return {
#                 "answer": safe,
#                 "company_id": request.company_id,
#                 "session_id": session_id,
#                 "external_user_id": request.external_user_id
#             }

#         # 7.2) Route by action_type
#         if planner_out.action_type == "reject":
#             reject = planner_out.user_visible_answer or "Désolé, je ne suis pas en mesure de vous aider sur ce point."
#             return respond_and_log(reject)

#         if planner_out.action_type == "clarify":
#             clarif = planner_out.user_visible_answer or "D'accord. Mais je ne suis pas sûr de clairement comprendre votre demande. Pouvez-vous détailler encore un peu plus svp ?"
#             return respond_and_log(clarif)

#         if planner_out.action_type in ("answer"):
#             if not planner_out.user_visible_answer:
#                 return respond_and_log("Pouvez-vous me fournir un peu plus de détail svp ?")
#             return respond_and_log(planner_out.user_visible_answer)

#         if planner_out.action_type == "tool":
#             # Accusé de prise en charge immédiat
#             list_temp_resp = [
#                         "D'accord. Je regarde un instant et je reviens vers vous.",
#                         "Très bien. Un instant, je reviens vers vous.",
#                         "Entendu. Je regarde un instant.",
#                         "D'accord. Je fais le point et je vous reviens.",
#                         "OK. Je vérifie en interne et je reviens vers vous.",
#                         "Entendu. Laissez-moi un instant, je reviens vers vous.",
#                         "Très bien. Je me charge de cela et je vous tiens informé.",
#                         "Ok. Je reviens vers vous rapidement.",
#                         "D'accord. Je vois de mon côté et je reviens vers vous au plus vite.",
#                     ]

#             temp_resp = random.choice(list_temp_resp)

#             await add_public_message(session_id, temp_resp, "assistant", public_messages)
#             background_tasks.add_task(run_exec_plan_now,
#                                       session_id,
#                                       request.company_id,
#                                       planner_out,
#                                       SUPABASE_URL, 
#                                       SUPABASE_ANON_KEY,
#                                       public_messages)

#             return {
#                 "answer": temp_resp, #planner_out.user_visible_answer,
#                 "company_id": request.company_id,
#                 "session_id": session_id,
#                 "external_user_id": request.external_user_id
#             }

#         # default fallback
#         return respond_and_log(controlled_fallback_response(lang))

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Erreur lors de la génération de la réponse: {str(e)}")


@app.post("/confirm_execution/")
async def confirm_execution(req: ExecConfirmationRequest):
    try:
        if not req.confirm:
            await add_public_message(req.session_id, "Action annulée. Souhaitez-vous autre chose ?", "assistant", public_messages)
            return {"status": "cancelled"}

        plan = req.exec_plan or {}
        plan["dry_run"] = False
        out = await julia_executor(plan)
        
        await add_public_message(req.session_id, f"Action exécutée: {out}", "assistant", public_messages)
        
        #log_audit({"type": "executor_run","plan": plan,"result": out,},AUDIT_LOGS)
        
        return {"status": "executed",
                "result": out,
                }
    
    except Exception as e:
        await add_public_message(req.session_id, "Une erreur est survenue lors de l'exécution.", "assistant", public_messages)
        #log_audit({"type": "executor_error", "error": str(e)}, AUDIT_LOGS)
        raise HTTPException(status_code=500, detail="Erreur d'exécution")

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
        # Essayer de charger depuis la mémoire d'abord
        if session_id in public_messages:
            messages = public_messages[session_id]
            session = public_sessions.get(session_id)
        else:
            # Essayer de charger depuis Supabase
            session, public_sessions, public_messages = await load_public_session_from_supabase(session_id, public_sessions, public_messages)
            if not session:
                raise HTTPException(status_code=404, detail="Session non trouvée")
            
            messages = public_messages.get(session_id, [])
        
        return messages
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
        background_tasks.add_task(rebuild_company_index, current_user.company_id, DATA_DIR, HTTPException)
        
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

@app.get("/audit_tail/")
async def audit_tail(n: int = 50):
    """Expose un endpoint simple pour debug"""
    return AUDIT_LOGS[-n:]


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
# test pour voir si ça marche
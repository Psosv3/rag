import os
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from rag_utils import build_index, get_answer
from dotenv import load_dotenv
import models

# Charger les variables d'environnement
load_dotenv()

app = FastAPI(title="RAG API", description="API pour le système RAG")

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

# Variable globale pour stocker l'index
vectordb = None
build_index(DATA_DIR, HTTPException)

@app.post("/upload/")
async def upload_file(file: UploadFile = File(...),
                      data_dir = DATA_DIR,
                      background_tasks: BackgroundTasks = None):
    
    """Endpoint pour uploader un fichier PDF ou DOCX."""
    if not file.filename.endswith(('.pdf', '.docx')):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF et DOCX sont acceptés")
    
    file_path = os.path.join(data_dir, file.filename)
    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        background_tasks.add_task(build_index, DATA_DIR, HTTPException)

        return {"message": f"Fichier {file.filename} uploadé avec succès"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'upload: {str(e)}")

@app.post("/build_index/")
async def express_build_index(DATA_DIR, HTTPException):
    build_index(DATA_DIR, HTTPException)
    return {"message": "Index construit avec succès"}

@app.post("/ask/")
async def ask_question(question: str = Form(...)):
    """Endpoint pour poser une question."""
    global vectordb
    if vectordb is None:
        raise HTTPException(
            status_code=400,
            detail="L'index n'est pas construit. Utilisez /build_index/ d'abord."
        )
    
    try:
        answer = get_answer(question, vectordb.as_retriever(), models.mistral_llm)
        return {"answer": answer["answer"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la génération de la réponse: {str(e)}")

@app.get("/")
async def root():
    """Page d'accueil de l'API."""
    return {
        "message": "Bienvenue sur l'API RAG",
        "endpoints": {
            "/upload/": "Uploader un fichier PDF ou DOCX",
            "/build_index/": "Construire l'index",
            "/ask/": "Poser une question"
        }
    } 
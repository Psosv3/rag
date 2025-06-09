import os
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from rag_utils import load_documents, create_vectorstore, get_answer
from dotenv import load_dotenv

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

@app.post("/upload/")
async def upload_file(file: UploadFile = File(...)):
    """Endpoint pour uploader un fichier PDF ou DOCX."""
    if not file.filename.endswith(('.pdf', '.docx')):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF et DOCX sont acceptés")
    
    file_path = os.path.join(DATA_DIR, file.filename)
    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        return {"message": f"Fichier {file.filename} uploadé avec succès"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'upload: {str(e)}")

@app.post("/build_index/")
async def build_index(openai_api_key: str = Form(...)):
    """Endpoint pour construire l'index à partir des documents."""
    global vectordb
    try:
        docs = load_documents(DATA_DIR)
        if not docs:
            raise HTTPException(status_code=400, detail="Aucun document trouvé dans le dossier data")
        
        vectordb = create_vectorstore(docs, openai_api_key)
        return {"message": "Index construit avec succès"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la construction de l'index: {str(e)}")

@app.post("/ask/")
async def ask_question(
    question: str = Form(...),
    openai_api_key: str = Form(...)
):
    """Endpoint pour poser une question."""
    global vectordb
    if vectordb is None:
        raise HTTPException(
            status_code=400,
            detail="L'index n'est pas construit. Utilisez /build_index/ d'abord."
        )
    
    try:
        answer = get_answer(question, vectordb, openai_api_key)
        return {"answer": answer}
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
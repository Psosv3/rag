import os
import faiss
import numpy as np
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import CharacterTextSplitter
from PyPDF2 import PdfReader
import docx
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

def read_pdf(file_path):
    """Lit un fichier PDF et retourne son contenu en texte."""
    try:
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        print(f"Erreur lors de la lecture du PDF {file_path}: {str(e)}")
        return ""

def read_docx(file_path):
    """Lit un fichier DOCX et retourne son contenu en texte."""
    try:
        doc = docx.Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        print(f"Erreur lors de la lecture du DOCX {file_path}: {str(e)}")
        return ""

def load_documents(data_dir):
    """Charge tous les documents PDF et DOCX du dossier spécifié."""
    docs = []
    for fname in os.listdir(data_dir):
        fpath = os.path.join(data_dir, fname)
        if fname.endswith(".pdf"):
            docs.append(read_pdf(fpath))
        elif fname.endswith(".docx"):
            docs.append(read_docx(fpath))
    return docs

def create_vectorstore(docs, openai_api_key):
    """Crée un index vectoriel à partir des documents."""
    if not docs:
        raise ValueError("Aucun document trouvé à indexer")
    
    splitter = CharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=100,
        separator="\n"
    )
    
    texts = []
    for doc in docs:
        if doc.strip():  # Ignorer les documents vides
            texts.extend(splitter.split_text(doc))
    
    if not texts:
        raise ValueError("Aucun texte à indexer après le découpage")
    
    # Configuration mise à jour des embeddings
    # embeddings = OpenAIEmbeddings(
    #     api_key=openai_api_key,
    #     model="text-embedding-ada-002"
    # )
    os.environ["OPENAI_API_KEY"] = openai_api_key
    embeddings = OpenAIEmbeddings(model="text-embedding-ada-002")

    vectordb = FAISS.from_texts(texts, embeddings)
    return vectordb

def get_answer(question, vectordb, openai_api_key):
    """Récupère la réponse à une question en utilisant le RAG."""
    if not question.strip():
        return "Veuillez poser une question valide."
    
    try:
        # Recherche des documents pertinents
        docs = vectordb.similarity_search(question, k=3)
        context = "\n".join([d.page_content for d in docs])
        
        # Création de la réponse avec OpenAI
        from langchain_openai import OpenAI
        # llm = OpenAI(
        #     openai_api_key=openai_api_key,
        #     model_name="gpt-3.5-turbo-instruct",
        #     temperature=0.7
        # )
        os.environ["OPENAI_API_KEY"] = openai_api_key
        llm = OpenAI(model="gpt-3.5-turbo-instruct", temperature=0.7)

        
        prompt = f"""Réponds à la question en te basant uniquement sur le contexte suivant.
        Si la réponse n'est pas dans le contexte, dis-le clairement.
        
        Contexte:
        {context}
        
        Question: {question}
        
        Réponse:"""
        
        return llm(prompt)
    except Exception as e:
        return f"Une erreur s'est produite: {str(e)}" 
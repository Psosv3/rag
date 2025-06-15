import os
import faiss # Facebook AI Similarity Search
import numpy as np
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import CharacterTextSplitter
from PyPDF2 import PdfReader
import docx
from dotenv import load_dotenv

from typing import Optional, Union, List, Dict
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from langchain.schema import BaseRetriever, Document
from langchain.base_language import BaseLanguageModel
import models

import uuid
from pathlib import Path
                  
from tqdm.auto import tqdm

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.docstore.in_memory import InMemoryDocstore

#---------------------------------
from mistralai import Mistral

embedding_model = "mistral-embed"

client = Mistral(api_key = models.mistral_api_key)
#---------------------------------

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


def create_vectorstore(docs: List[str],
                       *,
                       model: str = "text-embedding-3-large",
                       splitter_chunk_size: int = 800,
                       splitter_overlap: int = 100,
                       embed_batch_size: int = 128,
                       use_hnsw: bool = True,
                       hnsw_m: int = 32,
                       normalise: bool = True,
                       persist_dir: Optional[str | Path] = None,
                       show_progress: bool = True,
                       ) -> FAISS:
    """
    Create and optionally persist a FAISS vector index from document
    strings using OpenAI text-embedding-3-large.

    Args:
        docs (list[str]): Raw document strings.
        openai_api_key (str): OpenAI key with embedding access.
        model (str, optional): Embedding model name. Defaults to
            "text-embedding-3-large".
        splitter_chunk_size (int, optional): Target chunk length in chars.
        splitter_overlap (int, optional): Overlap between chunks in chars.
        embed_batch_size (int, optional): Max chunks per embedding request.
        use_hnsw (bool, optional): If True, build an HNSW index; otherwise
            a flat IP index.
        hnsw_m (int, optional): HNSW connectivity factor.
        normalise (bool, optional): L2-normalise vectors before indexing.
        persist_dir (str | Path, optional): Directory to save
            `index.faiss`/`index.pkl`. In-memory if None.
        show_progress (bool, optional): Display TQDM progress bars.

    Returns:
        langchain_community.vectorstores.FAISS: Ready-to-query vector store.
    """
    # -------------------------------------------------------------- sanity
    if not docs or all(not d.strip() for d in docs):
        raise ValueError("No non-empty documents provided.")

    # ------------------------------------------------------ smart chunking
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=splitter_chunk_size,
        chunk_overlap=splitter_overlap,
        separators=["\n\n", "\n", ".", " ", ""],  # paragraph → sentence → …
    )

    documents: List[Document] = []
    for src_id, raw in enumerate(docs):
        if not raw.strip():
            continue
        for chunk_id, chunk in enumerate(splitter.split_text(raw)):
            meta = {"source_id": src_id, "chunk_id": chunk_id}
            documents.append(Document(page_content=chunk, metadata=meta))

    if not documents:
        raise ValueError("Everything was filtered out during chunking.")

    # ------------------------------------------------------ embed in batches
    embedder = OpenAIEmbeddings(
        model=model,
        chunk_size=embed_batch_size,     # batch size :contentReference[oaicite:2]{index=2}
        show_progress_bar=show_progress,
        max_retries=6,                   # exponential back-off built-in
    )

    texts = [d.page_content for d in documents]
    vectors = embedder.embed_documents(texts)        # auto-batched

    # ------------------------------------------------------ vector prep
    vecs_np = np.asarray(vectors, dtype="float32")
    if normalise:
        faiss.normalize_L2(vecs_np)

    dimension = vecs_np.shape[1]

    # ------------------------------------------------------ index factory
    if use_hnsw:
        index = faiss.IndexHNSWFlat(dimension, hnsw_m)
        # tune search/construct parameters for better recall vs. latency
        index.hnsw.efConstruction = max(64, hnsw_m * 4)
        index.hnsw.efSearch = 128
    else:
        # Exact search (Inner Product) - accurate but slower and RAM-heavy
        index = faiss.IndexFlatIP(dimension)

    index.add(vecs_np)                                # populate index

    # ------------------------------------------------------ wrap with LangChain
    ids = [str(uuid.uuid4()) for _ in documents]
    docstore = InMemoryDocstore(dict(zip(ids, documents)))
    index_to_docstore_id = {i: doc_id for i, doc_id in enumerate(ids)}

    vectordb = FAISS(
        embedding_function=embedder,
        index=index,
        docstore=docstore,
        index_to_docstore_id=index_to_docstore_id,
    )

    # ------------------------------------------------------ optional save
    if persist_dir:
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        vectordb.save_local(str(persist_dir))          # persists index & meta :contentReference[oaicite:3]{index=3}

    return vectordb


def build_index(data_dir, HTTPException):
    """Endpoint pour construire l'index à partir des documents."""

    try:
        docs = load_documents(data_dir)
        if not docs:
            raise HTTPException(status_code=400, detail="Aucun document trouvé dans le dossier data")
        
        vectordb = create_vectorstore(docs)

        return vectordb
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la construction de l'index: {str(e)}")



def get_answer(question: str,
               retriever: BaseRetriever,
               llm: BaseLanguageModel,
               *,
               k: int = 3,
            #    chain_type: str = "refine", # or "stuff", "map_reduce", "refine"…
               chain_type: str = "map_reduce",
               temperature: float = 0.0,
               max_tokens: int = 512,
               return_sources: bool = True,
               ) -> Union[str, Dict[str, Union[str, List[Document]]]]:
    """
    Retrieve an answer to a question via a RAG pipeline.

    Retrieves the top-k most relevant passages using the provided retriever,
    then generates a response with the specified LLM. Optionally returns source
    documents alongside the answer.

    Args:
        question (str): The question to answer.
        retriever (BaseRetriever): The retriever for document lookup.
        llm (BaseLanguageModel): The language model for generation.
        k (int, optional): Number of passages to retrieve. Defaults to 3.
        chain_type (str, optional): RetrievalQA chain type ("stuff", 
            "map_reduce", "refine"). Defaults to "stuff".
        temperature (float, optional): Sampling temperature for the LLM. 
            Defaults to 0.0.
        max_tokens (int, optional): Maximum tokens to generate. Defaults to 512.
        return_sources (bool, optional): If True, include source documents 
            in the output. Defaults to False.

    Returns:
        Union[str, Dict[str, Union[str, List[Document]]]]:
            If `return_sources` is False, returns the answer text.
            If True, returns a dict with:
              - "answer" (str): the generated answer  
              - "sources" (List[Document]): the retrieved source documents
    """

    # 1. Validate
    if not question or not question.strip():
        raise ValueError("La question est vide - veuillez fournir du texte.")

    # 2. Configure retriever
    # retriever.search_kwargs["k"] = k

    # 3. Build prompt template
    template = (
        "Vous êtes un assistant expert en RAG. "
        "Répondez à la question en vous basant *uniquement* sur le contexte fourni. "
        "Si l'information n'y figure pas, dites-le clairement.\n\n"
        "Contexte :\n{context}\n\n"
        "Question : {question}\n\n"
        "Réponse :"
    )
    prompt = PromptTemplate(
        template=template,
        input_variables=["context", "question"]
    )

    # 4. Instantiate the RetrievalQA chain
    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type=chain_type,
        retriever=retriever,
        return_source_documents=return_sources,
        chain_type_kwargs={
            "prompt": prompt,
            #"max_tokens_limit": max_tokens,
            #"temperature": temperature
        }
    )

    # 5. Run the chain and handle errors
    try:
        result = qa_chain({"query": question})
    except Exception as e:
        raise RuntimeError(f"Erreur RAG : {e}")

    # 6. Return answer (and sources if requested)
    if return_sources:
        return {
            "answer": result["result"],
            "sources": result["source_documents"]
        }
    return result["result"]

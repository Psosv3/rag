import os
import faiss
import numpy as np
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from dotenv import load_dotenv
from typing import Optional, Union, List, Dict
from langchain.schema import Document
import asyncio
from pathlib import Path
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.docstore.in_memory import InMemoryDocstore
from utils.utils import load_documents, split_documents, _tokens, _lexical_hit
from llm_model.model_server import client_mistral, mistral_llm, planner_model_backup, planner_core_model


# Load environment variables
load_dotenv()

SELF_CHECK_PROMPT = (
    "Vérifie la réponse suivante par rapport au contexte fourni. "
    "Répond STRICTEMENT par 'OK' si chaque affirmation est supportée par le contexte; "
    "sinon répond 'INSUFFISANT'. "
    "Contexte:\n{context}\n\nRéponse:\n{answer}\n\nVerdict:"
)

async def rebuild_company_index(company_id: str, DATA_DIR, HTTPException):
    """Fonction pour reconstruire l'index d'une entreprise (utilisée en arrière-plan)."""
    try:
        await build_index(company_id, DATA_DIR, HTTPException)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la re-construction de l'index: {str(e)}")

def get_company_data_dir(company_id: str, base_data_dir: str = "data") -> str:
    """Retourne le répertoire de données pour une entreprise spécifique."""
    company_dir = os.path.join(base_data_dir, f"company_{company_id}")
    os.makedirs(company_dir, exist_ok=True)
    return company_dir

def get_company_index_dir(company_id: str, base_data_dir: str = "data") -> str:
    """Retourne le répertoire d'index pour une entreprise spécifique."""
    index_dir = os.path.join(base_data_dir, f"indexes", f"company_{company_id}")
    os.makedirs(index_dir, exist_ok=True)
    return index_dir

def create_vectorstore(docs: List[str],
                      *,
                      augment_rag : bool = True,
                      model: str = "text-embedding-3-large",
                      splitter_chunk_size: int = 256,
                      splitter_overlap: int = 64,
                      embed_batch_size: int = 256,
                      use_hnsw: bool = False, # anciennement True pour test (à voir si c'est pas trop long en prod), Normalisation L2  à 1 des vecteurs = produit scalaire devient exactement le cosinus (Avec normalise=True, IndexFlatIP ≈ cosine similarity exacte), sinon absence de normalisation : avantage des vecteurs à grande norme. garder FlatIP pour petits/moyens jeux ou si tu veux du 100 % exact / activer use_hnsw dès ~10^5–10^6 vecteurs ou que la latence devient critique, et augmenter efSearch si le rappel est trop bas.
                      hnsw_m: int = 32,
                      normalise: bool = True,
                      persist_dir: Optional[str | Path] = None,
                      show_progress: bool = True,
                      ) -> FAISS:
    """
    Create and optionally persist a FAISS vector index from document strings.
    """
    if not docs or all(not d.strip() for d in docs):
        raise ValueError("Empty documents provided.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1_000_000 if augment_rag else splitter_chunk_size,
        chunk_overlap=splitter_overlap,
        separators=["\n\n", "\n", ".", " ", ""],
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

    embedder = OpenAIEmbeddings(
        model=model,
        chunk_size=embed_batch_size,
        show_progress_bar=show_progress,
        max_retries=6,
    )

    texts = [d.page_content for d in documents]
    vectors = embedder.embed_documents(texts)

    vecs_np = np.asarray(vectors, dtype="float32")
    if normalise:
        faiss.normalize_L2(vecs_np)

    dimension = vecs_np.shape[1]

    if use_hnsw:
        index = faiss.IndexHNSWFlat(dimension, hnsw_m)
        index.hnsw.efConstruction = max(64, hnsw_m * 4)
        index.hnsw.efSearch = 128
    else:
        index = faiss.IndexFlatIP(dimension)

    index.add(vecs_np)

    ids = [f"{d.metadata['source_id']}:{d.metadata['chunk_id']}" for d in documents]
    docstore = InMemoryDocstore(dict(zip(ids, documents)))
    index_to_docstore_id = {i: doc_id for i, doc_id in enumerate(ids)}

    vectordb = FAISS(
        embedding_function=embedder,
        index=index,
        docstore=docstore,
        index_to_docstore_id=index_to_docstore_id,
    )

    if persist_dir:
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        vectordb.save_local(str(persist_dir))

    return vectordb

async def build_index(company_id: str, data_dir: str = "data", update_resume : bool = True, HTTPException=None):
    """Builds the vectorstore index from documents for a specific company."""

    try:
        # Répertoire spécifique à l'entreprise
        company_data_dir = get_company_data_dir(company_id, data_dir)
        company_index_dir = get_company_index_dir(company_id, data_dir)
        
        docs = load_documents(company_data_dir) # Charger les documents de l'entreprise : return = list[doc1_str, docs2_str, ...]

        company_synth = None
        if update_resume:
            full_docs = "\n--------\n".join(docs)
            try: 
                company_synth = await company_resume(full_docs)
            except :
                company_synth = f"Veuillez déduire le résumé de l'entreprise à partir des contextes fournis ci-dessous."

        split_docs = split_documents(docs)
        if not split_docs:
            if HTTPException:
                raise HTTPException(status_code=400, detail=f"Aucun document trouvé pour l'entreprise {company_id}")
            else:
                raise ValueError(f"Aucun document trouvé pour l'entreprise {company_id}")
        
        #Créer le vectorstore avec persistance
        vectordb = create_vectorstore(split_docs, persist_dir=company_index_dir)
        return vectordb, company_synth 
    
    except Exception as e:
        if HTTPException:
            raise HTTPException(status_code=500, detail=f"Erreur lors de la construction de l'index: {str(e)}")
        else:
            raise e

def get_or_load_vectorstore(company_id: str, vectorstores_cache : dict, data_dir: str = "data", HTTPException=None) -> Optional[FAISS]:
    """Récupère le vectorstore depuis le cache ou le charge depuis le disque."""

    # Vérifier le cache
    if company_id in vectorstores_cache:
        return vectorstores_cache[company_id]

    # Essayer de charger depuis le disque
    company_index_dir = get_company_index_dir(company_id, data_dir)
    if os.path.exists(company_index_dir) and os.listdir(company_index_dir):
        try:
            embedder = OpenAIEmbeddings(model="text-embedding-3-large")
            vectordb = FAISS.load_local(company_index_dir, embedder, allow_dangerous_deserialization=True)
            return vectordb
        
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur lors du chargement de l'index pour l'entreprise {company_id}: {str(e)}")

    return None


def augment_chunks(docs, vectorstore : FAISS, window=1, active : bool = True):

    if not active :
        return docs
    
    augmented = []
    seen = set()

    for d in docs:
        source = d.metadata.get("source_id")
        chunk_id = d.metadata.get("chunk_id")

        # Avoid reprocessing the same doc
        if (source, chunk_id) in seen:
            continue
        seen.add((source, chunk_id))

        # Collect neighbors
        merged_texts = []
        for offset in range(1, window + 1):
            prev_id = chunk_id - offset
            next_id = chunk_id + offset

            for neighbor_id in range(prev_id, next_id+1):
                try:
                    neighbor = vectorstore.docstore.search(f"{int(source)}:{int(neighbor_id)}")
                    if neighbor:
                        merged_texts.append(neighbor.page_content)
                except:
                    pass

        # Merge and truncate
        merged_text = "\n\n".join(merged_texts)

        new_doc = Document(page_content=merged_text, metadata=d.metadata)
        augmented.append(new_doc)

    return augmented


async def get_rag_context(question: str,
               company_id: str,
               vectorstores_cache: dict,
               data_dir: str = "data",
               *,
               k: int = 10,
               final_k: int = 5,
               HTTPException=None,
               activate_augment_chunks: bool = False,
               rerank: bool = False,
               lexical_filter: bool = False,
               shortlist_factor: int = 5,
               ) -> Union[str, Dict[str, Union[str, List[Document]]]]:
    

    """Retrieve a context to a question via a RAG pipeline with reranking for a specific company.
    Args:
        question (str): The user question in natural language. Must be non-empty.
        company_id (str): Identifier of the company whose vector index should be used.
        data_dir (str, optional): Root directory where company data and vector indexes are stored.
        Defaults to "data".
        k (int, optional): Number of top documents to retrieve from the vector index before reranking.
        Must be >= 1. Defaults to 5.
        rerank_top_n (int, optional): Number of documents to keep after reranking with FlashRank.
        Must be >= 1. Defaults to 3.
    Returns:
        String
    Raises:
        ValueError: If the question is empty/whitespace only, or if no index exists for the given company_id.
        RuntimeError: If an error occurs during retrieval or QA chain execution.
    """
    if not question or not question.strip():
        raise HTTPException(status_code=400, detail="Question vide.")

    # Récupérer le vectorstore de l'entreprise
    vectordb = get_or_load_vectorstore(company_id, vectorstores_cache, data_dir, HTTPException)
    if vectordb is None:
        raise HTTPException(status_code=500, detail=f"Aucun index trouvé pour l'entreprise {company_id}. Veuillez d'abord construire l'index.")
    
    # 1) Dense shortlist (plus grande que k)
    shortlist_k = max(k * shortlist_factor, k)
    dense_candidates: List[Document] = await asyncio.get_running_loop().run_in_executor(None, lambda: vectordb.similarity_search(question, k=shortlist_k))

    # 2) Filtre/boost lexical (priorise les chunks contenant les mots clés)
    if lexical_filter:
        qtok = _tokens(question)
        hits, rest = [], []
        for d in dense_candidates:
            (hits if _lexical_hit(d.page_content, qtok) > 0 else rest).append(d)
        preselected = (hits + rest)[:k]     # d’abord les “hits”, puis on complète
    else:
        preselected = dense_candidates[:k]

    # 3) Compression (FlashRank / ton compressor existant) : On compresse uniquement les pré-sélectionnés   
    if rerank :
        if compressor is not None:
            docs = compressor.compress_documents(preselected, question)
    else:
        docs = preselected[:final_k]

    # 4. Expand each doc with neighbors
    augmented_docs = augment_chunks(docs, vectordb, active=activate_augment_chunks)
    
    return (vectordb, "\n\n".join(d.page_content for d in augmented_docs))


def clear_company_cache(company_id: str, vectorstores_cache : dict):
    """Vide le cache vectorstore pour une entreprise spécifique."""
    if company_id in vectorstores_cache:
        del vectorstores_cache[company_id]

def get_company_stats(company_id: str, vectorstores_cache : dict, data_dir: str = "data") -> Dict:
    """Retourne des statistiques sur les documents et l'index d'une entreprise."""

    company_data_dir = get_company_data_dir(company_id, data_dir)
    company_index_dir = get_company_index_dir(company_id, data_dir)
    
    # Compter les documents
    doc_count = 0
    total_size = 0
    if os.path.exists(company_data_dir):
        for fname in os.listdir(company_data_dir):
            if fname.endswith(('.pdf', '.docx')):
                doc_count += 1
                fpath = os.path.join(company_data_dir, fname)
                total_size += os.path.getsize(fpath)
    
    # Vérifier si l'index existe
    index_exists = os.path.exists(company_index_dir) and os.listdir(company_index_dir)
    
    return {
        "company_id": company_id,
        "document_count": doc_count,
        "total_size_bytes": total_size,
        "index_exists": index_exists,
        "in_cache": company_id in vectorstores_cache
    } 


async def rewrite_rag_augmentor(doc : str, client_mistral = client_mistral) -> str:

    system_message = f"""
Tu es un assistant de restructuration pour un pipeline RAG.
Ton rôle est de baliser un document en le segmentant en section thématiques (séparation par balise), 
tout en respectant strictement sa structure et son ordre d'origine.

Balise : <!--|||SECTION|||-->

Contraintes de sortie (obligatoires) :
- Ne retire aucune information du document original.
- Ne rajoute aucune information qui n'est pas dans le document original.
- Conserve exactement l'ordre du document. Ne déplace pas, ne réorganise pas, ne fusionne pas de passages éloignés.
- Regroupe uniquement les parties consécutives qui concernent le même sujet / thème, dans une seule section.
- Il est interdit de créer plusieurs section successives avec le même titre ou le même sujet.
- Chaque section doit être structurée ainsi :

### Sujet : <titre court, factuel, issu du texte>
<paragraphe(s) réécrits pour clarté, sans changer le sens>
<!--|||SECTION|||-->

- Le sous-titre et son contenu doivent toujours être dans le même bloc, avant la balise.
- Aucun autre texte hors sections (pas d'intro, pas de conclusion, pas de commentaires).
- Utilise uniquement la balise fournie pour séparer les sections.
- Préserve intégralement les faits : noms propres, chiffres, détails, dates, citations, URLs, adresse, contacts, lieux.

Règles de segmentation :
- Regroupe par sujet ; fusionne les passages liés si c'est le même thème.
- Si un passage est trop court pour avoir un titre détaillé, crée quand même un sous-titre minimal fidèle (ex. "### Sujet : Brève remarque").
"""
    messages = [{"role": "system", "content": system_message}] + [{"role": "user", "content": f"Réécrit le document suivant en suivant strictement les instructions données: \n\n{doc}\n\n"}]

    try:
        chat_completion  = await planner_model_backup.chat.completions.create(
            model=planner_core_model,
            messages=messages,
            temperature=0,
            top_p=1,
            stream=False,
        )
        _content = chat_completion.choices[0].message.content.strip() or "{}"
        return _content
    except :
        print("[ERROR] : fallback rewrite_rag_augmentor to Mistral")
        processed_doc =  await client_mistral.chat.complete_async(
            model=mistral_llm,
            messages=messages,
            temperature=0,
            top_p=1,
            stream=False,
        )
        _content = processed_doc.choices[0].message.content
        return _content


async def company_resume(doc : str, client_mistral = client_mistral) -> str:
    system_message = f"""
### Rôle :
Tu es un expert en synthèse d'informations.
Ta mission est de produire un résumé concis et complet (100 à 200 mots) d'une entreprise, organisation ou institution, à partir d'un document fourni par l'utilisateur.

### Objectifs :
- Extraire les informations clés (identité, secteur, activités, services, localisation, contacts, spécificités, etc.).
- Structurer le résumé pour qu'il soit clair, informatif et directement exploitable.
- Prioriser les éléments qui définissent l'activité principale, la valeur ajoutée et les modalités pratiques client (accès, documents, horaires, etc.).

### Consignes de Synthèse :
1. Identité et Localisation : Commence par le nom de l'entreprise/organisation, son secteur d'activité, et sa localisation (ville, adresse si pertinente).
Ajoute les coordonnées principales (téléphone, email, site web, réseaux sociaux si disponibles).
2. Activités et Services :
    - Résume les services/produits proposés en 2-3 phrases max.
    - Mentionne les spécificités (ex : disponibilité H24, services sur rendez-vous, tarification, innovations, etc.).
3. Points Clés Distinctifs :
    - Si le document en mentionne, mets en avant 1-2 principaux éléments différenciants de l'entreprise/organisation (ex : engagement qualité, accessibilité, technologie utilisée, partenariats, labels, etc.).
4. Modalités Pratiques :
    - Horaires d'ouverture, disponibilités (ex : 24/7, sur rendez-vous).
    - Conseils utiles pour les clients/utilisateurs.
5. Style et Format :
    - Phrases courtes et directes, sans jargon.
    - Évite les listes : intègre les informations dans des phrases fluides.
    - Ton neutre et professionnel, adapté au secteur (médical, commercial, associatif, etc.).
    - Pas de détails superflus : concentre-toi sur ce qui est essentiel pour comprendre l'entreprise et ses services.
6. Exemple de sortie attendue :
"EcoTech Solutions, basée à Lyon, est un leader français des solutions d'énergie renouvelable pour les particuliers et entreprises.
L'entreprise conçoit et installe des panneaux solaires, pompes à chaleur et systèmes de stockage d'énergie, avec un accompagnement clé en main incluant audit énergétique et financement vert.
Labellisée RGE, elle garantit des installations durables et un suivi post-vente réactif. Les devis sont gratuits et réalisables en ligne ou sur rendez-vous en agence (ouverte du lundi au vendredi, 9h-18h).
EcoTech Solutions se distingue par son engagement zéro déchet et son partenariat avec EDF pour des tarifs avantageux.
Contacts : 04 78 00 00 00 / contact@ecotech.fr."
7. Contraintes :
    - Longueur maximale : 200 mots.
    - Ne pas répéter les informations.
    - Vérifier l'exactitude des données (NE JAMAIS INVENTER, se baser STRICTEMENT sur le document).
"""
    messages = [{"role": "system", "content": system_message}] + [{"role": "user", "content": f"Fait un résumé - synthèse de l'entreprise suivant en respectant les consignes à la lettre: \n\n{doc}\n\n"}]

    processed_doc =  await client_mistral.chat.complete_async(
        model=mistral_llm,
        messages=messages,
        temperature=0,
        top_p=1,
        stream=False
    )
    return processed_doc.choices[0].message.content
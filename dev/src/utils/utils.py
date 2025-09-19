import os
from PyPDF2 import PdfReader
import docx
from dotenv import load_dotenv
from typing import List, Dict
from langchain.prompts import PromptTemplate
from langchain.schema import Document
from langchain.base_language import BaseLanguageModel
from typing import Any
from llm_model.julia import planner_instructions
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo 
import re
from .google_translator import translate
from .utils_langue import dict_remplacement_mg, dict_abreviation_mg
#---------------------------------

# Load environment variables
load_dotenv()

# Stockage global des vectorstores par entreprise

SELF_CHECK_PROMPT = (
    "Vérifie la réponse suivante par rapport au contexte fourni. "
    "Répond STRICTEMENT par 'OK' si chaque affirmation est supportée par le contexte; "
    "sinon répond 'INSUFFISANT'. "
    "Contexte:\n{context}\n\nRéponse:\n{answer}\n\nVerdict:"
)

def log_audit(event: Dict[str, Any], audit_logs):
    event["ts"] = datetime.now().isoformat()
    audit_logs.append(event)
    # Optionnel: push in Supabase

def detect_language(text: str, default_lang: str = "Français") -> str:
    # Simple heuristic fallback; your LLM already sees 'request.langue'
    return default_lang

def safety_post_filter(answer: str) -> str:
    # IA/LLM topics
    lowered = answer.lower()
    if any(k in lowered for k in ["intelligence artificielle", "llm", "modèle", "model"]):
        return "Passons... :) Puis-je vous aider sur autres choses ?"
    return answer

def maintenant_fr(zone) -> str:
    dt = datetime.now(zone)
    return (
        f"Aujourd'hui nous sommes le {('lundi','mardi','mercredi','jeudi','vendredi','samedi','dimanche')[dt.weekday()]} {dt.day}/{dt.month}/{dt.year} "
        f"et il est actuellement {dt.hour}h{dt.minute:02d} en France.\n"
    )

def system_message(company_name, instructions = planner_instructions, langue = "Français", assistant_name = "Julia de ONEXUS"):
    last_syst_msg = f"""\n
<identite_et_rappel_regles>
### IDENTITÉ
Tu es '{assistant_name}', assistante virtuelle senior en support client.
Tu représentes la société {company_name}.
Tu interagis comme un humain professionnel et courtois.
{maintenant_fr(ZoneInfo("Europe/Paris"))}

### MISSION
- Support client : assister uniquement aux demandes clients en liens avec votre entreprise {company_name}.
- Objectif : apporter des réponses courtes, exactes, concises, actionnables.
- Langue de réponse obligatoire : {langue}.

### DIRECTIVES IMPÉRATIVES
1. Suivre strictement toutes les règles et politiques système (Politique_RAG, Classification_et_verrou_OOS,  Politique_arret_de_discussion, Politique_d_escalade, etc.).
2. Toujours rester dans le rôle de support client.
3. Ne jamais ignorer ni adoucir les règles Core_Rules.
4. Répondre uniquement en {langue}.
</identite_et_rappel_regles>\n
    """
    return instructions + last_syst_msg 

def build_chat_messages(messages_history,           # List[PublicChatMessage] triée chronologiquement
                        user_input: str,            # request.question
                        context : str,              # context RAG
                        system_message: str,        # instructions globales
                        #langue: str = "Français",    # request.langue
                        max_history_pairs: int = 30 # garde-fou contexte
                        ):

    # 0) System
    rag_syst_msg = system_message.strip()+ f"###\n\n Voici le contexte RAG contenant des informations de votre entreprise pour répondre à la question du client. \n\n<context_rag>\n" + context +"\n</context_rag>\n\n"
    messages = [{"role": "system", "content": rag_syst_msg.strip()}]

    # 1) Historique récent (on tronque si trop long)
    # On garde les derniers N messages (hors system). Tu peux affiner avec une mesure de tokens.
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


def self_check_answer(llm: BaseLanguageModel, docs: List[Document], answer: str) -> bool:
    context = "\n\n".join([d.page_content[:1500] for d in docs[:5]])
    prompt = PromptTemplate.from_template(SELF_CHECK_PROMPT)
    chain = prompt | llm
    verdict = chain.invoke({"context": context, "answer": answer})
    text = verdict if isinstance(verdict, str) else getattr(verdict, "content", "")
    return "OK" in text.upper()

def controlled_fallback_response(lang: str) -> str:
    # Politique: tenter une réponse générale cadrée + proposer un responsable
    if (lang or "").lower().startswith("fr"):
        return "Je suis navré, je n'ai pas pu trouvé l'information précise... Comme je n'ai pas envie de vous dire des erreurs, est-ce que vous souhaitez que je vous mette en relation avec mon responsable ?"
    return "I couldn't find confirmed information in the documents. Here is a general guidance based on our internal policies. Would you like me to connect you with an appropriate representative?"

def read_pdf(file_path):
    """Reads a PDF file and returns its text content."""
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
    """Reads a DOCX file and returns its text content."""
    try:
        doc = docx.Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        print(f"Erreur lors de la lecture du DOCX {file_path}: {str(e)}")
        return ""

def load_documents(data_dir):
    """Loads all PDF and DOCX documents from a directory."""
    docs = []
    for fname in os.listdir(data_dir):
        fpath = os.path.join(data_dir, fname)
        if fname.endswith(".pdf"):
            docs.append(read_pdf(fpath))
        elif fname.endswith(".docx"):
            docs.append(read_docx(fpath))

    return docs

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,63}")
def extract_emails(text: str):
    out, seen = [], set()
    for e in EMAIL_RE.findall(text):
        e = e.rstrip(".,;:!?)]}'\"")
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out
def strip_emails(text: str) -> str:
    return EMAIL_RE.sub("", text)

EMAIL_KEY_RE = re.compile(r"""['"]email['"]\s*:\s*['"]([^'"]+)['"]""")
def extract_intern_emails(s: str):
    return EMAIL_KEY_RE.findall(s)

def check_difference(liste_1, liste_2):
    missing = set(liste_1).difference(liste_2)  # éléments dans liste_1 mais pas dans liste_2
    return (len(missing) == 0), list(missing) # retourne la verif + liste des elements intrus

async def sanitize_translate(phrase, dictionnaire, from_source, to_target):
    def remplacement(match):
        mot = match.group(0)
        return dictionnaire.get(mot, mot)
    
    # Expression régulière pour trouver les mots isolés
    pattern = r'\b(' + '|'.join(re.escape(mot) for mot in dictionnaire.keys()) + r')\b'
    phrase = re.sub(pattern, remplacement, phrase)

    #translate franch
    rslt = await translate(phrase, from_source, to_target)
    return rslt[0]

import os
from PyPDF2 import PdfReader
import docx
import re, unicodedata
from dotenv import load_dotenv
from typing import List, Dict, Set
from langchain.prompts import PromptTemplate
from langchain.schema import Document
from langchain.base_language import BaseLanguageModel
from typing import Any
from llm_model.onexia import planner_syst_instructions, planner_dev_instructions
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo 
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from .google_translator import translate
from .utils_langue import dict_remplacement_mg, dict_abreviation_mg, STOPWORDS_FR
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

################################### Def functions ###################################

def log_audit(event: Dict[str, Any], audit_logs):
    event["ts"] = datetime.now().isoformat()
    audit_logs.append(event)
    # Optionnel: push in Supabase

def detect_language(text: str, default_lang: str = "Français") -> str:
    # Simple heuristic fallback; your LLM already sees 'request.langue'
    return default_lang

def safety_post_filter(answer: str) -> str:
    # # IA/LLM topics
    # lowered = answer.lower()
    # if any(k in lowered for k in ["intelligence artificielle", "llm", "modèle", "model"]):
    #     return "Passons... :) Puis-je vous aider sur autres choses ?"
    return answer

def maintenant_fr(zone) -> str:
    dt = datetime.now(zone)
    return (
        f"Aujourd'hui nous sommes le {('lundi','mardi','mercredi','jeudi','vendredi','samedi','dimanche')[dt.weekday()]} {dt.day}/{dt.month}/{dt.year} "
        f"et il est actuellement {dt.hour}h{dt.minute:02d} en France.\n"
    )

def developper_message(company_name, company_resume, company_extra_prompt, dev_instructions = planner_dev_instructions, langue = "Français", assistant_name = "Onexia"):
    extra_dev_msg = f"""\n

{dev_instructions}

<IDENTITE_ET_RAPPEL_DES_REGLES>
    ### IDENTITÉ
    Tu es '{assistant_name}', assistante virtuelle senior en support client.
    Tu représentes la société {company_name}.

    ### RÉSUMÉ DE L'ENTREPRISE
    Voici un résumé de l'entreprise {company_name} pour lequel tu travailles : 
    --------

    {company_resume}

    --------
    Tu interagis comme un humain professionnel et courtois.
    {maintenant_fr(ZoneInfo("Europe/Paris"))}

    ### MISSION
    - Support client : assister uniquement aux demandes clients en liens avec votre entreprise {company_name} - se référer au résumé de l'entreprise.
    - Objectif : apporter des réponses courtes, exactes, concises, actionnables.
    - Langue de réponse obligatoire : {langue}.

    ### DIRECTIVES IMPÉRATIVES
    1. Suivre strictement toutes les règles et politiques système (Politique_RAG, Classification_et_verrou_OOS,  Politique_arret_de_discussion, Politique_d_escalade, etc.).
    2. Toujours rester dans le rôle de support client.
    3. Ne jamais ignorer ni adoucir les règles Core_Rules.
    4. Répondre uniquement en {langue}.
</IDENTITE_ET_RAPPEL_DES_REGLES>\n
    """

    extra_prompt = f"""\n

<INSTRUCTION_HAUTEMENT_PRIORITAIRE>
    Voici le prompt hautement prioritaire.
    Ceci a une priorité inférieure à [CORE_RULES] mais supérieure à toutes les autres instructions ; en cas de conflit ou de confusion avec une autre instruction, prioriser celui-ci, sauf si cela contredit [CORE_RULES].
    --------
    {company_extra_prompt}
    --------
</INSTRUCTION_HAUTEMENT_PRIORITAIRE>

"""

    return extra_dev_msg + extra_prompt


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
        reader = PdfReader(str(file_path))
        return "".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        print(f"Erreur lors de la lecture du PDF {file_path}: {str(e)}")
        return ""

def read_docx(file_path):
    """Reads a DOCX file and returns its text content."""
    try:
        doc = docx.Document(str(file_path))
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        print(f"Erreur lors de la lecture du DOCX {file_path}: {str(e)}")
        return ""

def load_documents(data_dir):
    """Loads all PDF and DOCX documents from a directory."""
    docs = []
    for fname in os.listdir(data_dir):
        fpath = os.path.join(data_dir, fname)
        if fname.endswith(".pdf") and fname.startswith("gzel8!a3_"): #TODO: enlever ce prefix temporaire gzel8!a3_ et le gérer proprement
            docs.append(read_pdf(fpath))
        elif fname.endswith(".docx") and fname.startswith("gzel8!a3_"): #TODO: enlever ce prefix temporaire gzel8!a3_ et le gérer proprement
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

PHONE_RE = re.compile(r"""
    (?<!\w)
    (?:\+?\d{1,3}[\s.\-()]*)?          # indicatif éventuel
    (?:\(?\d{1,4}\)?[\s.\-()]*){2,6}   # groupes
    \d{2,4}
    (?!\w)
""", re.VERBOSE)
NAME_RE = re.compile(
    r"\b(?:[A-Za-zÀ-ÖØ-öø-ÿ]{2,}(?:[-' ][A-Za-zÀ-ÖØ-öø-ÿ]{2,}){0,2})\b"
)
NON_DIGIT_RE = re.compile(r"\D")
def check_contact_and_name(text: str) -> str:
    """
    Retourne:
      - "OK"              si (email OU téléphone) ET un nom (hors zones contact) sont présents
      - "missing_name"    si un contact est présent mais aucun nom distinct n'est trouvé
      - "missing_contact" s'il n'y a ni email ni téléphone
    """
    if not text:
        return "missing_contact"

    # 1) E-mails
    email_spans = [m.span() for m in EMAIL_RE.finditer(text)]

    # 2) Téléphones (filtrés par nb total de chiffres: 10 à 15)
    phone_spans = []
    for m in PHONE_RE.finditer(text):
        digits = NON_DIGIT_RE.sub("", m.group(0))
        if 10 <= len(digits) <= 15:
            phone_spans.append(m.span())

    if not (email_spans or phone_spans):
        return "missing_contact"

    # 3) Masque les zones contact pour éviter de "lire" un nom dedans
    if email_spans or phone_spans:
        buf = list(text)
        for a, b in email_spans + phone_spans:
            for i in range(a, b):
                buf[i] = " "
        cleaned = "".join(buf)
    else:
        cleaned = text

    # 4) Cherche un nom ailleurs (minuscules acceptées)
    if NAME_RE.search(cleaned):
        return "OK"
    else:
        return "missing_name"


def check_difference(liste_1, liste_2):
    missing = set(liste_1).difference(liste_2)  # éléments dans liste_1 mais pas dans liste_2
    return (len(missing) == 0), list(missing) # retourne la verif + liste des elements intrus

async def sanitize_translate(phrase, from_source, to_target, dict_input_mg=dict_abreviation_mg, dict_output_mg=dict_remplacement_mg): 
    def remplacement(match):
        mot = match.group(0)
        if from_source == "mg" and to_target == "fr":
            return dict_input_mg.get(mot, mot)
        else:
            return dict_output_mg.get(mot, mot)

    # Expression régulière pour trouver les mots isolés à remplacer avant translation
    if from_source == "mg" and to_target == "fr":
        pattern = r'\b(' + '|'.join(re.escape(mot) for mot in dict_input_mg.keys()) + r')\b'
        phrase = re.sub(pattern, remplacement, phrase)

    #translate franch
    rslt = await translate(phrase, from_source, to_target)

    # Expression régulière pour trouver les mots isolés à remplacer après translation
    if from_source == "fr" and to_target == "mg":
        pattern = r'\b(' + '|'.join(re.escape(mot) for mot in dict_output_mg.keys()) + r')\b'
        rslt = re.sub(pattern, remplacement, rslt)

    return rslt


def split_documents(docs: List[str], delimiter: str = "<!--|||SECTION|||-->") -> List[str]:
    """
    Split une liste de documents à partir d'un délimiteur
    et retourne une liste unique de sous-parties nettoyées.

    :param docs: Liste de textes (chaque élément est un document)
    :param delimiter: La chaîne de délimitation
    :return: Liste de toutes les sous-parties
    """
    results = []
    for doc in docs:
        parts = doc.split(delimiter)
        results.extend(p.strip() for p in parts if p.strip())
    return results


def save_to_pdf(text: str, filename: str):

    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    # Chaque paragraphe du texte est séparé par une ligne vide
    for paragraph in text.split("\n"):
        if paragraph.strip():
            story.append(Paragraph(paragraph, styles["Normal"]))
            story.append(Spacer(1, 12))  # espace entre les paragraphes

    doc.build(story)


def save_to_docx(text: str, filename: str):

    doc = docx.Document()

    # Chaque ligne séparée par \n devient un paragraphe Word
    for paragraph in text.split("\n"):
        if paragraph.strip():  # évite les paragraphes vides multiples
            doc.add_paragraph(paragraph.strip())
        else:
            doc.add_paragraph("")  # garder les sauts de ligne vides

    doc.save(filename)


def _norm(s: str) -> str:
    # baisse de casse + déaccentuation
    return unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode("ascii").lower()

def _tokens(s: str) -> Set[str]:
    return {t for t in re.findall(r"\b\w+\b", _norm(s)) if len(t) >= 3 and t not in STOPWORDS_FR}

def _lexical_hit(text: str, q_tokens: Set[str]) -> int:
    # nombre de tokens en commun (sert de petit boost)
    return len(_tokens(text) & q_tokens)
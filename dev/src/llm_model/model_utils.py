import json
from typing import Dict, Any
from .model_server import client_mistral, mistral_llm
from docx import Document

def close_and_require_all(schema: dict) -> dict:
    def walk(node, path=""):
        if isinstance(node, dict):
            if node.get("type") == "object":
                if path.endswith("/args"):
                    node["additionalProperties"] = True
                    node["required"] = []          # rien d'obligatoire
                else:
                    node["additionalProperties"] = False
                    node["required"] = list(node.get("properties", {}).keys())
                for k, v in node.get("properties", {}).items():
                    walk(v, f"{path}/{k}")
            if node.get("type") == "array" and "items" in node:
                walk(node["items"], f"{path}/items")
    walk(schema)
    return schema

async def rewrite_rag_augmentor(doc : str, client_mistral = client_mistral) -> str:

    system_message = f"""
Tu es un assistant de restructuration pour un pipeline RAG.
Ton rôle est de réécrire un document en le segmentant en sous-parties thématiques (séparation par balise), 
tout en respectant strictement sa structure et son ordre d'origine.

Balise : <!--|||SECTION|||-->

Contraintes de sortie (obligatoires) :
- Conserve exactement l'ordre du document. Ne déplace pas, ne réorganise pas, ne fusionne pas de passages éloignés.
- Regroupe uniquement les passages consécutifs qui concernent le même sujet, dans une seule sous-partie.
- Il est interdit de créer plusieurs sous-parties successifs avec le même titre ou le même sujet.
- Chaque sous-partie doit être structurée ainsi :

### Sujet : <titre court, factuel, issu du texte>
<paragraphe(s) réécrits pour clarté, sans changer le sens>
<!--|||SECTION|||-->

- Le sous-titre et son contenu doivent toujours être dans le même bloc, avant la balise.
- Aucun autre texte hors sous-parties (pas d'intro, pas de conclusion, pas de commentaires).
- Utilise uniquement la balise fournie pour séparer les sous-parties.
- Préserve intégralement les faits : noms propres, chiffres, dates, citations, URLs, adresse, contacts, lieux.

Règles de segmentation :
- Regroupe les phrases par sujet ; fusionne les passages liés si c'est le même thème.
- Si un passage est trop court pour avoir un titre détaillé, crée quand même un sous-titre minimal fidèle (ex. "### Sujet : Brève remarque").
"""
    messages = [{"role": "system", "content": system_message}] + [{"role": "user", "content": f"Réécrit le documet suivant en suivant strictement les instructions données: \n\n{doc}\n\n"}]

    processed_doc =  await client_mistral.chat.complete_async(
        model=mistral_llm,
        messages=messages,
        temperature=0,
        top_p=1,
        stream=False
    )
    return processed_doc.choices[0].message.content
import json
from typing import Dict, Any

def close_and_require_all(schema: dict) -> dict:
    def walk(node, path=""):
        if isinstance(node, dict):
            if node.get("type") == "object":
                if path.endswith("/args"):
                    node["additionalProperties"] = True
                    node["required"] = []          # rien d’obligatoire
                else:
                    node["additionalProperties"] = False
                    node["required"] = list(node.get("properties", {}).keys())
                for k, v in node.get("properties", {}).items():
                    walk(v, f"{path}/{k}")
            if node.get("type") == "array" and "items" in node:
                walk(node["items"], f"{path}/items")
    walk(schema)
    return schema
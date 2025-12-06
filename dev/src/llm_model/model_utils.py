from typing import Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Dict, Any, Literal

############################# Class #############################

class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)

class PlannerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: Literal["answer","tool","reject","clarify","escalate"]
    tools_to_call: List[ToolCall] = Field(default_factory=list)
    continue_discussion: bool = True
    explain_stop_discussion: str = ""
    exec_required: bool = False
    exec_inst: str = ""
    user_visible_answer: str = ""

class ExecutorOutput(BaseModel):
    status: str = Field(..., description="one of: Completed|need_info|error")
    final: bool = Field(default=False)
    message: str = Field(default="")
    data: Any = Field(default=None)
    ask: str = Field(default="")
    error: str = Field(default="")

############################# Utils func #############################

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
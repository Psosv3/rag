from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import List, Optional, Dict, Any, Literal
from pathlib import Path
from tools.functions import read_instructions, handle_stream_events
from tools.for_agents import read_dir_struct, read_file_contents
from .model_server import planner_model, planner_core_model, executor_model, mcp_server
from agents import Agent, Runner, ModelSettings, AgentOutputSchema
from dotenv import load_dotenv


load_dotenv()
BASE = Path(__file__).resolve().parent.parents[2]

############################# Class #############################

class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)

class PlannerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: Literal["answer","tool","reject","clarify"]
    tools_to_call: List[ToolCall] = Field(default_factory=list)
    continue_discussion: bool = True
    citations_required: bool = False
    user_visible_answer: str = ""
    exec_required: bool = False
    exec_inst: str = ""

class ExecutorOutput(BaseModel):
    status: str = Field(..., description="one of: Completed|need_info|error")
    final: bool = Field(default=False)
    message: str = Field(default="")
    data: Any = Field(default=None)
    ask: str = Field(default="")
    error: str = Field(default="")


############################# Instructions planner & executeur #############################

planner_instructions = (
    read_instructions(BASE/"dev/src/instructions/julia.md")
    + "\n###\n"
    + read_instructions(BASE/"dev/src/instructions/planner.md")
    + "\n###\n"
    + read_instructions(BASE/"dev/src/instructions/RAG_policy.md")
    + "\n###\n"
    + read_instructions(BASE/"dev/src/instructions/Safety_policy.md")
    + "\n###\n"
    + read_instructions(BASE/"dev/src/instructions/Delegation_policy.md")
)

executor_instructions = (read_instructions(BASE/"dev/src/instructions/executor.md"))


############################# Features additionnels #############################

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

output_schema = close_and_require_all(PlannerOutput.model_json_schema())


############################# Definition des agents #############################

executor_agent = Agent(
    name="Executor Agent",
    model=executor_model,
    instructions=executor_instructions,
    mcp_servers=[mcp_server],
    tools=[read_dir_struct, read_file_contents],
    model_settings=ModelSettings(temperature=0),
)

# Planner Agent
async def julia_planner(user_message,
                        output_schema = output_schema
                        )-> PlannerOutput:
    
    chat_completion  = await planner_model.chat.completions.create(
        model=planner_core_model,
        messages=user_message,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "PlannerOutput",
                "schema": output_schema,
                "strict": True
            }
        },
        temperature=0.6,
        top_p=0.1,
        stream=False,
    )
    content = chat_completion.choices[0].message.content.strip() or "{}"

    try:
    # Valide et convertit en instance Pydantic
        return PlannerOutput.model_validate_json(content)
    except ValidationError as e:
    # En prod: logger 'content' pour diagnostic et remonter une erreur claire
        raise

# Executor Agent
async def julia_executor(exec_inst: str, mcp_server=mcp_server):
    async with mcp_server:
        result = await Runner.run(
            executor_agent,
            exec_inst
            )
        #await handle_stream_events(result)
        return result.final_output
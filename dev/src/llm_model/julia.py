from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import List, Optional, Dict, Any, Literal
from pathlib import Path
from tools.functions import read_instructions, handle_stream_events
from tools.for_agents import read_dir_struct, read_file_contents
from .model_server import planner_model, planner_core_model, executor_model, mcp_server_tool, mcp_server_escalator
from agents import Agent, Runner, AgentOutputSchema
from agents.model_settings import ModelSettings
from dotenv import load_dotenv
from .model_utils import close_and_require_all

load_dotenv()
BASE = Path(__file__).resolve().parent.parents[2]

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
    citations_required: bool = False
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


############################# Instructions planner & executeur #############################

planner_instructions = read_instructions(BASE/"dev/src/instructions/planner_instruction1.md")

executor_instructions = (read_instructions(BASE/"dev/src/instructions/executor_instruction.md"))

escalator_instructions = (read_instructions(BASE/"dev/src/instructions/escalator_instruction.md"))



############################# Features additionnels #############################

output_schema = close_and_require_all(PlannerOutput.model_json_schema())

############################# Definition des agents #############################

executor_agent = Agent(
    name="Executor Agent",
    model=executor_model,
    instructions=executor_instructions,
    mcp_servers=[mcp_server_tool],
    tools=[],
    model_settings=ModelSettings(temperature=0),
)

escalator_agent = Agent(
    name="Escalator Agent",
    model=executor_model,
    instructions=escalator_instructions,
    mcp_servers=[mcp_server_escalator],
    tools=[],
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
        temperature=0.05,
        top_p=0.95,
        seed = 127,
        stream=False,
    )
    content = chat_completion.choices[0].message.content.strip() or "{}"

    try:
        return PlannerOutput.model_validate_json(content)     # Valide et convertit en instance Pydantic
    except ValidationError :
        return PlannerOutput(
            action_type="answer",
            tools_to_call=[],
            continue_discussion=True,
            citations_required=False,
            exec_required=False,
            exec_inst="",
            user_visible_answer=None
        )

# Executor Agent
async def julia_executor(exec_inst: str, mcp_server=mcp_server_tool):
    async with mcp_server:
        result = await Runner.run(
            executor_agent,
            exec_inst
            )
        return result.final_output
    
# Escalator Agent
async def julia_escalator(exec_inst: str, mcp_server=mcp_server_escalator):
    async with mcp_server:
        result = await Runner.run(
            escalator_agent,
            exec_inst
            )
        return result.final_output
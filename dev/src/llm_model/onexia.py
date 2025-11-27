from pydantic import ValidationError
from pathlib import Path
from tools.functions import read_instructions, handle_stream_events
from tools.for_agents import json, read_file_contents
from .model_server import planner_model, planner_model_backup, planner_core_model, executor_model, mcp_server_tool, mcp_server_escalator, mcp_server_api
from agents import Agent, Runner, AgentOutputSchema
from agents.model_settings import ModelSettings
from dotenv import load_dotenv
from .model_utils import chat_completion_function, close_and_require_all, ToolCall, PlannerOutput, ExecutorOutput, fallback_completion
from .sanitizing_mcp import SanitizingMCP

load_dotenv()
BASE = Path(__file__).resolve().parent.parents[2]


############################# Instructions planner & executeur #############################

planner_syst_instructions = read_instructions(BASE/"dev/src/instructions/planner_syst_instruct.md")
planner_dev_instructions = read_instructions(BASE/"dev/src/instructions/planner_dev_instruct.md")
executor_instructions = (read_instructions(BASE/"dev/src/instructions/executor_instruct.md"))
escalator_instructions = (read_instructions(BASE/"dev/src/instructions/escalator_instruct.md"))

############################# Features additionnels #############################

output_schema = close_and_require_all(PlannerOutput.model_json_schema())

############################# Definition des agents #############################

san_tool = SanitizingMCP(mcp_server_tool)
san_api = SanitizingMCP(mcp_server_api)
executor_agent = Agent(
    name="Executor Agent",
    model=executor_model,
    instructions=executor_instructions,
    mcp_servers=[san_tool, san_api],
    tools=[json],
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
async def onexia_planner(user_message, output_schema=output_schema) -> PlannerOutput:
    try:
        content = await chat_completion_function(user_message, planner_model_backup, planner_core_model, output_schema)#(user_message, planner_model, planner_core_model, output_schema)
    except Exception as e:
        try:
            content = await chat_completion_function(user_message, planner_model_backup, planner_core_model, output_schema)
        except Exception as e:
            content = fallback_completion()
    try:
        return PlannerOutput.model_validate_json(content)     # Valide et convertit en instance Pydantic
    except ValidationError :
        return fallback_completion()
    
# Executor Agent
async def onexia_executor(exec_inst: str, mcp_server=san_tool, mcp_api=san_api):
    async with mcp_server, mcp_api:
        result = await Runner.run(
            executor_agent,
            exec_inst
            )
    return result.final_output
    
# Escalator Agent
async def onexia_escalator(exec_inst: str, mcp_server=mcp_server_escalator):
    async with mcp_server:
        result = await Runner.run(
            escalator_agent,
            exec_inst
            )
        return result.final_output
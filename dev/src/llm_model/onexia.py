from pydantic import ValidationError
from pathlib import Path
from tools.functions import read_instructions, handle_stream_events
from tools.for_agents import read_dir_struct, read_file_contents
from .model_server import planner_model, planner_model_backup, planner_core_model, executor_model, mcp_server_tool, mcp_server_escalator
from agents import Agent, Runner, AgentOutputSchema
from agents.model_settings import ModelSettings
from dotenv import load_dotenv
from .model_utils import close_and_require_all, ToolCall, PlannerOutput, ExecutorOutput

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
async def onexia_planner(user_message, output_schema=output_schema) -> PlannerOutput:
    try:
        chat_completion = await planner_model.chat.completions.create(
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
    except Exception as e:
        try:
            chat_completion  = await planner_model_backup.chat.completions.create(
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
        except Exception as e:
            content = PlannerOutput(
                action_type="answer",
                tools_to_call=[],
                continue_discussion=True,
                citations_required=False,
                exec_required=False,
                exec_inst="",
                user_visible_answer="Désolé, il semble que j'ai perdu ma connexion. Pourriez-vous répéter svp ?"
            )
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
            user_visible_answer="Désolé, il semble que j'ai perdu ma connexion. Pourriez-vous répéter svp ?"
        )
    
# Executor Agent
async def onexia_executor(exec_inst: str, mcp_server=mcp_server_tool):
    async with mcp_server:
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
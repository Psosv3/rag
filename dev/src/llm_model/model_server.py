
from agents import OpenAIChatCompletionsModel
from agents import AsyncOpenAI as AgentsAsyncOpenAI 
from groq import AsyncGroq
from openai import AsyncOpenAI
from agents.mcp  import MCPServerSse
from mistralai import Mistral
import os
from dotenv import load_dotenv

###
load_dotenv()
assert os.getenv("OPENAI_API_KEY") 
assert os.getenv("MISTRAL_API_KEY") 
assert os.getenv("GROQ_API_KEY") 
assert os.getenv("BASETEN_API_KEY") 
openai_key = os.getenv("OPENAI_API_KEY")
mistral_api_key = os.getenv("MISTRAL_API_KEY")
groq_api_key = os.getenv("GROQ_API_KEY")
baseten_api_key = os.getenv("BASETEN_API_KEY")

###
client_mistral = Mistral(api_key=mistral_api_key)
mistral_llm = "mistral-small-latest"

###
planner_model = AsyncGroq(api_key=groq_api_key)
planner_core_model = "openai/gpt-oss-120b"

planner_model_backup = AsyncOpenAI(api_key=baseten_api_key, base_url="https://inference.baseten.co/v1")

###
image_model = AsyncGroq(api_key=groq_api_key)
image_core_model = "meta-llama/llama-4-maverick-17b-128e-instruct" #"meta-llama/llama-4-scout-17b-16e-instruct"

###
executor_model = OpenAIChatCompletionsModel( 
    model = "openai/gpt-oss-20b",
    openai_client = AgentsAsyncOpenAI (base_url="https://api.groq.com/openai/v1", api_key=groq_api_key),
)

###
mcp_tool_url = "https://flow.onexus.space/api/v1/mcp/T43HNxLiNBYWvnRzpfq6y/sse"
mcp_server_tool = MCPServerSse(
    name="mcp_onexia_executor",             # this is the tool name you'll call
    params={"url": mcp_tool_url}    # the URL for the SSE endpoint
)

mcp_esc_url = "https://flow.onexus.space/api/v1/mcp/RkNbUg9DshpWj8uo4dItY/sse"
mcp_server_escalator = MCPServerSse(
    name="mcp_onexia_escalator",             # this is the tool name you'll call
    params={"url": mcp_esc_url}    # the URL for the SSE endpoint
)
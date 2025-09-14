
from agents import OpenAIChatCompletionsModel
from agents import AsyncOpenAI as AgentsAsyncOpenAI 
from groq import AsyncGroq
from agents.mcp  import MCPServerSse
from langchain_mistralai.chat_models import ChatMistralAI
import os
from dotenv import load_dotenv

###
load_dotenv()
assert os.getenv("OPENAI_API_KEY") 
assert os.getenv("MISTRAL_API_KEY") 
assert os.getenv("GROQ_API_KEY") 
openai_key = os.getenv("OPENAI_API_KEY")
mistral_api_key = os.getenv("MISTRAL_API_KEY")
groq_api_key = os.getenv("GROQ_API_KEY")

###
mistral_llm = ChatMistralAI(
    api_key=mistral_api_key,
    model="mistral-small-latest",
    temperature=0.7,
)

###
planner_model = AsyncGroq(api_key=groq_api_key)
planner_core_model = "openai/gpt-oss-20b"

###
executor_model = OpenAIChatCompletionsModel( 
    model = "openai/gpt-oss-20b",
    openai_client = AgentsAsyncOpenAI (base_url="https://api.groq.com/openai/v1", api_key=groq_api_key),
)

###
mcp_tool_url = "https://flow.onexus.space/api/v1/mcp/T43HNxLiNBYWvnRzpfq6y/sse"
mcp_server_tool = MCPServerSse(
    name="mcp_julia_executor",             # this is the tool name you'll call
    params={"url": mcp_tool_url}    # the URL for the SSE endpoint
)

mcp_esc_url = "https://flow.onexus.space/api/v1/mcp/RkNbUg9DshpWj8uo4dItY/sse"
mcp_server_escalator = MCPServerSse(
    name="mcp_julia_escalator",             # this is the tool name you'll call
    params={"url": mcp_esc_url}    # the URL for the SSE endpoint
)

from openai_agents import OpenAIChatCompletionsModel
from openai_agents import AsyncOpenAI as AgentsAsyncOpenAI 
from groq import AsyncGroq
from openai_agents.mcp import MCPServerSse
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
mcp_server_url_sse = "https://flow.onexus.space/api/v1/mcp/E0xROVAPdkFccm4RwA4Nw/sse"
mcp_server = MCPServerSse(
    name="mcp_julia",             # this is the tool name you'll call
    params={"url": mcp_server_url_sse}    # the URL for the SSE endpoint
)
# FastAPI application level api url setup and app lifecycle management

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from .mcp_client.agent import agent_router
from .api.checkin import checkin_router   # also puts app/ on sys.path for the shared `services.*` imports
from .api.nudges import nudge_router
from .mcp_client.serverconfig import multi_server_mcp_client
from .prompts.prompt_file import system_message_for_tooling_agent, system_message_for_generic_agent
from langchain.agents import create_agent
from app.services.llm_service import get_openai_llm, get_ollama_llm, get_gemini_llm, get_gemini_llm_with_tools, get_gemini_llm_with_fallbacks
from .mcp_client.graph import get_agent_graph
import traceback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

available_tools = []
llm_agent_with_tools = None
generic_llm_agent = None
llm = None              # Gemini LLM without tools (generic agent)
llm_with_tools = None   # Gemini LLM with MCP tools bound (tool agent)

@asynccontextmanager
async def lifespan(app: FastAPI): 
    """
    Application lifespan management for startup and shutdown events. 
    Start the mcp_server tools and LLM agent on application startup, and perform any necessary cleanup on shutdown.
    """
    try:
        global available_tools, llm_agent_with_tools, generic_llm_agent, llm, llm_with_tools

        # Fetch the list of available tools from the MCP server client
        available_tools = await multi_server_mcp_client.get_tools()
        logger.info(f"Loaded {len(available_tools)} MCP tools: {[tool.name for tool in available_tools]}")

        # get the LLM model
        # llm = get_openai_llm()
        # llm = get_ollama_llm()
        llm = get_gemini_llm()

        # Gemini LLM with the MCP tools bound - used by the tool agent node of the Gemini agent graph
        # llm_with_tools = get_gemini_llm_with_tools(available_tools, llm=llm)
        # Same, but falls back to GEMINI_FALLBACK_MODELS when the primary model is overloaded (503) or rate limited (429)
        llm_with_tools = get_gemini_llm_with_fallbacks(available_tools)

        # Create 2 LLM agents - one  with the available tools and other just a generic agent without tools. Both agents have different system prompts to guide their behavior.
        # (used by the previous create_agent based graph `agent_graph()` in graph.py)
        llm_agent_with_tools = create_agent(llm, available_tools, system_prompt=system_message_for_tooling_agent)
        generic_llm_agent = create_agent(llm, [], system_prompt=system_message_for_generic_agent)

        # Build the Gemini agent graph at startup so configuration errors surface immediately
        await get_agent_graph()

        # Load the XGBoost risk model in the main thread (used by /checkin/answer). A first-time numpy import
        # inside a worker thread deadlocks on Windows, so it must not happen lazily in a request.
        from services.risk_model_service import get_risk_model
        get_risk_model()

        logger.info("application_starting")

        yield
    except Exception as e:
        logger.error(f"Error during application startup: {e}")
        logger.error(traceback.format_exc())
        raise e
    finally:
        logger.info("application_shutting_down")

# ----------------------------------------------------------------------------------------

app = FastAPI(
    title="Langgraph Agent API",
    description="AI Agent with FastAPI, LangGraph, and MCP. Works for B2B and B2C scenarios.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter()
app.include_router(agent_router, prefix="/agent", tags=["agent"])
app.include_router(checkin_router, prefix="/checkin", tags=["checkin"])
app.include_router(nudge_router, prefix="/nudges", tags=["nudges"])

@app.get("/health")
async def health_check():
    return JSONResponse(
        content={
            "status": "healthy",
        }
    )

@app.get("/")
async def root():
    return {
        "message": "AI Agent API",
        "docs": "/docs",
        "version": "0.1.0",
    }

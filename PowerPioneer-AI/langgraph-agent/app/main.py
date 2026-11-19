# FastAPI application level api url setup and app lifecycle management

import asyncio
import logging
import os
import sys
import traceback
from contextlib import asynccontextmanager

# The shared services and tools are imported as top-level packages (services.*, mcp_server.*, tools.*), the same
# way the stdio MCP servers import them, so app/ must be on sys.path before anything else is imported.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from langchain.agents import create_agent  # noqa: E402

from config import settings  # noqa: E402
from .api.briefing import briefing_router  # noqa: E402
from .api.checkin import checkin_router  # noqa: E402
from .api.nudges import nudge_router  # noqa: E402
from .mcp_client.agent import agent_router  # noqa: E402
from .mcp_client.graph import get_agent_graph  # noqa: E402
from .prompts.prompt_file import system_message_for_generic_agent, system_message_for_tooling_agent  # noqa: E402
from app.services.llm_service import get_gemini_llm, get_gemini_llm_with_fallbacks  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

available_tools = []
approval_required_tools: frozenset[str] = frozenset()
llm_agent_with_tools = None
generic_llm_agent = None
llm = None              # Gemini LLM without tools (generic agent)
llm_with_tools = None   # Gemini LLM with the ShiftGuard tools bound (tool agent)


async def _load_tools() -> list:
    """In-process tools (default, fast) or the stdio MCP servers (AGENT_TOOL_MODE=mcp)."""
    if settings.AGENT_TOOL_MODE.strip().lower() == "mcp":
        from .mcp_client.serverconfig import multi_server_mcp_client
        tools = await multi_server_mcp_client.get_tools()
        logger.info("Loaded %d MCP tools (stdio): %s", len(tools), [t.name for t in tools])
        return tools
    from tools.registry import get_inprocess_tools
    tools = get_inprocess_tools()     # main thread: loads numpy/xgboost here (a worker-thread first import deadlocks on Windows)
    logger.info("Loaded %d in-process tools: %s", len(tools), [t.name for t in tools])
    return tools


async def _daily_briefings():
    """Background loop: build every manager's briefing at BRIEFING_HOUR_UTC each day."""
    from services.briefing_service import run_all_briefings, seconds_until

    while True:
        delay = seconds_until(settings.BRIEFING_HOUR_UTC)
        logger.info("Next daily briefing run in %.0f minutes", delay / 60)
        await asyncio.sleep(delay)
        try:
            await asyncio.to_thread(run_all_briefings, True)
        except Exception:
            logger.exception("Daily briefing run failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan management for startup and shutdown events.
    Load the tools and LLM agent on application startup, and perform any necessary cleanup on shutdown.
    """
    briefing_task = None
    try:
        global available_tools, approval_required_tools, llm_agent_with_tools, generic_llm_agent, llm, llm_with_tools

        # Load the XGBoost risk model in the main thread first (used by /checkin/answer and the risk tools).
        from services.risk_model_service import get_risk_model
        get_risk_model()

        available_tools = await _load_tools()
        from tools.registry import APPROVAL_REQUIRED
        approval_required_tools = APPROVAL_REQUIRED

        llm = get_gemini_llm()
        # Falls back to GEMINI_FALLBACK_MODELS when the primary model is overloaded (503) or rate limited (429)
        llm_with_tools = get_gemini_llm_with_fallbacks(available_tools)

        # Legacy create_agent based agents (used by the previous `agent_graph()` in graph.py)
        llm_agent_with_tools = create_agent(llm, available_tools, system_prompt=system_message_for_tooling_agent)
        generic_llm_agent = create_agent(llm, [], system_prompt=system_message_for_generic_agent)

        # Build the agent graph at startup so configuration errors surface immediately
        await get_agent_graph()

        if settings.BRIEFING_ENABLED:
            briefing_task = asyncio.create_task(_daily_briefings())

        logger.info("application_starting")
        yield
    except Exception as e:
        logger.error(f"Error during application startup: {e}")
        logger.error(traceback.format_exc())
        raise e
    finally:
        if briefing_task:
            briefing_task.cancel()
        logger.info("application_shutting_down")

# ----------------------------------------------------------------------------------------

app = FastAPI(
    title="ShiftGuard Agent API",
    description="ShiftGuard wellbeing agent: check-ins, nudges, manager copilot (LangGraph + Gemini) and briefings.",
    version="0.2.0",
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
app.include_router(briefing_router, prefix="/briefing", tags=["briefing"])


@app.get("/health")
async def health_check():
    return JSONResponse(
        content={
            "status": "healthy",
            "tools": len(available_tools),
            "tool_mode": settings.AGENT_TOOL_MODE,
        }
    )


@app.get("/")
async def root():
    return {
        "message": "AI Agent API",
        "docs": "/docs",
        "version": "0.2.0",
    }

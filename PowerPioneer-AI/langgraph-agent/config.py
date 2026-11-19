from pathlib import Path
from pydantic_settings import BaseSettings

# Absolute path so the .env is found no matter which directory uvicorn / the MCP servers are started from
ENV_FILE = Path(__file__).resolve().parent / ".env"

class Settings(BaseSettings):
    """
    Application Settings. These settings will be loaded from environment variables or a .env file.
    In the server it will be loaded from environment variables, and in development it will be loaded from a .env file.
    """

    # Azure OpenAI (optional - only needed when get_openai_llm() is used)
    OPENAI_API_KEY: str | None = None
    AZURE_OPENAI_ENDPOINT: str | None = None
    AZURE_OPENAI_API_VERSION: str | None = None
    AZURE_OPENAI_DEPLOYMENT: str | None = None
    AZURE_OPENAI_MODEL: str | None = None

    # Azure AI Search (optional - only needed by the fetch_azure_ai_search_documents MCP tool)
    AZURE_SEARCH_SERVICE_NAME: str | None = None
    AZURE_SEARCH_API_KEY: str | None = None
    AZURE_SEARCH_SEMANTIC_CONFIGURATION: str | None = None

    # MySQL (optional - only needed when the MySQL DBConnectionManager is used)
    DB_SERVER_NAME: str | None = None
    DB_NAME: str | None = None
    DB_USERNAME: str | None = None
    DB_PASSKEY: str | None = None

    # Ollama (optional - only needed when get_ollama_llm() is used)
    OLLAMA_MODEL: str | None = None
    OLLAMA_BASE_URL: str | None = None
    OLLAMA_SUPPORTS_TOOLS: bool = True

    # Google Gemini (required - LLM used by the application)
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_TEMPERATURE: float | None = None  # None -> model default
    GEMINI_MAX_OUTPUT_TOKENS: int | None = 2048
    # Tried in order when GEMINI_MODEL returns 503 (overloaded) or 429 (rate limited). Empty disables fallback.
    GEMINI_FALLBACK_MODELS: str = "gemini-3.7-flash,gemini-3.5-flash,gemini-2.5-flash"

    # Supabase Postgres (used by SupabaseDBConnectionManager).
    # Set SUPABASE_DB_URL (postgresql://... connection string) OR the individual fields.
    SUPABASE_DB_URL: str | None = None
    SUPABASE_DB_HOST: str | None = None
    SUPABASE_DB_PORT: int = 5432
    SUPABASE_DB_NAME: str = "postgres"
    SUPABASE_DB_USER: str | None = None
    SUPABASE_DB_PASSWORD: str | None = None
    SUPABASE_DB_SSLMODE: str = "require"

    # SMTP (used by the send_notification_email MCP tool)
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM_EMAIL: str | None = None
    SMTP_USE_TLS: bool = True    # STARTTLS (port 587)
    SMTP_USE_SSL: bool = False   # implicit TLS (port 465); overrides SMTP_USE_TLS
    SMTP_TIMEOUT: int = 20

    # ShiftGuard risk model (used by the risk MCP tools)
    RISK_MODEL_ARTIFACT_DIR: str | None = None   # None -> PowerPioneer-AI/model_artifacts
    # Skip a duplicate intervention of the same type within N days. 0 = OFF: every answer triggers its actions
    # and emails (demo setting). Set INTERVENTION_DEDUP_DAYS=7 in .env after the demo to avoid repeat alerts.
    INTERVENTION_DEDUP_DAYS: int = 0
    CHECKIN_QUESTION_EXPIRY_HOURS: int = 24      # default lifetime of an agent-generated check-in question

    # Check-in APIs (/checkin/*) called by PowerPioneer-Frontend
    BACKEND_API_BASE_URL: str = "http://127.0.0.1:8000/api"   # Django API, used to verify the caller's login token
    AGENT_REQUIRE_AUTH: bool = True   # False lets Swagger/curl pass employee_id without a token (local testing only)

    # How the chat agent runs its tools: "inprocess" (default, fast: the tool functions are called directly in this
    # process) or "mcp" (each call goes through the stdio MCP servers in app/mcp_server; ~10 s per call).
    AGENT_TOOL_MODE: str = "inprocess"

    # Shared secret for agent -> Django calls (POST /api/internal/notify/ pushes a bell notification over WebSocket).
    # Must match AGENT_INTERNAL_KEY in PowerPioneer-Backend-Core/.env. The default only suits local demos.
    AGENT_INTERNAL_KEY: str = "shiftguard-local-agent-key"

    # Daily manager briefing. BRIEFING_ENABLED runs it automatically every day at BRIEFING_HOUR_UTC; it can always be
    # run on demand with POST /briefing/run. BRIEFING_SEND_EMAIL also emails each manager their briefing.
    BRIEFING_ENABLED: bool = False
    BRIEFING_HOUR_UTC: int = 6
    BRIEFING_SEND_EMAIL: bool = False


    class Config:
        env_file = ENV_FILE

settings = Settings()

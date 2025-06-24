import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from typing import Optional, List
from loguru import logger
import sys

# Определяем базовый путь к проекту API для корректной загрузки .env.apicenter
# Это важно, если Settings() вызывается из разных мест
API_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_FILE_PATH = os.path.join(API_PROJECT_ROOT, ".env.apicenter")

class Settings(BaseSettings):
    PROJECT_NAME_API: str = "AI Core API Service"
    API_VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"

    LOG_LEVEL: str = "INFO"

    # MongoDB
    MONGO_CONNECTION_STRING: str = "mongodb://mongo_user:mongo_pass@mongodb:27017/?authSource=admin&directConnection=true"
    MONGO_DATABASE_NAME: str = "ai_agent_mvp_db"
    MONGO_DIALOG_HISTORY_COLLECTION: str = "dialog_history_mvp"

    # LangChain & LLM
    OPENROUTER_API_KEY: Optional[str] = "YOUR_OPENROUTER_KEY_HERE" # Ключ для OpenRouter (может быть None, если не используется)
    GOOGLE_GEMINI_API_KEY: Optional[str] = None # Ключ для Google Gemini (может быть None, если не используется)

    DEFAULT_LLM_PROVIDER: str = "openrouter" # Провайдер LLM по умолчанию для MVP/fallback ("openrouter", "gemini", "openai")
    DEFAULT_LLM_MODEL: str = "deepseek/deepseek-chat" # Модель LLM по умолчанию (должна соответствовать DEFAULT_LLM_PROVIDER)
    
    # LangSmith (опционально, но рекомендуется)
    LANGCHAIN_API_KEY: Optional[str] = None
    LANGCHAIN_TRACING_V2: str = "true" # "true" to enable
    LANGCHAIN_ENDPOINT: Optional[str] = "https://api.smith.langchain.com"
    LANGCHAIN_PROJECT: Optional[str] = "MVP_AI_Agent_Core_Default"

    # I18n
    I18N_PATH_API: str = os.path.join(API_PROJECT_ROOT, "app", "core", "locales") # Динамический путь
    DEFAULT_LANG_API: str = "ru"

    # MVP Client Config (временное решение, лучше грузить из БД или YAML)
    MVP_CLIENT_ID: str = "default_mvp_client"
    MVP_CLIENT_NAME: str = "Default MVP Client"
    MVP_CLIENT_PERSONA: str = "полезный ассистент"
    MVP_CLIENT_TONE: str = "нейтральный"
    MVP_BUSINESS_TYPE: str = "general"

    # API Server (для uvicorn/gunicorn, если не заданы в CMD Dockerfile)
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000 # Этот порт слушает Uvicorn ВНУТРИ контейнера
    
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 100 # Увеличил немного для более полных ответов
    HISTORY_MAX_MESSAGES: int = 10

    # Admin User (for basic auth on admin endpoints)
    # These should ideally be set via environment variables, especially in production
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "supersecretadminpassword" # CHANGE THIS IN PRODUCTION!
    ADMIN_APP_SECRET_KEY: str = "a_very_strong_random_secret_for_admin_sessions_please_change_me" # CHANGE THIS IN PRODUCTION!

    class Config:
        env_file = ENV_FILE_PATH
        env_file_encoding = 'utf-8'
        extra = "ignore"

# Попытка загрузить .env.apicenter, если он существует на уровне ai_core_api_service/
# Это в основном для локальной разработки вне Docker. В Docker переменные придут из docker-compose.
if os.path.exists(ENV_FILE_PATH):
    logger.info(f"Attempting to load environment variables from: {ENV_FILE_PATH}")
    load_dotenv(dotenv_path=ENV_FILE_PATH, override=True) # override=True чтобы переменные из файла имели приоритет
else:
    logger.info(f"No .env.apicenter file found at {ENV_FILE_PATH}, relying on OS environment variables set by Docker Compose or system.")

settings = Settings()

def setup_logging_api():
    logger.remove() 
    logger.add(
        sys.stderr, 
        level=settings.LOG_LEVEL.upper(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True 
    )
    # logger.info(f"API Service logging configured. Level: {settings.LOG_LEVEL.upper()}") # Вызовется в lifespan

# Now loads from DB if client_id is provided, otherwise uses MVP defaults.
async def load_client_config(client_id: Optional[str], request_lang: Optional[str]) -> dict:
    """
    Loads client-specific configuration from the database if client_id is provided.
    Falls back to MVP default settings if client_id is None, client not found, or client is inactive.
    Prioritizes request_lang for the 'default_lang' field if provided.
    """
    # Import here to avoid circular dependencies at module load time
    # and ensure Beanie models are initialized.
    from app.models.client_models import ClientConfiguration

    # Prepare MVP default config first
    # This will be used as a fallback or base.
    default_llm_provider = settings.DEFAULT_LLM_PROVIDER
    default_api_key = None
    if default_llm_provider == "openrouter":
        default_api_key = settings.OPENROUTER_API_KEY
    elif default_llm_provider == "gemini":
        default_api_key = settings.GOOGLE_GEMINI_API_KEY
    # Add other providers here if needed for MVP default

    mvp_config = {
        "client_id": settings.MVP_CLIENT_ID, # Default client_id for MVP
        "name": settings.MVP_CLIENT_NAME,
        "persona": settings.MVP_CLIENT_PERSONA,
        "tone": settings.MVP_CLIENT_TONE,
        "business_type": settings.MVP_BUSINESS_TYPE,
        "default_lang": request_lang or settings.DEFAULT_LANG_API,
        "history_max_messages": settings.HISTORY_MAX_MESSAGES,

        "llm_config_provider": default_llm_provider,
        "llm_model": settings.DEFAULT_LLM_MODEL, # Ensure this model is compatible with default_llm_provider
        "llm_config_api_key": default_api_key,
        "llm_config_temperature": settings.LLM_TEMPERATURE,
        "llm_config_max_tokens": settings.LLM_MAX_TOKENS,
        "llm_config_custom_prompt_prefix": None, # No custom prefix for MVP default
    }

    if not client_id:
        logger.warning(f"No client_id provided, using MVP default configuration with provider: {default_llm_provider}.")
        return mvp_config # mvp_config already has MVP_CLIENT_ID set as its "client_id"

    try:
        client_doc = await ClientConfiguration.find_one(
            ClientConfiguration.client_id == client_id,
            ClientConfiguration.is_active == True
        )

        if client_doc:
            logger.info(f"Loaded configuration for client_id: {client_id}")
            # Construct the config dictionary from the Beanie document
            # Ensure all expected keys by LLMProcessor are present.

            # Prioritize request_lang if provided by user, else use client's default_lang
            effective_lang = request_lang or client_doc.default_lang

            loaded_config = {
                "client_id": client_doc.client_id,
                "name": client_doc.client_name,
                "persona": client_doc.persona,
                "tone": client_doc.tone,
                "business_type": client_doc.business_type,
                "default_lang": effective_lang,
                "history_max_messages": client_doc.history_max_messages,

                # LLM Config fields - directly from client_doc.llm_config Pydantic model
                "llm_model": client_doc.llm_config.model_name,
                "llm_config_provider": client_doc.llm_config.provider,
                "llm_config_api_key": client_doc.llm_config.api_key, # This will be used by LLMProcessor
                "llm_config_temperature": client_doc.llm_config.temperature,
                "llm_config_max_tokens": client_doc.llm_config.max_tokens,
                "llm_config_custom_prompt_prefix": client_doc.llm_config.custom_prompt_prefix,
            }
            return loaded_config
        else:
            logger.warning(f"Client configuration not found or inactive for client_id: {client_id}. Using MVP default configuration.")
            # Ensure client_id in the returned config reflects the one being used (MVP's)
            mvp_config["client_id"] = settings.MVP_CLIENT_ID # Fallback to MVP client_id
            if client_id: # If a specific client_id was requested but not found/inactive
                mvp_config["original_request_client_id"] = client_id # Keep track of what was asked
            return mvp_config

    except Exception as e:
        logger.error(f"Error loading client configuration for client_id '{client_id}': {e}. Using MVP default configuration.", exc_info=True)
        # Ensure client_id in the returned config reflects the one being used (MVP's)
        mvp_config["client_id"] = settings.MVP_CLIENT_ID
        if client_id:
             mvp_config["original_request_client_id"] = client_id
        return mvp_config

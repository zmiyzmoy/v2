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
    MONGO_CLIENTS_COLLECTION: str = "clients"
    MONGO_PROMPTS_COLLECTION: str = "prompts"
    MONGO_USERS_COLLECTION: str = "users"
    MONGO_APPOINTMENTS_COLLECTION: str = "appointments"

    # Default Fallback Values
    DEFAULT_FALLBACK_CLIENT_ID: str = "system_default_client"
    DEFAULT_FALLBACK_BUSINESS_TYPE: str = "general_default"

    # LangChain & LLM
    OPENROUTER_API_KEY: str = "YOUR_OPENROUTER_KEY_HERE" # Будет переопределено из env
    DEFAULT_LLM_MODEL: str = "deepseek/deepseek-chat"
    
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

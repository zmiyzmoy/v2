from fastapi import FastAPI, HTTPException
from loguru import logger
from contextlib import asynccontextmanager # Для lifespan в FastAPI

# Импортируем все необходимые компоненты
from app.api.endpoints import router as api_router
from app.core.config import settings, setup_logging_api
from app.core.db import connect_to_mongo, close_mongo_connection, get_database
from app.core.i18n import I18nLoader

# Контекстный менеджер для событий startup и shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Код, выполняемый при старте приложения
    setup_logging_api() # Настройка логирования Loguru
    logger.info(f"Starting {settings.PROJECT_NAME_API} v{settings.API_VERSION}...")
    
    await connect_to_mongo() # Подключение к MongoDB
    
    # Инициализация I18nLoader и сохранение в состояние приложения
    # чтобы он был доступен через request.app.state.i18n_loader в эндпоинтах
    app.state.i18n_loader = I18nLoader(
        locales_path=settings.I18N_PATH_API, 
        default_lang=settings.DEFAULT_LANG_API
    )
    logger.info(f"Global I18nLoader initialized with default lang: {settings.DEFAULT_LANG_API} from path: {settings.I18N_PATH_API}")

    # Проверка и логирование статуса LangSmith
    if settings.LANGCHAIN_TRACING_V2 == "true" and settings.LANGCHAIN_API_KEY and settings.LANGCHAIN_PROJECT:
        logger.info(f"LangSmith tracing is ENABLED for project: {settings.LANGCHAIN_PROJECT}")
    else:
        logger.warning("LangSmith tracing is DISABLED or API key/project not provided in settings.")
    
    yield # Точка, где приложение готово принимать запросы

    # Код, выполняемый при остановке приложения
    logger.info(f"Shutting down {settings.PROJECT_NAME_API}...")
    await close_mongo_connection()
    logger.info(f"{settings.PROJECT_NAME_API} has been shut down.")

# Создание экземпляра FastAPI с использованием lifespan
app = FastAPI(
    title=settings.PROJECT_NAME_API,
    version=settings.API_VERSION,
    lifespan=lifespan 
)

# Подключение роутера с API эндпоинтами
app.include_router(api_router, prefix=settings.API_V1_STR)

# Эндпоинт для проверки состояния
@app.get("/health", summary="Check Application Health", tags=["Health"])
async def health_check():
    db = get_database() # Получаем инстанс БД
    db_status = "not_connected"
    if db is not None:
        try:
            await db.command("ping") # Проверяем пинг к БД
            db_status = "ok"
        except Exception as e:
            db_status = f"error: {str(e)}"
            logger.error(f"Health check - DB ping failed: {e}")
    else:
        logger.warning("Health check - get_database() returned None.")    
    
    return {
        "application_name": settings.PROJECT_NAME_API,
        "application_version": settings.API_VERSION,
        "status": "healthy", # Общий статус приложения
        "dependencies_status": {
            "mongodb_connection": db_status,
            "langsmith_tracing_enabled": settings.LANGCHAIN_TRACING_V2 == "true"
        }
    }

# Это для локального запуска без Uvicorn CLI, обычно не используется при запуске в Docker
# if __name__ == "__main__":
#     import uvicorn
#     # Логирование будет настроено через lifespan
#     uvicorn.run("app.main:app", host=settings.API_HOST, port=settings.API_PORT, reload=True)

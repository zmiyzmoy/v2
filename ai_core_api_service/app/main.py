from fastapi import FastAPI, HTTPException
from loguru import logger
from contextlib import asynccontextmanager # Для lifespan в FastAPI

# Импортируем все необходимые компоненты
from app.api.endpoints import router as api_router
from app.api.admin_endpoints import router as admin_api_router # ADDED: Admin router
from app.core.config import settings, setup_logging_api
from app.core.db import connect_to_mongo, close_mongo_connection, get_database, get_mongo_client
from app.core.i18n import I18nLoader
from beanie import init_beanie
from app.models.client_models import ClientConfiguration
# For FastAPI Admin
from fastapi_admin.app import app as fastapi_admin_app
from fastapi_admin.resources import Model as ModelResource
from fastapi_admin.widgets import displays # inputs might not be needed for basic display
from fastapi_admin.engine import Engine
from motor.motor_asyncio import AsyncIOMotorClient # Needed for Admin engine
from app.core.security import verify_admin_credentials # For protecting the admin mount
from fastapi import Depends


# Контекстный менеджер для событий startup и shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Код, выполняемый при старте приложения
    setup_logging_api() # Настройка логирования Loguru
    logger.info(f"Starting {settings.PROJECT_NAME_API} v{settings.API_VERSION}...")
    
    await connect_to_mongo() # Подключение к MongoDB
    
    # Initialize Beanie ODM
    mongo_client = get_mongo_client() # Get the connected Motor client
    if mongo_client:
        db_instance_for_beanie = get_database() # Get the Motor database instance
        if db_instance_for_beanie:
            await init_beanie(
                database=db_instance_for_beanie,
                document_models=[ClientConfiguration] # Register your Beanie documents here
            )
            logger.info("Beanie ODM initialized successfully.")
        else:
            logger.critical("Failed to get database instance for Beanie initialization.")
            # Potentially raise an error here to stop app startup if Beanie is critical
    else:
        logger.critical("Failed to get MongoDB client for Beanie initialization.")
        # Potentially raise an error here

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
app.include_router(api_router, prefix=settings.API_V1_STR, tags=["AI Core"])
app.include_router(admin_api_router, prefix="/admin-api", tags=["Admin API: Client Management"]) # Renamed prefix to /admin-api

# Initialize FastAPI Admin
# This engine is what FastAPI Admin uses to interact with the database.
# It needs the Motor client instance.
# We get the client instance after `connect_to_mongo()` has run.
# However, admin_app is typically configured at the global scope.
# This is a common challenge with tools that need DB access during global setup.

# Option 1: Initialize admin_app within lifespan (might be complex for fastapi-admin's design)
# Option 2: Initialize admin_app globally but ensure its resources are loaded after DB connection.
# FastAPI Admin's `Admin` class takes the FastAPI `app` instance to mount itself.

# Let's configure FastAPI Admin resources first
@fastapi_admin_app.register
class ClientConfigurationAdmin(ModelResource):
    resource = ClientConfiguration # Your Beanie model
    fields = [
        "client_id",
        "client_name",
        "is_active",
        "persona",
        "tone",
        "business_type",
        "default_lang",
        displays.JSON("llm_config", "LLM Config"), # Display JSON for llm_config
        "history_max_messages",
        "created_at",
        "updated_at",
    ]
    # To make llm_config editable as a JSON string in the admin:
    # (This is basic; a more complex form would require custom widget development)
    # inputs = [
    #     inputs.Json("llm_config", "LLM Config"),
    # ]
    # For now, direct editing of llm_config might be best done via the /admin-api PUT endpoint
    # or by making individual llm_config fields editable if FastAPI Admin supports nested Pydantic models easily.
    # Let's keep it simple: display as JSON, edit via API or by editing top-level fields if broken out.

# The `fastapi_admin_app` (which is the Admin class instance from fastapi-admin)
# needs to be initialized with the main FastAPI `app` instance and the engine.
# This is typically done by calling `admin_app.init(app, engine)`
# This needs to happen after the main `app` is created.

# Deferring full Admin init until `engine` is available.
# The mounting of `admin_app` must happen after `engine` is set up in `lifespan`.

async def init_admin_app(fastapi_app_instance: FastAPI, motor_client: AsyncIOMotorClient):
    engine = Engine(motor_client=motor_client, database_name=settings.MONGO_DATABASE_NAME)
    # The secret key is crucial for session management in FastAPI Admin
    # It should be a strong, random string, ideally from your application settings.
    await fastapi_admin_app.configure(
        app=fastapi_app_instance, # Mounts admin panel to the main app
        engine=engine,
        secret_key=settings.ADMIN_APP_SECRET_KEY, # Use the key from settings
        # admin_path="/admin-panel" # This is set when mounting if not using configure's app param
        # authentication_provider=... # If using fastapi-admin's own auth system
        # For Basic Auth on the mount, we don't use authentication_provider here.
    )
    # Mount the admin app with dependency-based authentication
    # Ensure this path is distinct from your other /admin paths.
    fastapi_app_instance.mount(
        "/admin-panel",
        fastapi_admin_app,
        dependencies=[Depends(verify_admin_credentials)],
        name="fastapi_admin"
    )
    logger.info(f"FastAPI Admin panel mounted at /admin-panel and configured.")


# Modify lifespan to initialize admin_app and Redis
import redis.asyncio as redis # MODIFIED: Changed from aioredis to redis.asyncio

@asynccontextmanager
async def lifespan(app_param: FastAPI): # Renamed app to app_param to avoid conflict
    # Код, выполняемый при старте приложения
    setup_logging_api() # Настройка логирования Loguru
    logger.info(f"Starting {settings.PROJECT_NAME_API} v{settings.API_VERSION}...")

    # Initialize Redis
    redis_url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB_ADMIN}"
    if settings.REDIS_PASSWORD: # Construct URL with password if provided
        redis_url = f"redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB_ADMIN}"

    try:
        # Use redis.asyncio.Redis.from_url
        app_param.state.redis = redis.Redis.from_url(redis_url, encoding="utf8", decode_responses=True)
        # Test connection
        await app_param.state.redis.ping()
        logger.info(f"Successfully connected to Redis at {settings.REDIS_HOST}:{settings.REDIS_PORT}, DB: {settings.REDIS_DB_ADMIN}")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}", exc_info=True)
        app_param.state.redis = None
        # Consider if app should fail to start if Redis connection is critical

    await connect_to_mongo() # Подключение к MongoDB

    mongo_client = get_mongo_client()
    db_instance_for_beanie = get_database()

    if mongo_client and db_instance_for_beanie:
        await init_beanie(
            database=db_instance_for_beanie,
            document_models=[ClientConfiguration]
        )
        logger.info("Beanie ODM initialized successfully.")

        # Initialize FastAPI Admin here, as mongo_client is now available
        # Pass redis client to fastapi_admin_app if it supports it directly,
        # or ensure SessionMiddleware is configured to use it if that's the mechanism.
        # For fastapi-admin 1.0.4, it primarily uses Starlette's SessionMiddleware.
        # If we want Redis-backed sessions, we'd replace/configure that middleware.
        # For now, just making redis available in app.state for potential use.
        # The `secret_key` in `fastapi_admin_app.configure` enables cookie-based sessions by default.
        # If `fastapi-admin` has specific Redis integration for cache/sessions beyond Starlette's SessionMiddleware,
        # its documentation for v1.0.4 would need to be consulted for the exact parameters in .configure()

        # The existing init_admin_app does not explicitly take a redis client for fastapi-admin 1.0.4's structure.
        # It relies on the SessionMiddleware configured by secret_key.
        # If Redis is strictly for fastapi-admin's internal cache (not sessions), it might look for app.state.redis.
        await init_admin_app(app_param, mongo_client)
    else:
        logger.critical("Failed to get MongoDB client or database for Beanie/Admin initialization.")

    app_param.state.i18n_loader = I18nLoader(
        locales_path=settings.I18N_PATH_API,
        default_lang=settings.DEFAULT_LANG_API
    )
    logger.info(f"Global I18nLoader initialized with default lang: {settings.DEFAULT_LANG_API} from path: {settings.I18N_PATH_API}")

    if settings.LANGCHAIN_TRACING_V2 == "true" and settings.LANGCHAIN_API_KEY and settings.LANGCHAIN_PROJECT:
        logger.info(f"LangSmith tracing is ENABLED for project: {settings.LANGCHAIN_PROJECT}")
    else:
        logger.warning("LangSmith tracing is DISABLED or API key/project not provided in settings.")

    yield

    logger.info(f"Shutting down {settings.PROJECT_NAME_API}...")
    if hasattr(app_param.state, 'redis') and app_param.state.redis:
        await app_param.state.redis.close()
        logger.info("Redis connection closed.")
    await close_mongo_connection()
    logger.info(f"{settings.PROJECT_NAME_API} has been shut down.")

# Create main FastAPI app instance
app = FastAPI(
    title=settings.PROJECT_NAME_API,
    version=settings.API_VERSION,
    lifespan=lifespan
)
# Routers and admin app are included/mounted inside the lifespan (init_admin_app) or globally for API routers

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

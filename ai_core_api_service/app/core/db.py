from motor.motor_asyncio import AsyncIOMotorClient
from loguru import logger
from app.core.config import settings # Импортируем наш объект settings
from typing import Optional, Any
from datetime import datetime, timezone

mongo_client_instance: Optional[AsyncIOMotorClient] = None
mongo_database_instance: Optional[Any] = None # MongoDB Database object from Motor

async def connect_to_mongo():
    global mongo_client_instance, mongo_database_instance
    if mongo_client_instance is not None and mongo_database_instance is not None:
        try:
            await mongo_client_instance.admin.command('ping')
            logger.debug("MongoDB connection already active and verified.")
            return
        except Exception:
            logger.warning("MongoDB connection lost or stale, attempting to reconnect.")
            mongo_client_instance = None
            mongo_database_instance = None

    logger.info(f"Connecting to MongoDB: {settings.MONGO_CONNECTION_STRING} (DB: {settings.MONGO_DATABASE_NAME})")
    try:
        mongo_client_instance = AsyncIOMotorClient(
            settings.MONGO_CONNECTION_STRING,
            serverSelectionTimeoutMS=5000, # Таймаут для выбора сервера
            uuidRepresentation='standard' # Рекомендуется для Motor
        )
        await mongo_client_instance.admin.command('ping') # Проверка соединения
        mongo_database_instance = mongo_client_instance[settings.MONGO_DATABASE_NAME]
        logger.success(f"Successfully connected to MongoDB, database: '{settings.MONGO_DATABASE_NAME}'.")
        await create_indexes(mongo_database_instance) # Создаем индексы при подключении
    except Exception as e:
        logger.critical(f"Failed to connect to MongoDB: {e}", exc_info=True)
        mongo_client_instance = None
        mongo_database_instance = None
        # В реальном приложении можно добавить логику retry или graceful shutdown

async def close_mongo_connection():
    global mongo_client_instance, mongo_database_instance
    if mongo_client_instance is not None:
        logger.info("Closing MongoDB connection.")
        mongo_client_instance.close()
        mongo_client_instance = None
        mongo_database_instance = None

def get_database() -> Optional[Any]: # Возвращает объект базы данных Motor
    if mongo_database_instance is None:
        logger.error("MongoDB instance (database) is not available. Connection might have failed or not been initialized.")
    return mongo_database_instance

def get_mongo_client() -> Optional[AsyncIOMotorClient]: # Returns the Motor client instance
    if mongo_client_instance is None:
        logger.error("MongoDB client instance is not available. Connection might have failed or not been initialized.")
    return mongo_client_instance

async def create_indexes(db: Any): # Accepts a Motor database object
    """Создает необходимые индексы, если они еще не существуют."""
    if db is None:
        logger.error("Cannot create indexes, database instance is None.")
        return

    logger.info("Checking and creating MongoDB indexes...")
    try:
        collection_name = settings.MONGO_DIALOG_HISTORY_COLLECTION
        await db[collection_name].create_index(
            [("client_id", 1), ("user_id", 1), ("timestamp", -1)],
            name="idx_history_client_user_time"
        )
        await db[collection_name].create_index(
            [("session_id_n8n", 1)],
            name="idx_history_n8n_session",
            sparse=True
        )
        logger.success(f"Indexes checked/created for collection '{collection_name}'.")
    except Exception as e:
        logger.error(f"Error creating indexes for '{collection_name}': {e}", exc_info=True)

async def save_dialog_entry(db: Any, entry_data: dict):
    """Сохраняет одну запись диалога в указанную коллекцию."""
    if db is None:
        logger.error("Cannot save dialog entry, database instance is None.")
        return None
    try:
        collection_name = settings.MONGO_DIALOG_HISTORY_COLLECTION
        result = await db[collection_name].insert_one(entry_data)
        logger.debug(f"Dialog entry saved with id: {result.inserted_id}")
        return result.inserted_id
    except Exception as e:
        logger.error(f"Error saving dialog entry: {e}", exc_info=True)
        return None

async def get_dialog_history(db: Any, client_id: str, user_id: str, limit: int) -> list:
    """Получает последние 'limit' сообщений для данного клиента и пользователя."""
    if db is None:
        logger.error("Cannot get dialog history, database instance is None.")
        return []
    try:
        collection_name = settings.MONGO_DIALOG_HISTORY_COLLECTION
        history_cursor = db[collection_name].find(
            {"client_id": client_id, "user_id": user_id}
        ).sort("timestamp", -1).limit(limit)

        history_docs = await history_cursor.to_list(length=limit)
        return history_docs[::-1]
    except Exception as e:
        logger.error(f"Error fetching dialog history for client '{client_id}', user '{user_id}': {e}", exc_info=True)
        return []

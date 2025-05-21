import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from loguru import logger
from .config import settings

async def init_mongodb():
    """Initialize MongoDB with default data if collections are empty."""
    try:
        # Подключаемся к MongoDB
        client = AsyncIOMotorClient(settings.MONGO_CONNECTION_STRING)
        db = client[settings.MONGO_DATABASE_NAME]

        # Проверяем и создаем дефолтного клиента
        default_client = await db[settings.MONGO_CLIENTS_COLLECTION].find_one(
            {"client_id": settings.DEFAULT_FALLBACK_CLIENT_ID}
        )
        
        if not default_client:
            logger.info("Creating default client configuration...")
            await db[settings.MONGO_CLIENTS_COLLECTION].insert_one({
                "client_id": settings.DEFAULT_FALLBACK_CLIENT_ID,
                "name": "Стандартный Ассистент",
                "business_type": settings.DEFAULT_FALLBACK_BUSINESS_TYPE,
                "persona": "универсальный помощник",
                "tone": "нейтральный и вежливый",
                "default_lang": "ru",
                "history_max_messages": 10
            })
            logger.info("Default client configuration created.")

        # Проверяем и создаем дефолтный промпт
        default_prompt = await db[settings.MONGO_PROMPTS_COLLECTION].find_one(
            {"business_type": settings.DEFAULT_FALLBACK_BUSINESS_TYPE}
        )
        
        if not default_prompt:
            logger.info("Creating default prompt...")
            await db[settings.MONGO_PROMPTS_COLLECTION].insert_one({
                "business_type": settings.DEFAULT_FALLBACK_BUSINESS_TYPE,
                "prompt": """Ты - {persona} для сервиса "{name}". 
                Твоя задача - вежливо ответить на запрос пользователя.
                Пожалуйста, отвечай на языке: {language_fallback}.
                Твой ответ ДОЛЖЕН БЫТЬ в формате JSON объекта со следующими обязательными ключами:
                "response_text": (string) Твой естественный ответ пользователю.
                "language_detected": (string) ISO 639-1 код определенного тобой языка пользователя.
                "intent": (string|null) "general_query".
                "entities": (object|null) null.
                "actions_for_n8n": (array) [].
                Убедись, что JSON валиден."""
            })
            logger.info("Default prompt created.")

        logger.info("MongoDB initialization completed successfully.")
        
    except Exception as e:
        logger.error(f"Error during MongoDB initialization: {e}", exc_info=True)
        raise
    finally:
        client.close()

if __name__ == "__main__":
    asyncio.run(init_mongodb()) 
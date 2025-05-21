import traceback # <--- ДОБАВЛЕН ЭТОТ ИМПОРТ
from fastapi import APIRouter, HTTPException, Depends, Request
from loguru import logger
from typing import List, Optional, Dict, Any

from app.schemas.message_schemas import ProcessRequest, ProcessResponse, AICoreResponseData, ErrorDetails, DebugInfo # MODIFIED: Schema names
from app.schemas.prompt_schemas import PromptCreate, PromptResponse
from app.schemas.user_schemas import UserCreate, UserResponse
from app.schemas.appointment_schemas import AppointmentCreate, AppointmentResponse
from datetime import datetime, timezone # Ensure datetime and timezone are imported
from app.core.llm_processor import LLMProcessor
from app.core.i18n import I18nLoader
from app.core.config import settings
from app.core.db import get_database # Для передачи в LLMProcessor

router = APIRouter()

# Dependency Injection для I18nLoader и LLMProcessor
def get_i18n_loader(request: Request) -> I18nLoader:
    # Получаем экземпляр из состояния приложения, инициализированный в lifespan
    return request.app.state.i18n_loader

def get_llm_processor(
    db = Depends(get_database), 
    i18n_loader: I18nLoader = Depends(get_i18n_loader)
) -> LLMProcessor:
    # db_instance will be passed from process_user_message directly if needed by LLMProcessor,
    # but LLMProcessor constructor might not need it if db is only used for client_config lookup here.
    # Let's assume LLMProcessor still needs db_instance for other potential operations (e.g. history).
    return LLMProcessor(db_instance=db, i18n_loader=i18n_loader)


@router.post(
    "/api/v1/process",  # MODIFIED: Path
    response_model=ProcessResponse,  # MODIFIED: Response model
    summary="Process Incoming User Message", 
    tags=["Messaging"] # Kept tags as Messaging, can be "AI Processing"
)
async def process_message(  # MODIFIED: Function name
    request_data: ProcessRequest,  # MODIFIED: Request data type hint
    llm_processor: LLMProcessor = Depends(get_llm_processor),
    db = Depends(get_database) 
):
    logger.info(f"Processing message for user: {request_data.user_id} on {request_data.platform} via n8n_session: {request_data.session_id}")
    logger.debug(f"Incoming request payload: {request_data.model_dump_json(indent=2)}")

    try:
        client_config_for_llm = None
        source_of_config = "hardcoded_mvp" # Источник конфигурации

        if db is not None: # Только если БД доступна
            # Сначала пытаемся найти конфиг по client_id из запроса
            if request_data.client_id:
                client_config_db = await db[settings.MONGO_CLIENTS_COLLECTION].find_one({"client_id": request_data.client_id})
                if client_config_db:
                    source_of_config = f"db_client:{request_data.client_id}"
                    client_config_for_llm = client_config_db
            
            # Если не нашли, пытаемся загрузить дефолтный конфиг
            if not client_config_for_llm:
                logger.warning(f"Client config for client_id '{request_data.client_id}' not found. Attempting fallback: '{settings.DEFAULT_FALLBACK_CLIENT_ID}'.")
                client_config_db = await db[settings.MONGO_CLIENTS_COLLECTION].find_one({"client_id": settings.DEFAULT_FALLBACK_CLIENT_ID})
                if client_config_db:
                    source_of_config = f"db_fallback_client:{settings.DEFAULT_FALLBACK_CLIENT_ID}"
                    client_config_for_llm = client_config_db
                else:
                    logger.warning(f"Fallback client config '{settings.DEFAULT_FALLBACK_CLIENT_ID}' also not found in DB.")
        else:
            logger.warning("Database instance is None. Cannot load client configurations from DB.")

        # Если не нашли конфиг нигде, используем MVP настройки
        if not client_config_for_llm:
            logger.info(f"Using hardcoded MVP settings as client_config. Source: {source_of_config}")
            client_config_for_llm = {
                "client_id": settings.MVP_CLIENT_ID,
                "name": settings.MVP_CLIENT_NAME,
                "persona": settings.MVP_CLIENT_PERSONA,
                "tone": settings.MVP_CLIENT_TONE,
                "business_type": settings.MVP_BUSINESS_TYPE,
                "default_lang": settings.DEFAULT_LANG_API,
                "history_max_messages": settings.HISTORY_MAX_MESSAGES
            }

        # Определяем business_type для загрузки промпта
        effective_business_type: str
        if request_data.business_type:
            effective_business_type = request_data.business_type
            logger.info(f"Using business_type from request: {effective_business_type}")
        elif "business_type" in client_config_for_llm and client_config_for_llm["business_type"]:
            effective_business_type = client_config_for_llm["business_type"]
            logger.info(f"Using business_type from loaded client_config ('{client_config_for_llm['client_id']}'): {effective_business_type}")
        else:
            effective_business_type = settings.DEFAULT_FALLBACK_BUSINESS_TYPE
            logger.info(f"Using DEFAULT_FALLBACK_BUSINESS_TYPE: {effective_business_type}")
        
        client_config_for_llm["business_type"] = effective_business_type

        # Дозаполняем остальными MVP значениями, если их нет в client_config_for_llm
        client_config_for_llm.setdefault("name", settings.MVP_CLIENT_NAME)
        client_config_for_llm.setdefault("persona", settings.MVP_CLIENT_PERSONA)
        client_config_for_llm.setdefault("tone", settings.MVP_CLIENT_TONE)
        client_config_for_llm.setdefault("default_lang", settings.DEFAULT_LANG_API)
        client_config_for_llm.setdefault("history_max_messages", settings.HISTORY_MAX_MESSAGES)
        
        logger.debug(f"Final client_config for LLMProcessor (client_id: '{client_config_for_llm['client_id']}', business_type: '{client_config_for_llm['business_type']}'): {client_config_for_llm}")

        llm_processed_data = await llm_processor.process_with_llm_langchain(
            client_config=client_config_for_llm,
            user_id=request_data.user_id,
            platform=request_data.platform,
            current_user_message=request_data.message,
            conversation_history=request_data.conversation_history or [],
            language_preference=request_data.language,
            session_id=request_data.session_id,
            message_metadata=request_data.message_metadata
        )
        
        if "error" in llm_processed_data:
            logger.error(f"Error from LLM Processor for session {request_data.session_id}: {llm_processed_data.get('error_message', 'Unknown LLM error')}")
            return ProcessResponse(
                request_id=request_data.session_id or "unknown_session",
                status="error",
                error_details=ErrorDetails(
                    code=llm_processed_data.get("error", "LLM_PROCESSING_FAILED"), 
                    message=llm_processed_data.get("error_message", "Failed to process message with LLM.")
                )
            )

        response_data = AICoreResponseData(
            response_text=llm_processed_data.get("response_text", "No response generated."),
            language_detected=llm_processed_data.get("language_detected", client_config_for_llm["default_lang"]),
            intent=llm_processed_data.get("intent"),
            entities=llm_processed_data.get("entities"),
            actions_for_n8n=llm_processed_data.get("actions_for_n8n", [])
        )
        
        debug_payload = llm_processed_data.get("debug_info") if isinstance(llm_processed_data.get("debug_info"), dict) else {}

        return ProcessResponse(
            request_id=request_data.session_id or "unknown_session",
            status="success",
            data=response_data,
            debug_info=DebugInfo(**debug_payload) if debug_payload else None
        )

    except HTTPException: 
        raise
    except Exception as e:
        tb_str = traceback.format_exc() 
        logger.critical(f"Critical unhandled error in /api/v1/process for session {request_data.session_id}: {e}\nTRACEBACK:\n{tb_str}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/api/v1/prompts", response_model=PromptResponse, summary="Create or Update Prompt for a Business Type", tags=["Prompts"])
async def create_or_update_prompt(prompt: PromptCreate, db = Depends(get_database)): # Ensure db type hint if needed
    try:
        result = await db[settings.MONGO_PROMPTS_COLLECTION].update_one(
            {"business_type": prompt.business_type},
            {"$set": {"prompt": prompt.prompt}},
            upsert=True
        )
        # Optional: Check result.modified_count or result.upserted_id for more specific response
        logger.info(f"Prompt for business_type '{prompt.business_type}' {'upserted' if result.upserted_id else 'updated'}. Modified count: {result.modified_count}, Upserted ID: {result.upserted_id}")
        return PromptResponse(success=True, business_type=prompt.business_type)
    except Exception as e:
        logger.error(f"Error creating/updating prompt for business_type '{prompt.business_type}': {e}", exc_info=True)
        # Consider returning a more specific error response if desired
        raise HTTPException(status_code=500, detail=f"Failed to create or update prompt: {str(e)}")


@router.post("/api/v1/users", response_model=UserResponse, summary="Create or Update User", tags=["Users"])
async def create_or_update_user(user: UserCreate, db = Depends(get_database)):
    try:
        user_data = user.model_dump() # Use model_dump() for Pydantic v2+
        
        # Check if user exists
        existing_user = await db[settings.MONGO_USERS_COLLECTION].find_one(
            {"client_id": user.client_id, "user_id": user.user_id}
        )
        
        if existing_user:
            user_data["updated_at"] = datetime.now(timezone.utc)
            update_result = await db[settings.MONGO_USERS_COLLECTION].update_one(
                {"client_id": user.client_id, "user_id": user.user_id},
                {"$set": user_data}
            )
            action = "updated"
            if update_result.modified_count == 0 and update_result.matched_count > 0:
                 logger.info(f"User data for {user.user_id} was the same, no actual update performed.")
                 # action = "no_change" # Or similar if you want to distinguish
            else:
                logger.info(f"User {user.user_id} for client {user.client_id} updated.")
        else:
            user_data["created_at"] = datetime.now(timezone.utc)
            user_data["updated_at"] = datetime.now(timezone.utc) # Also set updated_at on creation
            insert_result = await db[settings.MONGO_USERS_COLLECTION].insert_one(user_data)
            action = "created"
            logger.info(f"User {user.user_id} for client {user.client_id} created with id {insert_result.inserted_id}.")
        
        return UserResponse(success=True, user_id=user.user_id, action=action)
    except Exception as e:
        logger.error(f"Error creating/updating user {user.user_id} for client {user.client_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create or update user: {str(e)}")


@router.post("/api/v1/appointments", response_model=AppointmentResponse, summary="Create Appointment", tags=["Appointments"])
async def create_appointment(appointment: AppointmentCreate, db = Depends(get_database)):
    try:
        appointment_data = appointment.model_dump()
        appointment_data["created_at"] = datetime.now(timezone.utc)
        appointment_data["updated_at"] = datetime.now(timezone.utc)
        appointment_data["status"] = "pending" # Default status
        
        # You might want to check if the user (appointment.user_id) exists first
        # user_exists = await db[settings.MONGO_USERS_COLLECTION].find_one({"client_id": appointment.client_id, "user_id": appointment.user_id})
        # if not user_exists:
        #     raise HTTPException(status_code=404, detail=f"User {appointment.user_id} not found for client {appointment.client_id}")

        result = await db[settings.MONGO_APPOINTMENTS_COLLECTION].insert_one(appointment_data)
        appointment_id = str(result.inserted_id)
        logger.info(f"Appointment created with ID {appointment_id} for user {appointment.user_id}, client {appointment.client_id}.")
        
        return AppointmentResponse(success=True, appointment_id=appointment_id)
    except HTTPException: # Re-raise HTTPException to avoid generic 500
        raise
    except Exception as e:
        logger.error(f"Error creating appointment for user {appointment.user_id}, client {appointment.client_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create appointment: {str(e)}")

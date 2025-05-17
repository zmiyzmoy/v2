from fastapi import APIRouter, HTTPException, Depends, Request
from loguru import logger
from typing import List, Optional, Dict, Any

from app.schemas.message_schemas import ProcessMessageRequest, ProcessMessageResponse, AICoreResponseData, ErrorDetails, DebugInfo
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
    return LLMProcessor(db_instance=db, i18n_loader=i18n_loader)


@router.post(
    "/process_message", 
    response_model=ProcessMessageResponse, 
    summary="Process Incoming User Message", 
    tags=["Messaging"]
)
async def process_user_message(
    request_data: ProcessMessageRequest,
    llm_processor: LLMProcessor = Depends(get_llm_processor)
):
    logger.info(f"Processing message for user: {request_data.user_id} on {request_data.platform} via n8n_session: {request_data.session_id}")
    logger.debug(f"Incoming request payload: {request_data.model_dump_json(indent=2)}")

    try:
        # Конфигурация клиента для MVP (в будущем будет грузиться из БД по request_data.client_id)
        client_config_mvp = {
            "client_id": request_data.client_id or settings.MVP_CLIENT_ID,
            "name": settings.MVP_CLIENT_NAME,
            "persona": settings.MVP_CLIENT_PERSONA,
            "tone": settings.MVP_CLIENT_TONE,
            "business_type": settings.MVP_BUSINESS_TYPE,
            "default_lang": request_data.language_preference or settings.DEFAULT_LANG_API,
            "llm_model": settings.DEFAULT_LLM_MODEL,
            "history_max_messages": settings.HISTORY_MAX_MESSAGES
        }
        logger.debug(f"Using client config for processing: {client_config_mvp}")

        llm_processed_data = await llm_processor.process_with_llm_langchain(
            client_config=client_config_mvp,
            user_id=request_data.user_id,
            platform=request_data.platform,
            current_user_message=request_data.text,
            conversation_history=request_data.conversation_history or [],
            language_preference=request_data.language_preference, # Передаем для логики внутри процессора
            session_id=request_data.session_id,
            message_metadata=request_data.message_metadata
        )
        # llm_processed_data должен содержать ключи: 
        # "response_text", "language_detected", "intent", "entities", "actions_for_n8n", "debug_info"
        # или "error", "error_message"

        if "error" in llm_processed_data:
            logger.error(f"Error from LLM Processor for session {request_data.session_id}: {llm_processed_data.get('error_message', 'Unknown LLM error')}")
            return ProcessMessageResponse(
                request_id=request_data.session_id or "unknown_session",
                status="error",
                error_details=ErrorDetails(
                    code=llm_processed_data.get("error", "LLM_PROCESSING_FAILED"), 
                    message=llm_processed_data.get("error_message", "Failed to process message with LLM.")
                )
            )

        response_data = AICoreResponseData(
            response_text=llm_processed_data.get("response_text", "No response generated."),
            language_detected=llm_processed_data.get("language_detected", client_config_mvp["default_lang"]),
            intent=llm_processed_data.get("intent"),
            entities=llm_processed_data.get("entities"),
            actions_for_n8n=llm_processed_data.get("actions_for_n8n", [])
        )
        
        debug_payload = llm_processed_data.get("debug_info") if isinstance(llm_processed_data.get("debug_info"), dict) else {}

        return ProcessMessageResponse(
            request_id=request_data.session_id or "unknown_session",
            status="success",
            data=response_data,
            debug_info=DebugInfo(**debug_payload) if debug_payload else None
        )

    except HTTPException: # Перехватываем HTTPException, чтобы не попасть в общий Exception ниже
        raise
    except Exception as e:
        logger.critical(f"Critical unhandled error in /process_message for session {request_data.session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage as LangchainSystemMessage
from loguru import logger
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from app.core.config import settings
from app.core.i18n import I18nLoader
from app.core.db import save_dialog_entry, get_dialog_history

class LLMProcessor:
    def __init__(self, db_instance: Any, i18n_loader: I18nLoader):
        self.db = db_instance
        self.i18n = i18n_loader

        self.llm = ChatOpenAI(
            model_name=settings.DEFAULT_LLM_MODEL,
            openai_api_key=settings.OPENROUTER_API_KEY,
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
        logger.info(f"LLMProcessor initialized with model: {settings.DEFAULT_LLM_MODEL} via OpenRouter.")
        if settings.LANGCHAIN_TRACING_V2 == "true":
             logger.info(f"LangSmith tracing should be active for project '{settings.LANGCHAIN_PROJECT}'.")


    async def _save_message_to_history(
        self, client_id: str, user_id: str, platform: str,
        content: Optional[str], role: str,
        session_id: Optional[str] = None,
        message_metadata: Optional[Dict[str, Any]] = None,
        llm_full_response: Optional[Dict[str, Any]] = None
    ):
        if self.db is None: # ИЗМЕНЕНИЕ ЗДЕСЬ
            logger.warning("Database instance not available. Skipping history save.")
            return

        content_to_save = content
        if not content:
             if role == "assistant" and llm_full_response and isinstance(llm_full_response.get("response_text"), str):
                 content_to_save = llm_full_response["response_text"]
             elif role == "assistant" and llm_full_response and llm_full_response.get("response_text") is None:
                 content_to_save = None
             else:
                logger.debug(f"Skipping saving message with no content for role {role} of user {user_id}.")
                return

        entry_data = {
            "client_id": client_id,
            "user_id": user_id,
            "platform": platform,
            "session_id_n8n": session_id,
            "role": role,
            "content": content_to_save,
            "timestamp": datetime.now(timezone.utc),
            "message_metadata_platform": message_metadata,
        }
        if role == "assistant" and llm_full_response:
            entry_data["llm_full_response_payload"] = llm_full_response

        await save_dialog_entry(self.db, entry_data)

    async def _load_prompt_from_db(self, business_type: str) -> str:
        if not self.db:
            logger.warning("Database instance not available. Using default prompt construction.")
            # Assuming _construct_default_system_prompt_content exists or will be created
            # For now, let's use the existing _construct_system_prompt_content
            # but it expects client_config and language.
            # We need a generic default or adapt _construct_system_prompt_content.
            # For this subtask, if DB is not available, we will fall back to a generic default prompt string.
            # Or, ideally, it should call the original _construct_system_prompt_content
            # with some default client_config. Let's try that.
            # This part might need refinement based on how _construct_system_prompt_content is structured.
            # The issue implies _construct_default_system_prompt_content() which is not currently in the file.
            # Let's use the existing _construct_system_prompt_content with a dummy client_config for default.
            logger.warning("Falling back to default prompt construction due to missing DB or prompt.")
            dummy_client_config = { # Provide a minimal config for the default prompt
                "name": settings.MVP_CLIENT_NAME,
                "business_type": business_type, # Use the passed business_type
                "tone": settings.MVP_CLIENT_TONE,
                "persona": settings.MVP_CLIENT_PERSONA
            }
            # Assuming default language from settings for this fallback
            return self._construct_system_prompt_content(dummy_client_config, settings.DEFAULT_LANG_API)

        prompt_doc = await self.db[settings.MONGO_PROMPTS_COLLECTION].find_one({"business_type": business_type})
        if not prompt_doc or "prompt" not in prompt_doc:
            logger.warning(f"Prompt for business_type '{business_type}' not found in DB. Using default prompt construction.")
            # Fallback to the original method if specific prompt not found
            dummy_client_config = {
                "name": settings.MVP_CLIENT_NAME, # Or load from a general client config if available
                "business_type": business_type,
                "tone": settings.MVP_CLIENT_TONE,
                "persona": settings.MVP_CLIENT_PERSONA
            }
            return self._construct_system_prompt_content(dummy_client_config, settings.DEFAULT_LANG_API)
        
        logger.info(f"Successfully loaded prompt for business_type '{business_type}' from DB.")
        return prompt_doc["prompt"]

    def _construct_system_prompt_content(self, client_config: Dict[str, Any], language: str) -> str:
        system_template = """Ты - AI-ассистент для бизнеса "{business_name}" (тип: {business_type}).
Твоя задача: внимательно проанализировать текущий запрос пользователя и историю диалога.
1. Понять намерение пользователя (например, запрос информации, бронирование, жалоба).
2. Извлечь ключевые сущности из запроса (например, название услуги, дата, время, имя).
3. Определить, какие действия должна предпринять система n8n (если нужны).
4. Сгенерировать максимально полезный, дружелюбный и вовлекающий ответ пользователю.
Ты должен общаться в тоне '{tone}' и от лица '{persona}'.
Всегда отвечай на языке, который ты определил как язык пользователя. Если сомневаешься, используй '{language_fallback}'.

Твой ответ ДОЛЖЕН БЫТЬ в формате JSON объекта со следующими обязательными ключами:
"response_text": (string) Твой естественный ответ пользователю.
"language_detected": (string) ISO 639-1 код определенного тобой языка пользователя (например, "ru", "en", "az").
"intent": (string|null) Краткая метка намерения пользователя (например, "greeting", "product_inquiry", "booking_request", "complaint", "other"). Если не уверен, ставь null.
"entities": (object|null) JSON объект извлеченных сущностей в формате ключ-значение (например, {{"service": "маникюр", "date": "завтра"}}). Если нет сущностей, ставь null.
"actions_for_n8n": (array) Список объектов действий для системы n8n. Каждое действие: {{"type": "имя_действия", "params": {{...}}}}. Если действий не требуется, верни пустой массив [].

Пример actions_for_n8n:
- Запрос информации о ценах: [{{"type": "get_price_list", "params": {{"service_category": "haircut"}}}}]
- Запись на услугу: [{{"type": "create_booking_lead", "params": {{"service": "маникюр", "client_name": "Анна", "phone": "...", "datetime": "2025-05-20T14:00:00"}}}}]
- Перевод на оператора: [{{"type": "escalate_to_human", "params": {{"reason": "сложный вопрос"}}}}]

Убедись, что JSON валиден.
"""
        return system_template.format(
            business_name=client_config.get('name', settings.MVP_CLIENT_NAME),
            business_type=client_config.get('business_type', settings.MVP_BUSINESS_TYPE),
            tone=client_config.get('tone', settings.MVP_CLIENT_TONE),
            persona=client_config.get('persona', settings.MVP_CLIENT_PERSONA),
            language_fallback=language
        ).strip()

    def _format_history_for_lc(self, conversation_history_db: List[Dict[str, Any]]) -> List[Any]:
        lc_messages = []
        for msg_doc in conversation_history_db:
            role = msg_doc.get("role")
            content = msg_doc.get("content")
            if role == "user" and content is not None:
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant" and content is not None:
                lc_messages.append(AIMessage(content=content))
        return lc_messages

    async def process_with_llm_langchain(
        self,
        client_config: Dict[str, Any],
        user_id: str,
        platform: str,
        current_user_message: str,
        conversation_history: List[Dict[str, Any]],
        language_preference: Optional[str] = None,
        session_id: Optional[str] = None,
        message_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:

        client_id = client_config["client_id"]
        business_type = client_config.get("business_type", settings.MVP_BUSINESS_TYPE)
        logger.info(f"Processing message for client_id: {client_id}, business_type: {business_type}, platform: {platform}, user_id: {user_id}, session_id: {session_id}")

        await self._save_message_to_history(
            client_id=client_id, user_id=user_id, platform=platform,
            content=current_user_message, role="user", session_id=session_id,
            message_metadata=message_metadata
        )

        effective_lang = language_preference or client_config.get("default_lang") or settings.DEFAULT_LANG_API

        if not conversation_history and self.db is not None: # ИЗМЕНЕНИЕ ЗДЕСЬ
            logger.debug(f"Conversation history from n8n is empty for {user_id}. Fetching from DB...")
            history_from_db_docs = await get_dialog_history(self.db, client_id, user_id, settings.HISTORY_MAX_MESSAGES)
            formatted_lc_history = self._format_history_for_lc(history_from_db_docs)
            logger.debug(f"Fetched {len(formatted_lc_history)} messages from DB history for LLM.")
        else:
            formatted_lc_history = self._format_history_for_lc(conversation_history)
            logger.debug(f"Using {len(formatted_lc_history)} messages from n8n-provided history for LLM.")

        business_type = client_config.get("business_type", settings.MVP_BUSINESS_TYPE) # Get business_type from client_config
        system_prompt_str = await self._load_prompt_from_db(business_type)

        prompt = ChatPromptTemplate.from_messages([
            LangchainSystemMessage(content=system_prompt_str),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            HumanMessage(content="{input}")
        ])

        output_parser = JsonOutputParser()
        chain = prompt | self.llm | output_parser

        final_response_payload = {}
        start_time = datetime.now()

        try:
            logger.debug(f"Invoking LLM for user '{user_id}', session '{session_id}'. History length for LLM: {len(formatted_lc_history)}")
            llm_result_dict = await chain.ainvoke({
                "chat_history": formatted_lc_history,
                "input": current_user_message
            })

            if not isinstance(llm_result_dict, dict) or "response_text" not in llm_result_dict:
                logger.error(f"LLM response is not a valid dict or missing 'response_text'. Response: {llm_result_dict}")
                if isinstance(llm_result_dict, str):
                    try:
                        llm_result_dict = output_parser.parse(llm_result_dict)
                        if "response_text" not in llm_result_dict: raise ValueError("Still no response_text")
                    except Exception as parse_err:
                        logger.error(f"Could not re-parse LLM string response: {parse_err}")
                        raise ValueError("Invalid LLM response format after re-parse attempt")
                else:
                  raise ValueError("Invalid LLM response format")


            final_response_payload = {
                "response_text": llm_result_dict.get("response_text", self.i18n.get("llm_empty_response", effective_lang)),
                "language_detected": llm_result_dict.get("language_detected", effective_lang),
                "intent": llm_result_dict.get("intent"),
                "entities": llm_result_dict.get("entities", {}),
                "actions_for_n8n": llm_result_dict.get("actions_for_n8n", [])
            }
            logger.info(f"LLM call successful for user '{user_id}'. Intent: {final_response_payload['intent']}")

        except Exception as e:
            logger.error(f"Error during LLM chain for user '{user_id}', session '{session_id}': {e}", exc_info=True)
            error_text = self.i18n.get("llm_invocation_error", effective_lang)
            final_response_payload = {
                "error": "LLM_INVOCATION_FAILURE",
                "error_message": str(e),
                "response_text": error_text,
                "language_detected": effective_lang,
                "actions_for_n8n": []
            }

        end_time = datetime.now()
        processing_time_ms = (end_time - start_time).total_seconds() * 1000

        final_response_payload["debug_info"] = {
            "model_used": self.llm.model_name,
            "processing_time_ms": round(processing_time_ms, 2)
        }

        await self._save_message_to_history(
            client_id=client_id, user_id=user_id, platform=platform,
            content=final_response_payload.get("response_text"),
            role="assistant", session_id=session_id,
            llm_full_response=final_response_payload
        )

        return final_response_payload

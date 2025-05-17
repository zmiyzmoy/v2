from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage as LangchainSystemMessage # Переименовал во избежание конфликта
from loguru import logger
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from app.core.config import settings
from app.core.i18n import I18nLoader
from app.core.db import save_dialog_entry, get_dialog_history # Импортируем функции БД

class LLMProcessor:
    def __init__(self, db_instance: Any, i18n_loader: I18nLoader):
        self.db = db_instance # Экземпляр БД Motor
        self.i18n = i18n_loader
        
        self.llm = ChatOpenAI(
            model_name=settings.DEFAULT_LLM_MODEL,
            openai_api_key=settings.OPENROUTER_API_KEY,
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_TOKENS,
            # request_timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS, # Можно добавить в config
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
        if not self.db:
            logger.warning("Database instance not available. Skipping history save.")
            return

        if not content: # Не сохраняем сообщения без контента
             # Исключение для ответов ассистента, где контент может быть в llm_full_response
             if role == "assistant" and llm_full_response and isinstance(llm_full_response.get("response_text"), str):
                 content_to_save = llm_full_response["response_text"]
             else:
                logger.debug(f"Skipping saving message with no content for role {role} of user {user_id}.")
                return
        else:
            content_to_save = content

        entry_data = {
            "client_id": client_id,
            "user_id": user_id,
            "platform": platform,
            "session_id_n8n": session_id,
            "role": role,
            "content": content_to_save, # Используем обработанный content_to_save
            "timestamp": datetime.now(timezone.utc),
            "message_metadata_platform": message_metadata,
        }
        if role == "assistant" and llm_full_response:
            entry_data["llm_full_response_payload"] = llm_full_response # Сохраняем весь ответ LLM

        await save_dialog_entry(self.db, entry_data)


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
            language_fallback=language # Используем язык, определенный для этого запроса
        ).strip()

    def _format_history_for_lc(self, conversation_history_db: List[Dict[str, Any]]) -> List[Any]:
        lc_messages = []
        for msg_doc in conversation_history_db: # msg_doc это документ из MongoDB
            role = msg_doc.get("role")
            content = msg_doc.get("content")
            if role == "user" and content:
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant" and content:
                lc_messages.append(AIMessage(content=content))
        return lc_messages

    async def process_with_llm_langchain(
        self,
        client_config: Dict[str, Any],
        user_id: str,
        platform: str,
        current_user_message: str,
        conversation_history: List[Dict[str, Any]], # Это уже отформатированный n8n список {"role": ..., "content": ...}
        language_preference: Optional[str] = None,
        session_id: Optional[str] = None,
        message_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        
        client_id = client_config["client_id"]

        await self._save_message_to_history(
            client_id=client_id, user_id=user_id, platform=platform,
            content=current_user_message, role="user", session_id=session_id,
            message_metadata=message_metadata
        )

        effective_lang = language_preference or client_config.get("default_lang") or settings.DEFAULT_LANG_API
        
        # Загружаем историю из БД, если n8n ее не передал или передал неполную
        # Для MVP, n8n передает историю, отформатированную в Code ноде
        # Если conversation_history пуст, можно загрузить из БД здесь
        if not conversation_history and self.db:
            logger.debug(f"Conversation history from n8n is empty for {user_id}. Fetching from DB...")
            history_from_db_docs = await get_dialog_history(self.db, client_id, user_id, settings.HISTORY_MAX_MESSAGES)
            # history_from_db_docs уже отсортирован (старые -> новые)
            # Преобразуем его в формат, который ожидает _format_history_for_lc (если он отличается от ConversationHistoryItem)
            # В нашем случае get_dialog_history уже возвращает документы с 'role' и 'content'
            formatted_lc_history = self._format_history_for_lc(history_from_db_docs)
            logger.debug(f"Fetched {len(formatted_lc_history)} messages from DB history.")
        else:
            # Используем историю, переданную от n8n, предполагая, что она уже в формате LangChain Messages
            # или близка к этому (список словарей {"role": ..., "content": ...})
            formatted_lc_history = self._format_history_for_lc(conversation_history)


        system_prompt_str = self._construct_system_prompt_content(client_config, effective_lang)
        
        prompt = ChatPromptTemplate.from_messages([
            LangchainSystemMessage(content=system_prompt_str),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            HumanMessage(content="{input}")
        ])
        
        # JsonOutputParser() ожидает, что LLM вернет строку, которая является валидным JSON.
        # Если LLM сам возвращает JSON объект (некоторые модели и API это поддерживают с response_format),
        # то JsonOutputParser может не понадобиться или нужна другая конфигурация.
        # Для OpenAI/OpenRouter с "response_format": {"type": "json_object"} в запросе,
        # ответ в message.content уже будет JSON строкой.
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
            # llm_result_dict это уже распарсенный JSON (python dict)
            
            if not isinstance(llm_result_dict, dict) or "response_text" not in llm_result_dict:
                logger.error(f"LLM response is not a valid dict or missing 'response_text'. Response: {llm_result_dict}")
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
                "actions_for_n8n": [] # Не предлагаем действий при ошибке LLM
            }
        
        end_time = datetime.now()
        processing_time_ms = (end_time - start_time).total_seconds() * 1000
        
        # Добавляем отладочную информацию
        final_response_payload["debug_info"] = {
            "model_used": self.llm.model_name,
            "processing_time_ms": round(processing_time_ms, 2)
            # Токены можно получить, если LangSmith включен и вы парсите его данные,
            # или если используете коллбэки LangChain для сбора статистики.
            # "prompt_tokens": ..., "completion_tokens": ...
        }

        await self._save_message_to_history(
            client_id=client_id, user_id=user_id, platform=platform,
            content=final_response_payload.get("response_text"), # Сохраняем только текст для пользователя
            role="assistant", session_id=session_id,
            llm_full_response=final_response_payload # Сохраняем весь структурированный ответ
        )
        
        return final_response_payload

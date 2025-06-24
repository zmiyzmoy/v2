from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI # ADDED for Gemini
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage as LangchainSystemMessage
from loguru import logger
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from app.core.config import settings
from app.core.i18n import I18nLoader
from app.core.db import save_dialog_entry, get_dialog_history
from app.schemas.message_schemas import ActionForN8N

# Pydantic model defining the expected JSON structure from the LLM
class LLMJsonOutput(BaseModel):
    response_text: str = Field(description="Your natural language response to the user.")
    language_detected: str = Field(description="ISO 639-1 code of the language you detected the user is speaking (e.g., 'ru', 'en', 'az').")
    intent: Optional[str] = Field(None, description="A brief label for the user's intent (e.g., 'greeting', 'product_inquiry', 'booking_request', 'complaint', 'other'). If unsure, set to null.")
    entities: Optional[Dict[str, Any]] = Field(None, description="A JSON object of extracted entities as key-value pairs (e.g., {\"service\": \"маникюр\", \"date\": \"tomorrow\"}). If no entities, set to null.")
    actions_for_n8n: List[ActionForN8N] = Field(default_factory=list, description="List of action objects for the n8n system. Each action: {\"type\": \"action_name\", \"params\": {...}}. If no actions are needed, return an empty list [].")

    class Config: # ADDED THIS CONFIG
        arbitrary_types_allowed = True

class LLMProcessor:
    def __init__(self, db_instance: Any, i18n_loader: I18nLoader):
        if db_instance is None:
            # This error will be caught by FastAPI's dependency injection system
            # and result in a 500 Internal Server Error response if
            # get_database() returns None.
            logger.error("LLMProcessor initialized with no database instance. Database is not available.")
            raise ValueError("Database instance is required for LLMProcessor.")

        self.db = db_instance
        self.i18n = i18n_loader
        self.output_parser = PydanticOutputParser(pydantic_object=LLMJsonOutput)
        # LLM client will be initialized per-request in process_with_llm_langchain
        # using client-specific configurations.
        logger.info("LLMProcessor initialized. LLM client will be configured per request.")


    async def _save_message_to_history(
        self, client_id: str, user_id: str, platform: str,
        content: Optional[str], role: str,
        session_id: Optional[str] = None,
        message_metadata: Optional[Dict[str, Any]] = None,
        llm_full_response: Optional[Dict[str, Any]] = None
    ):
        # self.db is now guaranteed to be non-None due to the check in __init__
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


    def _construct_system_prompt_content(self, client_config: Dict[str, Any], language: str) -> str:
        system_template = """Ты - AI-ассистент для бизнеса "{business_name}" (тип: {business_type}).
Твоя задача: внимательно проанализировать текущий запрос пользователя и историю диалога.
Основные цели:
1. Определить намерение (intent) пользователя.
2. Извлечь ключевые сущности (entities) из запроса.
3. Определить необходимые действия для системы n8n (actions_for_n8n).
4. Сгенерировать полезный, дружелюбный и вовлекающий ответ (response_text) пользователю.

Общие инструкции:
- Общайся в тоне '{tone}' и от лица '{persona}'.
- Всегда отвечай на языке, который ты определил как язык пользователя. Если сомневаешься, используй '{language_fallback}'.
- Твой ответ ДОЛЖЕН БЫТЬ в формате JSON, соответствующем следующей схеме:
{json_schema}

Важно:
- "response_text" должен быть твоим естественным ответом пользователю.
- "language_detected" должен быть ISO 639-1 кодом языка пользователя.
- "intent" должен быть краткой меткой намерения (null, если не уверен).
- "entities" должен быть JSON объектом (null, если нет).
- "actions_for_n8n" должен быть списком объектов действий (пустой список [], если действий не требуется).

Примеры для "actions_for_n8n":
- Запрос информации о ценах: `[{{\"type\": \"get_price_list\", \"params\": {{\"service_category\": \"haircut\"}}}}]`
- Запись на услугу: `[{{\"type\": \"create_booking_lead\", \"params\": {{\"service\": \"маникюр\", \"client_name\": \"Анна\", \"phone\": \"...\", \"datetime\": \"2025-05-20T14:00:00\"}}}}]`
- Перевод на оператора: `[{{\"type\": \"escalate_to_human\", \"params\": {{\"reason\": \"сложный вопрос\"}}}}]`

Убедись, что JSON строго валиден и соответствует предоставленной схеме.
"""
        return system_template.format(
            business_name=client_config.get('name', settings.MVP_CLIENT_NAME),
            business_type=client_config.get('business_type', settings.MVP_BUSINESS_TYPE),
            json_schema=self.output_parser.get_format_instructions(),
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

        await self._save_message_to_history(
            client_id=client_id, user_id=user_id, platform=platform,
            content=current_user_message, role="user", session_id=session_id,
            message_metadata=message_metadata
        )

        effective_lang = language_preference or client_config.get("default_lang") or settings.DEFAULT_LANG_API

        # self.db is now guaranteed to be non-None due to the check in __init__
        if not conversation_history:
            logger.debug(f"Conversation history from n8n is empty for {user_id}. Fetching from DB...")
            history_from_db_docs = await get_dialog_history(self.db, client_id, user_id, settings.HISTORY_MAX_MESSAGES)
            formatted_lc_history = self._format_history_for_lc(history_from_db_docs)
            logger.debug(f"Fetched {len(formatted_lc_history)} messages from DB history for LLM.")
        else:
            formatted_lc_history = self._format_history_for_lc(conversation_history)
            logger.debug(f"Using {len(formatted_lc_history)} messages from n8n-provided history for LLM.")


        system_prompt_str = self._construct_system_prompt_content(client_config, effective_lang)

        prompt = ChatPromptTemplate.from_messages([
            LangchainSystemMessage(content=system_prompt_str),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            HumanMessage(content="{input}"),
            # The PydanticOutputParser will add its own formatting instructions if not already in the prompt
        ])

        # Initialize LLM client with client-specific configuration
        llm_provider = client_config.get("llm_config_provider", settings.DEFAULT_LLM_PROVIDER).lower()
        llm_model_name = client_config.get("llm_model", settings.DEFAULT_LLM_MODEL)
        llm_api_key = client_config.get("llm_config_api_key") # Client specific key
        llm_temperature = client_config.get("llm_config_temperature", settings.LLM_TEMPERATURE)
        llm_max_tokens = client_config.get("llm_config_max_tokens", settings.LLM_MAX_TOKENS)

        llm_client: Any = None # Initialize with Any to satisfy type checker for now

        if llm_provider == "gemini":
            if not llm_api_key: # Fallback to global Gemini key if client has no specific key
                llm_api_key = settings.GOOGLE_GEMINI_API_KEY
            if not llm_api_key:
                logger.error(f"Gemini API key not found for client '{client_id}' and no global GOOGLE_GEMINI_API_KEY set.")
                raise ValueError(f"Gemini API key is required for provider 'gemini'.")

            llm_client = ChatGoogleGenerativeAI(
                model=llm_model_name,
                google_api_key=llm_api_key,
                temperature=llm_temperature
                # max_tokens is not a direct param for ChatGoogleGenerativeAI constructor,
                # it's usually handled via generation_config or specific call params.
                # For now, we'll rely on model defaults or later explore generation_config.
                # convert_system_message_to_human=True # Might be needed depending on Gemini model version and Langchain adapter
            )
            logger.debug(f"Using Gemini LLM client: model={llm_model_name}, temp={llm_temperature}")

        elif llm_provider == "openrouter":
            if not llm_api_key: # Fallback to global OpenRouter key
                llm_api_key = settings.OPENROUTER_API_KEY
            if not llm_api_key:
                logger.error(f"OpenRouter API key not found for client '{client_id}' and no global OPENROUTER_API_KEY set.")
                raise ValueError(f"API key is required for provider 'openrouter'.")

            llm_client = ChatOpenAI(
                model_name=llm_model_name,
                openai_api_key=llm_api_key,
                openai_api_base="https://openrouter.ai/api/v1",
                temperature=llm_temperature,
                max_tokens=llm_max_tokens,
            )
            logger.debug(f"Using OpenRouter LLM client: model={llm_model_name}, temp={llm_temperature}")

        elif llm_provider == "openai":
            # Assuming you might add a direct OpenAI integration later
            if not llm_api_key: # Fallback to a global OpenAI key if you add one to settings
                                # e.g., settings.OPENAI_API_KEY (distinct from OPENROUTER_API_KEY)
                # For now, let's assume it might be the same as OpenRouter key if not specified, or error.
                # This part would need a dedicated settings.OPENAI_API_KEY if used directly.
                llm_api_key = settings.OPENROUTER_API_KEY # Placeholder, adjust if you have a separate OpenAI key
                logger.warning("OpenAI provider selected, but no specific client API key. Falling back to OPENROUTER_API_KEY as placeholder for direct OpenAI.")

            if not llm_api_key:
                logger.error(f"OpenAI API key not found for client '{client_id}'.")
                raise ValueError(f"API key is required for provider 'openai'.")

            llm_client = ChatOpenAI(
                model_name=llm_model_name,
                openai_api_key=llm_api_key,
                # openai_api_base is not set, so it uses default OpenAI
                temperature=llm_temperature,
                max_tokens=llm_max_tokens,
            )
            logger.debug(f"Using OpenAI LLM client: model={llm_model_name}, temp={llm_temperature}")
        else:
            logger.error(f"Unsupported LLM provider: {llm_provider} for client_id: {client_id}")
            raise ValueError(f"Unsupported LLM provider: {llm_provider}")

        if llm_client is None: # Should have been caught by provider check, but as a safeguard
            logger.error(f"LLM client could not be initialized for provider: {llm_provider}")
            raise ValueError("LLM client initialization failed.")

        chain = prompt | llm_client | self.output_parser

        final_response_payload = {}
        start_time = datetime.now()

        try:
            logger.debug(f"Invoking LLM for user '{user_id}', session '{session_id}'. History length for LLM: {len(formatted_lc_history)}")
            llm_result_obj: LLMJsonOutput = await chain.ainvoke({
                "chat_history": formatted_lc_history,
                "input": current_user_message
            })

            # Convert Pydantic model to dict for existing processing logic
            # Access attributes directly from the llm_result_obj
            final_response_payload = {
                "response_text": llm_result_obj.response_text if llm_result_obj.response_text else self.i18n.get("llm_empty_response", effective_lang),
                "language_detected": llm_result_obj.language_detected if llm_result_obj.language_detected else effective_lang,
                "intent": llm_result_obj.intent,
                "entities": llm_result_obj.entities if llm_result_obj.entities is not None else {}, # Ensure entities is a dict
                "actions_for_n8n": [action.model_dump() for action in llm_result_obj.actions_for_n8n] # Convert ActionForN8N objects to dicts
            }
            logger.info(f"LLM call successful for user '{user_id}'. Intent: {final_response_payload.get('intent')}")

        except Exception as e: # Includes PydanticOutputParser's OutputFixingParser errors if it tries to fix and fails, or direct parsing errors
            logger.error(f"Error during LLM chain or parsing for user '{user_id}', session '{session_id}': {e}", exc_info=True)
            error_text = self.i18n.get("llm_invocation_error", effective_lang)
            # Attempt to include more specific error information if available from Langchain's exceptions
            error_message_detail = str(e)
            if hasattr(e, 'llm_output'): # For some Langchain errors
                error_message_detail = f"LLM Output: {e.llm_output}. Original Error: {str(e)}"

            final_response_payload = {
                "error": "LLM_PROCESSING_ERROR", # More generic error code
                "error_message": error_message_detail,
                "response_text": error_text,
                "language_detected": effective_lang,
                "actions_for_n8n": []
            }

        end_time = datetime.now()
        processing_time_ms = (end_time - start_time).total_seconds() * 1000

        final_response_payload["debug_info"] = {
            "model_used": llm_client.model_name, # Use the dynamically configured client's model name
            "processing_time_ms": round(processing_time_ms, 2)
        }

        await self._save_message_to_history(
            client_id=client_id, user_id=user_id, platform=platform,
            content=final_response_payload.get("response_text"),
            role="assistant", session_id=session_id,
            llm_full_response=final_response_payload
        )

        return final_response_payload

from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional, Dict, Any # Убедитесь, что HttpUrl импортирован, если будете его использовать для URL

# --- Модели для запроса к /process_message ---
class ConversationHistoryItem(BaseModel):
    role: str = Field(..., description="Role of the message sender, e.g., 'user' or 'assistant'")
    content: str = Field(..., description="Content of the message")

class ProcessMessageRequest(BaseModel):
    user_id: str = Field(..., description="Unique identifier for the user, prefixed by platform (e.g., whatsapp:12345)")
    platform: str = Field(..., description="Platform of the message (e.g., whatsapp, instagram)")
    text: str = Field(..., description="The user's message text")
    client_id: Optional[str] = Field(None, description="Identifier for the client/tenant this agent is serving")
    language_preference: Optional[str] = Field(None, description="User's preferred language (ISO 639-1 code, e.g., ru, en)")
    session_id: Optional[str] = Field(None, description="Session ID from n8n for tracing or context linking")
    message_metadata: Optional[Dict[str, Any]] = Field(None, description="Original message metadata from the platform (e.g., message_id, timestamp)")
    conversation_history: Optional[List[ConversationHistoryItem]] = Field(None, description="Recent conversation history")
    current_fsm_data: Optional[Dict[str, Any]] = Field(None, description="Current FSM data if FSM is managed by n8n (for MVP, likely null)")

# --- Модели для ответа от /process_message ---
class ActionForN8N(BaseModel):
    type: str = Field(..., description="Type of action for n8n to execute (e.g., 'send_email', 'create_deal')")
    params: Optional[Dict[str, Any]] = Field(None, description="Parameters for this action")

class AICoreResponseData(BaseModel):
    response_text: str = Field(..., description="The AI-generated text response for the user")
    language_detected: str = Field(..., description="Language detected/used for the response (ISO 639-1)")
    intent: Optional[str] = Field(None, description="Detected user intent (e.g., 'booking_request', 'faq_price')")
    entities: Optional[Dict[str, Any]] = Field(None, description="Extracted entities as key-value pairs")
    actions_for_n8n: Optional[List[ActionForN8N]] = Field(default_factory=list, description="List of actions for n8n to perform") # Изменено на default_factory

class ErrorDetails(BaseModel):
    code: str = Field(..., description="Internal error code (e.g., 'LLM_TIMEOUT', 'DB_ERROR')")
    message: str = Field(..., description="Human-readable error message")

class DebugInfo(BaseModel):
    model_used: Optional[str] = None
    processing_time_ms: Optional[float] = None
    # Можно добавить поля для токенов, если будете их отслеживать
    # prompt_tokens: Optional[int] = None
    # completion_tokens: Optional[int] = None
    # cost: Optional[float] = None

class ProcessMessageResponse(BaseModel):
    request_id: str = Field(..., description="ID linking to the n8n session or original request for tracing")
    status: str = Field(..., description="Status of the processing ('success' or 'error')")
    data: Optional[AICoreResponseData] = None
    error_details: Optional[ErrorDetails] = None
    debug_info: Optional[DebugInfo] = None

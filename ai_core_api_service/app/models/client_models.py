from beanie import Document, Indexed
from pydantic import Field, EmailStr # EmailStr not used yet, but good for future user models
from typing import Optional, List
from uuid import uuid4
from datetime import datetime, timezone # Ensure timezone aware datetimes

from app.schemas.admin_schemas import LLMConfigSchema # Re-use the LLM config schema
from passlib.context import CryptContext

# Initialize passlib context
# Using bcrypt, but you can configure other schemes
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_secret(secret: str) -> Optional[str]:
    if not secret:
        return None
    return pwd_context.hash(secret)

def verify_secret(plain_secret: str, hashed_secret: Optional[str]) -> bool:
    if not plain_secret or not hashed_secret:
        return False
    return pwd_context.verify(plain_secret, hashed_secret)


class ClientConfiguration(Document):
    # Use Indexed for fields that will be queried frequently
    client_id: Indexed(str, unique=True) = Field(default_factory=lambda: f"client_{uuid4().hex[:12]}")
    client_name: str

    client_secret_hashed: Optional[str] = Field(None) # Store hashed secret

    persona: str
    tone: str
    business_type: str
    default_lang: str

    llm_config: LLMConfigSchema = Field(default_factory=LLMConfigSchema)

    history_max_messages: int
    is_active: bool = True

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Example of a pre-save hook to update `updated_at`
    # from beanie.odm.actions import before_event, Insert, Replace, SaveChanges
    # @before_event([Replace, SaveChanges])
    # async def update_updated_at(self):
    #     self.updated_at = datetime.now(timezone.utc)

    class Settings:
        name = "client_configurations" # MongoDB collection name
        keep_nulls = False # Don't save fields with None values, good for partial updates if not using $set

    # Helper methods for secret management (could also be in a service layer)
    def set_secret(self, plain_secret: str):
        self.client_secret_hashed = hash_secret(plain_secret)

    def check_secret(self, plain_secret: str) -> bool:
        if not self.client_secret_hashed or not plain_secret:
            return False
        return verify_secret(plain_secret, self.client_secret_hashed)

    # Method to transform model to response schema, handling sensitive fields
    def to_response_schema(self) -> 'ClientConfigurationResponseSchema':
        # Dynamically import here to avoid circular dependency if schemas also import models
        from app.schemas.admin_schemas import ClientConfigurationResponseSchema

        llm_config_dict = self.llm_config.model_dump()
        # Ensure api_key is not part of the response if it was somehow loaded into the model
        # (though Beanie projection should ideally prevent this for reads)
        llm_api_key_is_set = bool(llm_config_dict.pop('api_key', None) or self.llm_config.api_key)


        # Create a new LLMConfigSchema instance for the response, excluding the api_key
        # This ensures the response schema structure is met without exposing the key.
        response_llm_config = LLMConfigSchema(
            provider=self.llm_config.provider,
            model_name=self.llm_config.model_name,
            api_key=None, # Explicitly set to None for response
            temperature=self.llm_config.temperature,
            max_tokens=self.llm_config.max_tokens,
            custom_prompt_prefix=self.llm_config.custom_prompt_prefix
        )

        return ClientConfigurationResponseSchema(
            client_id=self.client_id,
            client_name=self.client_name,
            persona=self.persona,
            tone=self.tone,
            business_type=self.business_type,
            default_lang=self.default_lang,
            llm_config=response_llm_config, # Use the safe version
            history_max_messages=self.history_max_messages,
            is_active=self.is_active,
            has_client_secret=bool(self.client_secret_hashed),
            llm_api_key_is_set=llm_api_key_is_set,
            created_at=self.created_at,
            updated_at=self.updated_at
        )

from pydantic import BaseModel
from typing import Optional

class PromptBase(BaseModel):
    business_type: str
    prompt: str

class PromptCreate(PromptBase):
    pass

class PromptResponse(BaseModel):
    success: bool
    business_type: str
    # Optional: message: Optional[str] = None

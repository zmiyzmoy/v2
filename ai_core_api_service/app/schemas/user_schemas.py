from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from datetime import datetime

class UserBase(BaseModel):
    client_id: str
    user_id: str # Typically a phone number or platform-specific ID
    name: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None # For platform, source, etc.

class UserCreate(UserBase):
    # Potentially add fields that are only for creation, if any
    pass

class UserInDB(UserBase):
    # Fields that are definitely in the DB, like created_at, updated_at
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class UserResponse(BaseModel):
    success: bool
    user_id: str
    action: str # e.g., "created", "updated"
    # message: Optional[str] = None # Optional user-friendly message

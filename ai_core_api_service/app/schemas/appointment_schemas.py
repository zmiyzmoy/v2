from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class AppointmentBase(BaseModel):
    client_id: str
    user_id: str # Link to the user
    service: str # Or service_id, if you have a services collection
    date: datetime # Appointment date and time
    duration_minutes: Optional[int] = 60
    master: Optional[str] = None # Or master_id
    # Add other relevant fields like price, notes, etc.

class AppointmentCreate(AppointmentBase):
    # status: str = "pending" # Default status on creation if managed by API
    pass

class AppointmentInDB(AppointmentBase):
    appointment_id: str # Could be ObjectId as string
    status: str = "pending" # Default status
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class AppointmentResponse(BaseModel):
    success: bool
    appointment_id: str
    # message: Optional[str] = None

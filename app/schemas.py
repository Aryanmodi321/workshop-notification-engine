from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkshopCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    scheduled_at: datetime


class WorkshopRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    scheduled_at: datetime
    created_at: datetime
    status: str


class RegistrationCreate(BaseModel):
    member_id: str = Field(min_length=1, max_length=200)


class RegistrationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workshop_id: int
    member_id: str
    registered_at: datetime
    status: str


class NotificationJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    recipient: str
    status: str
    attempt_count: int
    created_at: datetime
    next_attempt_at: datetime
    sent_at: datetime | None
    last_error: str | None

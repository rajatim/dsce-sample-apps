from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator


def _serialize_date(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return value


class ApplicationBase(BaseModel):
    id: int
    applicant_name: str
    loan_type: str
    amount: float
    status: str
    submitted_date: str
    validation_comments: Optional[str] = None
    app_id_str: str

    @field_validator("submitted_date", mode="before")
    @classmethod
    def normalize_submitted_date(cls, value):
        return _serialize_date(value)

    @field_serializer("submitted_date")
    def serialize_submitted_date(self, value: str) -> str:
        return _serialize_date(value)

    @field_serializer("amount")
    def serialize_amount(self, value: float | Decimal) -> float:
        return float(value)


class Application(ApplicationBase):
    model_config = ConfigDict(from_attributes=True)


class UserBase(BaseModel):
    username: str


class UserCreate(UserBase):
    password: str
    firstName: str
    lastName: str
    dateOfBirth: str


class UserDetail(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    date_of_birth: str

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def normalize_date_of_birth(cls, value):
        return _serialize_date(value)

    @field_serializer("date_of_birth")
    def serialize_date_of_birth(self, value: str) -> str:
        return _serialize_date(value)


class User(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None

import re
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

class OrderCreate(BaseModel):
    numbers: List[int] = Field(..., min_length=1, max_length=100)
    buyer_name: str = Field(..., min_length=3, max_length=120)
    buyer_phone: str = Field(..., min_length=8, max_length=25)
    buyer_email: str = Field(..., min_length=5, max_length=120)
    payment_method: str = Field(..., pattern="^(flow|transfer)$")

    @field_validator("buyer_email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        clean = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean):
            raise ValueError("Ingresa un correo electrónico válido.")
        return clean

    @field_validator("numbers")
    @classmethod
    def validate_numbers_range(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("Debes seleccionar al menos un número.")
        unique_numbers = sorted(list(set(v)))
        for num in unique_numbers:
            if num < 1 or num > 100:
                raise ValueError(f"El número {num} está fuera de rango (1-100).")
        return unique_numbers

    @field_validator("buyer_name")
    @classmethod
    def validate_buyer_name(cls, v: str) -> str:
        parts = [p for p in v.strip().split() if p]
        if len(parts) < 2:
            raise ValueError("Por favor ingresa tu Nombre y Apellido completo.")
        return " ".join(parts)

    @field_validator("buyer_phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[^\d+]", "", v.strip())
        if len(cleaned) < 8:
            raise ValueError("Ingresa un número telefónico válido (ej: +56912345678).")
        return cleaned

class ManualSaleCreate(BaseModel):
    numbers: List[int] = Field(..., min_length=1, max_length=100)
    buyer_name: str = Field(..., min_length=3, max_length=120)
    buyer_phone: str = Field(..., min_length=8, max_length=25)
    buyer_email: Optional[str] = None

    @field_validator("numbers")
    @classmethod
    def validate_numbers_range(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("Debes seleccionar al menos un número.")
        unique_numbers = sorted(list(set(v)))
        for num in unique_numbers:
            if num < 1 or num > 100:
                raise ValueError(f"El número {num} está fuera de rango (1-100).")
        return unique_numbers

    @field_validator("buyer_name")
    @classmethod
    def validate_buyer_name(cls, v: str) -> str:
        parts = [p for p in v.strip().split() if p]
        if len(parts) < 2:
            raise ValueError("Debes ingresar nombre y apellido.")
        return " ".join(parts)

class PublicTicket(BaseModel):
    number: int
    status: str
    buyer_initials: Optional[str] = None
    reserved_until: Optional[str] = None

class PublicGridResponse(BaseModel):
    tickets: List[PublicTicket]
    total_tickets: int
    sold_count: int
    reserved_count: int
    available_count: int
    sold_percentage: float
    ticket_price: int

class OrderLookupResponse(BaseModel):
    id: str
    buyer_name: str
    buyer_initials: str
    buyer_phone: str
    buyer_email: str
    numbers_list: List[int]
    total_amount: int
    payment_method: str
    payment_status: str
    created_at: Optional[str] = None
    reserved_until: Optional[str] = None

class AdminMetrics(BaseModel):
    total_collected: int
    total_tickets: int
    sold_count: int
    sold_percentage: float
    reserved_count: int
    available_count: int
    ticket_price: int

class AdminLoginRequest(BaseModel):
    password: str

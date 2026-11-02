import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from database import Base

class Order(Base):
    __tablename__ = "orders"

    id = Column(String(36), primary_key=True, index=True)
    buyer_name = Column(String(150), nullable=False)
    buyer_initials = Column(String(20), nullable=False)
    buyer_phone = Column(String(50), nullable=False)
    buyer_email = Column(String(150), nullable=False)
    numbers_list = Column(JSON, nullable=False)
    total_amount = Column(Integer, nullable=False)
    payment_method = Column(String(30), nullable=False)  # flow, transfer, manual_whatsapp
    payment_status = Column(String(30), nullable=False, default="pending")  # pending, paid, expired, cancelled
    flow_token = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    tickets = relationship("Ticket", back_populates="order")

    def to_dict(self):
        return {
            "id": self.id,
            "buyer_name": self.buyer_name,
            "buyer_initials": self.buyer_initials,
            "buyer_phone": self.buyer_phone,
            "buyer_email": self.buyer_email,
            "numbers_list": self.numbers_list,
            "total_amount": self.total_amount,
            "payment_method": self.payment_method,
            "payment_status": self.payment_status,
            "flow_token": self.flow_token,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

class Ticket(Base):
    __tablename__ = "tickets"

    number = Column(Integer, primary_key=True, index=True)
    status = Column(String(20), nullable=False, default="available")  # available, reserved, sold
    reserved_until = Column(DateTime, nullable=True)
    order_id = Column(String(36), ForeignKey("orders.id"), nullable=True)

    order = relationship("Order", back_populates="tickets")

    def to_public_dict(self):
        """Diccionario público: NO expone datos privados como teléfono o email."""
        initials = self.order.buyer_initials if self.order and self.status == "sold" else None
        return {
            "number": self.number,
            "status": self.status,
            "buyer_initials": initials,
            "reserved_until": self.reserved_until.isoformat() if self.reserved_until else None
        }

    def to_admin_dict(self):
        """Diccionario completo exclusivo para el panel de administración."""
        return {
            "number": self.number,
            "status": self.status,
            "reserved_until": self.reserved_until.isoformat() if self.reserved_until else None,
            "order_id": self.order_id,
            "buyer_name": self.order.buyer_name if self.order else None,
            "buyer_initials": self.order.buyer_initials if self.order else None,
            "buyer_phone": self.order.buyer_phone if self.order else None,
            "buyer_email": self.order.buyer_email if self.order else None,
            "payment_method": self.order.payment_method if self.order else None,
            "payment_status": self.order.payment_status if self.order else None,
        }

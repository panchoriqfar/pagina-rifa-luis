import os
import hmac
import hashlib
import random
import string
import datetime
import requests
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, or_, func
from fastapi import HTTPException, status
from dotenv import load_dotenv

from models import Ticket, Order
from schemas import OrderCreate, ManualSaleCreate

load_dotenv()

TICKET_PRICE = int(os.getenv("TICKET_PRICE", 2000))
TOTAL_TICKETS = int(os.getenv("TOTAL_TICKETS", 100))
FLOW_API_KEY = os.getenv("FLOW_API_KEY", "").strip()
FLOW_SECRET_KEY = os.getenv("FLOW_SECRET_KEY", "").strip()
FLOW_URL = os.getenv("FLOW_URL", "https://www.flow.cl/api").rstrip("/")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "Rifa Solidaria <onboarding@resend.dev>").strip()
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER", "56927178289").strip()
DRAW_DATE = os.getenv("DRAW_DATE", "10 de diciembre de 2026")

def generate_order_id() -> str:
    """Genera un código de orden corto y legible, ej. R-7K3B8Z"""
    chars = string.ascii_uppercase + string.digits
    code = ''.join(random.choices(chars, k=6))
    return f"R-{code}"

def extract_initials(full_name: str) -> str:
    """Extrae dinámicamente las iniciales reales de cada comprador según su nombre y apellido."""
    ignore = {"de", "del", "la", "las", "los", "y", "san", "santa"}
    raw_parts = [p.strip() for p in full_name.strip().split() if p.strip()]
    parts = [p for p in raw_parts if p.lower() not in ignore] or raw_parts
    if not parts:
        return "?."
    if len(parts) == 1:
        return f"{parts[0][0].upper()}."
    return f"{parts[0][0].upper()}. {parts[-1][0].upper() if len(parts) == 2 else parts[1][0].upper()}."

def init_db_tickets(db: Session):
    """Crea los 100 números (1 al 100) si la base de datos está vacía."""
    count = db.query(Ticket).count()
    if count < TOTAL_TICKETS:
        existing_numbers = set(row[0] for row in db.query(Ticket.number).all())
        new_tickets = []
        for n in range(1, TOTAL_TICKETS + 1):
            if n not in existing_numbers:
                new_tickets.append(Ticket(number=n, status="available", reserved_until=None, order_id=None))
        if new_tickets:
            db.add_all(new_tickets)
            db.commit()
            print(f"[DB] Se inicializaron {len(new_tickets)} tickets en la base de datos.")

def sync_flow_order_status(db: Session, order: Order) -> str:
    """
    Consulta directamente a Flow.cl el estado real de una orden con flow_token.
    - status == 2 (Pagada): confirma el pago y asigna los tickets como vendidos.
    - status in (3, 4) (Rechazada / Anulada): libera los tickets reservados de inmediato.
    """
    if not order or not order.flow_token or not FLOW_API_KEY or not FLOW_SECRET_KEY:
        return order.payment_status if order else "unknown"
    if order.payment_status == "paid":
        return "paid"

    try:
        params = {"apiKey": FLOW_API_KEY, "token": order.flow_token}
        params["s"] = sign_flow_params(params, FLOW_SECRET_KEY)
        resp = requests.get(f"{FLOW_URL}/payment/getStatus", params=params, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            flow_status = data.get("status")
            if flow_status == 2:
                confirm_order_paid(db, order)
                return "paid"
            elif flow_status in (3, 4):
                release_order_tickets(db, order.id)
                return "cancelled"
    except Exception as e:
        print(f"[Flow Sync Error] Orden {order.id}: {e}")

    return order.payment_status

def release_expired_tickets(db: Session) -> int:
    """
    Libera tickets cuyo tiempo de reserva ha expirado y marca órdenes pendientes como expired.
    Antes de expirar una orden Flow con token activo, verifica en Flow si fue pagada.
    """
    now = datetime.datetime.utcnow()
    expired_tickets = db.query(Ticket).filter(
        Ticket.status == "reserved",
        Ticket.reserved_until != None,
        Ticket.reserved_until < now
    ).all()

    if not expired_tickets:
        return 0

    order_ids = set(t.order_id for t in expired_tickets if t.order_id)
    paid_order_ids = set()

    if order_ids:
        orders = db.query(Order).filter(
            Order.id.in_(order_ids),
            Order.payment_status == "pending"
        ).all()
        for o in orders:
            if o.payment_method == "flow" and o.flow_token:
                new_status = sync_flow_order_status(db, o)
                if new_status == "paid":
                    paid_order_ids.add(o.id)
                    continue
            o.payment_status = "expired"

    released_count = 0
    for t in expired_tickets:
        if t.order_id in paid_order_ids:
            continue
        t.status = "available"
        t.reserved_until = None
        t.order_id = None
        released_count += 1

    db.commit()
    return released_count

def get_public_grid(db: Session):
    """Devuelve la lista pública de 100 números sin datos sensibles."""
    release_expired_tickets(db)
    tickets = db.query(Ticket).order_by(Ticket.number.asc()).all()
    
    sold_count = sum(1 for t in tickets if t.status == "sold")
    reserved_count = sum(1 for t in tickets if t.status == "reserved")
    available_count = sum(1 for t in tickets if t.status == "available")
    sold_percentage = round((sold_count / TOTAL_TICKETS) * 100, 1)

    tickets_data = [t.to_public_dict() for t in tickets]
    return {
        "tickets": tickets_data,
        "total_tickets": TOTAL_TICKETS,
        "sold_count": sold_count,
        "reserved_count": reserved_count,
        "available_count": available_count,
        "sold_percentage": sold_percentage,
        "ticket_price": TICKET_PRICE
    }

def sign_flow_params(params: dict, secret_key: str) -> str:
    """
    Firma obligatoria Flow HMAC-SHA256:
    Ordena llaves alfabéticamente, concatena key+value y genera el digest hexadecimal.
    """
    sorted_keys = sorted(params.keys())
    to_sign = "".join(f"{k}{params[k]}" for k in sorted_keys)
    signature = hmac.new(
        secret_key.encode("utf-8"),
        to_sign.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return signature

def create_order(db: Session, order_data: OrderCreate, base_url: str) -> dict:
    """
    Crea una orden con control de concurrencia y doble tiempo de reserva:
    - Flow: 10 minutos
    - Transferencia: 30 minutos
    """
    release_expired_tickets(db)
    requested_numbers = sorted(list(set(order_data.numbers)))

    # Bloqueo con with_for_update() en PostgreSQL para prevenir race conditions
    query = db.query(Ticket).filter(Ticket.number.in_(requested_numbers))
    if db.bind.dialect.name != "sqlite":
        query = query.with_for_update()
    
    locked_tickets = query.all()
    if len(locked_tickets) != len(requested_numbers):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uno o más números seleccionados no existen en el sistema."
        )

    # Verificar disponibilidad
    unavailable = [t.number for t in locked_tickets if t.status != "available"]
    if unavailable:
        unavailable_str = ", ".join(f"#{n:02d}" for n in unavailable)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Los siguientes números ya no están disponibles: {unavailable_str}. Por favor elige otros."
        )

    now = datetime.datetime.utcnow()
    # Tiempos de reserva
    if order_data.payment_method == "flow":
        reservation_minutes = 10
    else:  # transfer
        reservation_minutes = 30

    reserved_until = now + datetime.timedelta(minutes=reservation_minutes)
    order_id = generate_order_id()
    total_amount = len(requested_numbers) * TICKET_PRICE
    initials = extract_initials(order_data.buyer_name)

    order = Order(
        id=order_id,
        buyer_name=order_data.buyer_name,
        buyer_initials=initials,
        buyer_phone=order_data.buyer_phone,
        buyer_email=order_data.buyer_email,
        numbers_list=requested_numbers,
        total_amount=total_amount,
        payment_method=order_data.payment_method,
        payment_status="pending",
        flow_token=None,
        created_at=now,
        updated_at=now
    )
    db.add(order)

    # Reservar tickets
    for t in locked_tickets:
        t.status = "reserved"
        t.reserved_until = reserved_until
        t.order_id = order_id

    db.commit()
    db.refresh(order)

    # Procesar Flow si corresponde
    redirect_url = None
    if order_data.payment_method == "flow":
        effective_base = "http://localhost:8000" if "testserver" in base_url else base_url
        if FLOW_API_KEY and FLOW_SECRET_KEY and FLOW_API_KEY.lower() != "mock":
            # Llamada real a Flow.cl
            try:
                numbers_label = ", ".join(f"#{n:02d}" for n in requested_numbers)
                flow_params = {
                    "apiKey": FLOW_API_KEY,
                    "commerceOrder": order.id,
                    "subject": f"Rifa Solidaria Luis ({numbers_label}) - Orden {order.id}",
                    "currency": "CLP",
                    "amount": str(order.total_amount),
                    "email": order.buyer_email,
                    "urlConfirmation": f"{effective_base}/api/payments/flow/webhook",
                    "urlReturn": f"{effective_base}/api/payments/flow/return",
                }
                signature = sign_flow_params(flow_params, FLOW_SECRET_KEY)
                flow_params["s"] = signature

                resp = requests.post(f"{FLOW_URL}/payment/create", data=flow_params, timeout=12)
                if resp.status_code == 200:
                    flow_data = resp.json()
                    order.flow_token = flow_data.get("token")
                    db.commit()
                    db.refresh(order)
                    redirect_url = f"{flow_data.get('url')}?token={flow_data.get('token')}"
                else:
                    print(f"[Flow Error] HTTP {resp.status_code}: {resp.text}")
                    redirect_url = f"{base_url}/flow-checkout-simulation?order_id={order.id}"
            except Exception as e:
                print(f"[Flow Exception]: {e}")
                redirect_url = f"{base_url}/flow-checkout-simulation?order_id={order.id}"
        else:
            # Modo Simulación integrado
            redirect_url = f"{base_url}/flow-checkout-simulation?order_id={order.id}"

    return {
        "order": order.to_dict(),
        "reserved_until": reserved_until.isoformat(),
        "redirect_url": redirect_url
    }

def confirm_order_paid(db: Session, order: Order) -> bool:
    """Marca la orden y sus tickets como pagados y envía comprobante por email."""
    if order.payment_status == "paid":
        return True

    order.payment_status = "paid"
    order.updated_at = datetime.datetime.utcnow()

    # Bloquear y actualizar tickets
    tickets = db.query(Ticket).filter(Ticket.number.in_(order.numbers_list)).all()
    for t in tickets:
        t.status = "sold"
        t.reserved_until = None
        t.order_id = order.id

    db.commit()

    # Enviar correo de confirmación
    send_receipt_email(order)
    return True

def approve_transfer_order(db: Session, order_id: str) -> dict:
    """Aprobación manual de transferencia desde el panel de administración."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada.")

    # Verificar si los números aún están asignados o siguen libres
    tickets = db.query(Ticket).filter(Ticket.number.in_(order.numbers_list)).all()
    for t in tickets:
        if t.status == "sold" and t.order_id != order.id:
            raise HTTPException(
                status_code=400,
                detail=f"El número #{t.number:02d} ya fue vendido en otra orden posterior."
            )

    confirm_order_paid(db, order)
    return {"success": True, "message": f"Orden {order.id} aprobada con éxito."}

def release_order_tickets(db: Session, order_id: str) -> dict:
    """Libera inmediatamente los números reservados de una orden."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada.")

    order.payment_status = "cancelled"
    order.updated_at = datetime.datetime.utcnow()

    tickets = db.query(Ticket).filter(Ticket.order_id == order_id).all()
    for t in tickets:
        if t.status != "sold":
            t.status = "available"
            t.reserved_until = None
            t.order_id = None

    db.commit()
    return {"success": True, "message": f"Números de la orden {order_id} liberados exitosamente."}

def create_manual_sale(db: Session, sale_data: ManualSaleCreate) -> dict:
    """Venta directa desde el panel de administración (ej. pago presencial o WhatsApp)."""
    release_expired_tickets(db)
    numbers = sorted(list(set(sale_data.numbers)))

    tickets = db.query(Ticket).filter(Ticket.number.in_(numbers)).all()
    unavailable = [t.number for t in tickets if t.status != "available"]
    if unavailable:
        unavailable_str = ", ".join(f"#{n:02d}" for n in unavailable)
        raise HTTPException(
            status_code=400,
            detail=f"Los números {unavailable_str} ya no están disponibles."
        )

    order_id = generate_order_id()
    now = datetime.datetime.utcnow()
    initials = extract_initials(sale_data.buyer_name)
    total_amount = len(numbers) * TICKET_PRICE

    order = Order(
        id=order_id,
        buyer_name=sale_data.buyer_name,
        buyer_initials=initials,
        buyer_phone=sale_data.buyer_phone,
        buyer_email=sale_data.buyer_email or f"manual_{order_id}@rifasolidaria.cl",
        numbers_list=numbers,
        total_amount=total_amount,
        payment_method="manual_whatsapp",
        payment_status="paid",
        created_at=now,
        updated_at=now
    )
    db.add(order)

    for t in tickets:
        t.status = "sold"
        t.reserved_until = None
        t.order_id = order_id

    db.commit()
    db.refresh(order)

    if sale_data.buyer_email:
        send_receipt_email(order)

    return {"success": True, "order": order.to_dict()}

def send_receipt_email(order: Order):
    """
    Envía comprobante digital por email vía Resend.
    Si RESEND_API_KEY no está configurada, registra la acción sin arrojar excepción.
    """
    if not order.buyer_email or "@" not in order.buyer_email:
        return

    numbers_formatted = ", ".join(f"#{n:02d}" for n in sorted(order.numbers_list))
    total_formatted = f"${order.total_amount:,.0f}".replace(",", ".")

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Comprobante de Participación - Rifa Solidaria</title>
      <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; }}
        .card {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 16px; padding: 32px; border: 1px solid #e2e8f0; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
        .badge {{ display: inline-block; padding: 6px 14px; background: #dcfce7; color: #166534; font-weight: bold; border-radius: 9999px; font-size: 13px; }}
        .numbers-box {{ background: #eff6ff; border: 2px dashed #3b82f6; border-radius: 12px; padding: 18px; text-align: center; margin: 24px 0; }}
        .numbers-title {{ font-size: 13px; color: #1d4ed8; font-weight: bold; text-transform: uppercase; letter-spacing: 0.05em; }}
        .numbers-list {{ font-size: 26px; color: #1e3a8a; font-weight: 800; margin-top: 6px; letter-spacing: 2px; }}
        .info-row {{ display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #f1f5f9; font-size: 14px; color: #475569; }}
        .info-label {{ font-weight: 600; color: #334155; }}
        .prizes {{ background: #fffbeb; border-left: 4px solid #f59e0b; padding: 14px 16px; border-radius: 8px; margin: 20px 0; font-size: 13px; color: #92400e; }}
        .footer {{ text-align: center; font-size: 12px; color: #94a3b8; margin-top: 24px; line-height: 1.5; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div style="text-align: center; margin-bottom: 20px;">
          <span class="badge">✓ PAGO CONFIRMADO</span>
          <h2 style="color: #0f172a; margin: 12px 0 4px;">Rifa Solidaria Luis Henríquez</h2>
          <p style="color: #64748b; font-size: 14px; margin: 0;">¡Muchas gracias por tu apoyo solidario!</p>
        </div>

        <div class="numbers-box">
          <div class="numbers-title">Tus Números Oficiales Asignados</div>
          <div class="numbers-list">{numbers_formatted}</div>
        </div>

        <div style="margin: 20px 0;">
          <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
            <tr style="border-bottom: 1px solid #f1f5f9;">
              <td style="padding: 8px 0; color: #64748b;">N° Orden:</td>
              <td style="padding: 8px 0; text-align: right; font-weight: 700; color: #0f172a;">{order.id}</td>
            </tr>
            <tr style="border-bottom: 1px solid #f1f5f9;">
              <td style="padding: 8px 0; color: #64748b;">Comprador:</td>
              <td style="padding: 8px 0; text-align: right; font-weight: 600; color: #0f172a;">{order.buyer_name} ({order.buyer_initials})</td>
            </tr>
            <tr style="border-bottom: 1px solid #f1f5f9;">
              <td style="padding: 8px 0; color: #64748b;">Monto Pagado:</td>
              <td style="padding: 8px 0; text-align: right; font-weight: 700; color: #16a34a;">{total_formatted} CLP</td>
            </tr>
            <tr style="border-bottom: 1px solid #f1f5f9;">
              <td style="padding: 8px 0; color: #64748b;">Medio de Pago:</td>
              <td style="padding: 8px 0; text-align: right; text-transform: uppercase; font-weight: 600; color: #0f172a;">{order.payment_method}</td>
            </tr>
            <tr>
              <td style="padding: 8px 0; color: #64748b;">Fecha Sorteo:</td>
              <td style="padding: 8px 0; text-align: right; font-weight: 600; color: #0f172a;">{DRAW_DATE} (o al vender 100%)</td>
            </tr>
          </table>
        </div>

        <div class="prizes">
          <strong>🎁 Premios:</strong><br>
          • Alisador de Pelo Elegance Chía + Secador de Pelo Chía marca GAMA.<br>
          • Tostador de pan marca Ursus Trotter.
        </div>

        <div class="footer">
          Conserva este comprobante digital. El sorteo será transmitido en vivo con plataforma certificada.<br>
          WhatsApp de consultas: <strong>+{WHATSAPP_NUMBER}</strong>
        </div>
      </div>
    </body>
    </html>
    """

    if not RESEND_API_KEY:
        print(f"[Resend MOCK] Correo enviado a {order.buyer_email} para la orden {order.id} con números: {numbers_formatted}")
        return

    try:
        headers = {
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "from": RESEND_FROM_EMAIL,
            "to": [order.buyer_email],
            "subject": f"Comprobante Rifa Solidaria Luis Henríquez - Orden #{order.id}",
            "html": html_content
        }
        resp = requests.post("https://api.resend.com/emails", json=payload, headers=headers, timeout=10)
        if resp.status_code in (200, 201):
            print(f"[Resend SUCCESS] Comprobante enviado a {order.buyer_email}")
        else:
            print(f"[Resend ERROR] {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[Resend EXCEPTION] Error enviando correo: {e}")

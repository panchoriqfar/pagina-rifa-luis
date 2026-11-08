import os
import csv
import io
import datetime
from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Request, Response, status, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import or_
from dotenv import load_dotenv
import requests

from database import engine, Base, get_db, SessionLocal
from models import Ticket, Order
from schemas import (
    OrderCreate,
    ManualSaleCreate,
    PublicGridResponse,
    AdminMetrics,
    AdminLoginRequest
)
from services import (
    init_db_tickets,
    release_expired_tickets,
    sync_flow_order_status,
    get_public_grid,
    create_order,
    confirm_order_paid,
    approve_transfer_order,
    release_order_tickets,
    create_manual_sale,
    sign_flow_params,
    FLOW_API_KEY,
    FLOW_SECRET_KEY,
    FLOW_URL,
    TICKET_PRICE,
    TOTAL_TICKETS,
    WHATSAPP_NUMBER,
    DRAW_DATE
)

load_dotenv()

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "RifaLuis2026!")
BANK_BENEFICIARY_NAME = os.getenv("BANK_BENEFICIARY_NAME", "FRANCISCO ANDRES RIQUELME FARIAS")
BANK_BENEFICIARY_RUT = os.getenv("BANK_BENEFICIARY_RUT", "18.240.046-7")
BANK_NAME = os.getenv("BANK_NAME", "Banco Estado")
BANK_ACCOUNT_TYPE = os.getenv("BANK_ACCOUNT_TYPE", "CuentaRUT")
BANK_ACCOUNT_NUMBER = os.getenv("BANK_ACCOUNT_NUMBER", "18240046")
APP_URL = os.getenv("APP_URL", "http://localhost:8000").rstrip("/")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicialización de tablas y tickets 1-150
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        init_db_tickets(db)
    finally:
        db.close()
    yield

app = FastAPI(
    title="Gran Rifa Solidaria Luis Henríquez",
    description="Sistema web completo para Rifa Solidaria con Flow.cl, Transferencia y Panel Admin",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir archivos estáticos y plantillas
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

# ==========================================
# SEGURIDAD PANEL ADMIN
# ==========================================
def verify_admin(request: Request) -> bool:
    token = request.cookies.get("admin_session") or request.headers.get("x-admin-token")
    return token == ADMIN_PASSWORD

def require_admin(request: Request):
    if not verify_admin(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Acceso no autorizado. Inicia sesión como administrador."
        )
    return True

# ==========================================
# VISTAS PÚBLICAS Y HEALTHCHECK (RENDER)
# ==========================================
@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "rifa-solidaria-luis"}

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    grid = get_public_grid(db)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "grid": grid,
            "ticket_price": TICKET_PRICE,
            "total_tickets": TOTAL_TICKETS,
            "whatsapp_number": WHATSAPP_NUMBER,
            "draw_date": DRAW_DATE,
            "bank_info": {
                "name": BANK_BENEFICIARY_NAME,
                "rut": BANK_BENEFICIARY_RUT,
                "bank": BANK_NAME,
                "account_type": BANK_ACCOUNT_TYPE,
                "account_number": BANK_ACCOUNT_NUMBER
            }
        }
    )

@app.get("/api/tickets", response_model=PublicGridResponse)
async def get_tickets(db: Session = Depends(get_db)):
    """Retorna la grilla de tickets con datos públicos (solo iniciales en vendidos)."""
    return get_public_grid(db)

@app.post("/api/orders")
async def create_new_order(order_data: OrderCreate, request: Request, db: Session = Depends(get_db)):
    """Crea una orden con reserva temporal (Flow 10m / Transferencia 30m)."""
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if forwarded_proto and forwarded_host:
        base_url = f"{forwarded_proto}://{forwarded_host}".rstrip("/")
    else:
        base_url = str(request.base_url).rstrip("/")
    result = create_order(db, order_data, base_url)
    return result

@app.get("/api/orders/search")
async def search_my_numbers(q: str, db: Session = Depends(get_db)):
    """Busca números asociados a un correo o teléfono."""
    release_expired_tickets(db)
    clean_q = q.strip().lower()
    orders = db.query(Order).filter(
        or_(
            Order.buyer_email.ilike(f"%{clean_q}%"),
            Order.buyer_phone.ilike(f"%{clean_q}%"),
            Order.id.ilike(f"%{clean_q}%")
        )
    ).order_by(Order.created_at.desc()).all()

    for o in orders:
        if o.payment_method == "flow" and o.payment_status == "pending" and o.flow_token:
            sync_flow_order_status(db, o)

    return {"results": [o.to_dict() for o in orders]}

@app.get("/api/orders/{order_id}")
async def get_order_status(order_id: str, db: Session = Depends(get_db)):
    """Obtiene el estado de una orden específica (usado para comprobantes y polling)."""
    release_expired_tickets(db)
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")

    if order.payment_method == "flow" and order.payment_status == "pending" and order.flow_token:
        sync_flow_order_status(db, order)
        db.refresh(order)

    # Obtener el tiempo de reserva del ticket si sigue pendiente
    reserved_until = None
    if order.tickets and order.payment_status == "pending":
        first_ticket = order.tickets[0]
        if first_ticket.reserved_until:
            reserved_until = first_ticket.reserved_until.isoformat()

    return {
        "order": order.to_dict(),
        "reserved_until": reserved_until
    }

# ==========================================
# FLUJO DE PAGO FLOW.CL + MOCK (SOLO SI FLOW_API_KEY == 'mock')
# ==========================================
@app.get("/flow-checkout-simulation", response_class=HTMLResponse)
async def flow_simulation(request: Request, order_id: str, db: Session = Depends(get_db)):
    """Pantalla simulada de Flow deshabilitada en producción."""
    if FLOW_API_KEY.lower() != "mock":
        raise HTTPException(status_code=403, detail="El simulador de pagos está deshabilitado en producción.")
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    return templates.TemplateResponse(
        request=request,
        name="flow_mock.html",
        context={
            "request": request,
            "order": order,
            "ticket_price": TICKET_PRICE
        }
    )

@app.post("/api/mock-flow/confirm")
async def mock_flow_confirm(order_id: str = Form(...), action: str = Form(...), db: Session = Depends(get_db)):
    """Procesa el resultado del simulador de Flow (solo permitido en modo mock)."""
    if FLOW_API_KEY.lower() != "mock":
        raise HTTPException(status_code=403, detail="El simulador de pagos está deshabilitado en producción.")
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")

    if action == "pay":
        confirm_order_paid(db, order)
        return RedirectResponse(url=f"/?order_id={order.id}&flow_success=1", status_code=303)
    else:
        order.payment_status = "cancelled"
        release_order_tickets(db, order.id)
        return RedirectResponse(url=f"/?order_id={order.id}&flow_cancelled=1", status_code=303)

@app.post("/api/payments/flow/webhook")
async def flow_webhook(request: Request, db: Session = Depends(get_db)):
    """Webhook oficial de Flow.cl al completarse un pago."""
    try:
        form_data = await request.form()
        token = form_data.get("token")
        if not token:
            return JSONResponse(status_code=400, content={"error": "Falta token de pago"})

        # Consultar estado en Flow
        params = {"apiKey": FLOW_API_KEY, "token": token}
        signature = sign_flow_params(params, FLOW_SECRET_KEY)
        params["s"] = signature

        resp = requests.get(f"{FLOW_URL}/payment/getStatus", params=params, timeout=10)
        if resp.status_code == 200:
            status_data = resp.json()
            # status == 2 significa Pagado en Flow; 3 o 4 significa Rechazado / Anulado
            commerce_order = status_data.get("commerceOrder")
            flow_status = status_data.get("status")
            if commerce_order:
                order = db.query(Order).filter(Order.id == commerce_order).first()
                if order:
                    if flow_status == 2:
                        confirm_order_paid(db, order)
                        return JSONResponse(content={"status": "OK"})
                    elif flow_status in (3, 4):
                        release_order_tickets(db, commerce_order)
                        return JSONResponse(content={"status": "CANCELLED"})
    except Exception as e:
        print(f"[Flow Webhook Error]: {e}")
    return JSONResponse(content={"status": "RECEIVED"})

@app.api_route("/api/payments/flow/return", methods=["GET", "POST"])
async def flow_return(request: Request, db: Session = Depends(get_db)):
    """Retorno del usuario desde Flow hacia la aplicación."""
    token = None
    if request.method == "POST":
        form_data = await request.form()
        token = form_data.get("token")
    else:
        token = request.query_params.get("token")

    if token and FLOW_API_KEY and FLOW_SECRET_KEY:
        try:
            params = {"apiKey": FLOW_API_KEY, "token": token}
            params["s"] = sign_flow_params(params, FLOW_SECRET_KEY)
            resp = requests.get(f"{FLOW_URL}/payment/getStatus", params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                commerce_order = data.get("commerceOrder")
                flow_status = data.get("status")
                if flow_status == 2:
                    order = db.query(Order).filter(Order.id == commerce_order).first()
                    if order:
                        confirm_order_paid(db, order)
                        return RedirectResponse(url=f"/?order_id={commerce_order}&flow_success=1", status_code=303)
                else:
                    if commerce_order and flow_status in (3, 4):
                        release_order_tickets(db, commerce_order)
                    return RedirectResponse(url=f"/?order_id={commerce_order}&flow_cancelled=1", status_code=303)
        except Exception as e:
            print(f"[Flow Return Error]: {e}")

    return RedirectResponse(url="/", status_code=303)

# ==========================================
# PANEL DE ADMINISTRACIÓN (/admin)
# ==========================================
@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, db: Session = Depends(get_db)):
    """Panel de administración protegido por contraseña."""
    is_authenticated = verify_admin(request)
    init_db_tickets(db)
    release_expired_tickets(db)

    metrics = None
    tickets = []
    orders = []

    if is_authenticated:
        all_tickets = db.query(Ticket).order_by(Ticket.number.asc()).all()
        sold = sum(1 for t in all_tickets if t.status == "sold")
        reserved = sum(1 for t in all_tickets if t.status == "reserved")
        available = sum(1 for t in all_tickets if t.status == "available")
        total_collected = sold * TICKET_PRICE

        metrics = {
            "total_collected": total_collected,
            "total_tickets": TOTAL_TICKETS,
            "sold_count": sold,
            "reserved_count": reserved,
            "available_count": available,
            "sold_percentage": round((sold / TOTAL_TICKETS) * 100, 1),
            "ticket_price": TICKET_PRICE
        }

        tickets = [t.to_admin_dict() for t in all_tickets]
        # Órdenes pendientes o recientes
        db_orders = db.query(Order).order_by(Order.created_at.desc()).all()
        orders = [o.to_dict() for o in db_orders]

    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "request": request,
            "is_authenticated": is_authenticated,
            "metrics": metrics,
            "tickets": tickets,
            "orders": orders,
            "whatsapp_number": WHATSAPP_NUMBER,
            "ticket_price": TICKET_PRICE,
            "draw_date": DRAW_DATE
        }
    )

@app.post("/api/admin/login")
async def admin_login(payload: AdminLoginRequest, response: Response):
    if payload.password == ADMIN_PASSWORD:
        response.set_cookie(
            key="admin_session",
            value=ADMIN_PASSWORD,
            httponly=True,
            samesite="lax",
            max_age=86400 * 7
        )
        return {"success": True, "message": "Inicio de sesión exitoso"}
    raise HTTPException(status_code=401, detail="Contraseña incorrecta")

@app.post("/api/admin/logout")
async def admin_logout(response: Response):
    response.delete_cookie("admin_session")
    return {"success": True, "message": "Sesión cerrada"}

@app.get("/api/admin/data")
async def get_admin_data(request: Request, db: Session = Depends(get_db)):
    """Datos en vivo para el panel de administración."""
    require_admin(request)
    release_expired_tickets(db)

    all_tickets = db.query(Ticket).order_by(Ticket.number.asc()).all()
    sold = sum(1 for t in all_tickets if t.status == "sold")
    reserved = sum(1 for t in all_tickets if t.status == "reserved")
    available = sum(1 for t in all_tickets if t.status == "available")
    total_collected = sold * TICKET_PRICE

    metrics = {
        "total_collected": total_collected,
        "total_tickets": TOTAL_TICKETS,
        "sold_count": sold,
        "reserved_count": reserved,
        "available_count": available,
        "sold_percentage": round((sold / TOTAL_TICKETS) * 100, 1),
        "ticket_price": TICKET_PRICE
    }

    db_orders = db.query(Order).order_by(Order.created_at.desc()).all()

    return {
        "metrics": metrics,
        "tickets": [t.to_admin_dict() for t in all_tickets],
        "orders": [o.to_dict() for o in db_orders]
    }

@app.post("/api/admin/orders/{order_id}/approve")
async def admin_approve_order(order_id: str, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    return approve_transfer_order(db, order_id)

@app.post("/api/admin/orders/{order_id}/release")
async def admin_release_order(order_id: str, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    return release_order_tickets(db, order_id)

@app.post("/api/admin/orders/{order_id}/sync-flow")
async def admin_sync_flow_order(order_id: str, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Orden no encontrada")
    new_status = sync_flow_order_status(db, order)
    return {"success": True, "payment_status": new_status, "order_id": order.id}

@app.post("/api/admin/manual-sale")
async def admin_manual_sale(sale_data: ManualSaleCreate, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    return create_manual_sale(db, sale_data)

@app.get("/api/admin/export-csv")
async def export_tickets_csv(request: Request, db: Session = Depends(get_db)):
    """Exporta los 150 números a un archivo CSV listo para el sorteo."""
    require_admin(request)
    release_expired_tickets(db)

    tickets = db.query(Ticket).order_by(Ticket.number.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Numero",
        "Estado",
        "Comprador",
        "Iniciales",
        "Telefono",
        "Email",
        "Medio_Pago",
        "ID_Orden",
        "Fecha_Compra"
    ])

    for t in tickets:
        order = t.order
        writer.writerow([
            f"{t.number:02d}",
            t.status.upper(),
            order.buyer_name if order else "",
            order.buyer_initials if order else "",
            order.buyer_phone if order else "",
            order.buyer_email if order else "",
            order.payment_method.upper() if order else "",
            order.id if order else "",
            order.created_at.strftime("%Y-%m-%d %H:%M") if order and order.created_at else ""
        ])

    output.seek(0)
    filename = f"sorteo_rifa_luis_{datetime.date.today().isoformat()}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

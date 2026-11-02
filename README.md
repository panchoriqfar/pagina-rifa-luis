# 🎟️ Gran Rifa Solidaria Luis Henríquez

Aplicación web completa, moderna y lista para producción diseñada para la recaudación de fondos y rifa solidaria a beneficio de **Luis Henríquez**.

---

## 🌟 Características Principales

1. **Gestión de 100 Números (01 al 100):**
   - Grilla interactiva responsiva (10 columnas en PC, 5 en móviles).
   - Estados en tiempo real: `Libre`, `Tuyo`, `Reservado` y `Vendido`.
   - **Privacidad estricta:** La grilla pública solo muestra las iniciales del comprador (ej: `F. R.`). Nunca expone correo, teléfono ni nombre completo.
   - Barra de progreso animada con porcentaje de venta.
   - Polling en vivo cada 10 segundos para actualizar la disponibilidad sin recargar la página.

2. **Doble Medio de Pago y Control de Tiempos:**
   - **Flow.cl:** Reserva de números por **10 minutos**. Firma criptográfica HMAC-SHA256 y simulador visual local integrado para pruebas sin llaves.
   - **Transferencia Bancaria Manual:** Bloqueo temporal por **30 minutos** con **temporizador regresivo en vivo**. CuentaRUT preconfigurada para Francisco Riquelme, botón para copiar datos y enlace directo a WhatsApp con mensaje prellenado.

3. **Prevención de Carreras y Liberación Automática:**
   - Limpieza automática de tickets vencidos antes de consultar o reservar.
   - Transacciones seguras con bloqueo de concurrencia (`with_for_update`).

4. **Panel de Administración (`/admin`):**
   - Protegido por contraseña (`ADMIN_PASSWORD`).
   - Métricas en tiempo real: recaudación en CLP, avance, números libres, reservados y vendidos.
   - Validación de transferencias con enlaces directos a WhatsApp de cada comprador.
   - Aprobación de pago con 1 clic (marca vendido y dispara el comprobante).
   - Venta manual directa (para registrar pagos en efectivo o por WhatsApp).
   - Tabla maestra de los 100 números con buscador.
   - **Exportación a CSV / Excel** para la tómbola del sorteo en vivo.

5. **Correos Transaccionales con Resend:**
   - Envío automático de comprobante digital en HTML al aprobarse el pago.

---

## 🛠️ Stack Tecnológico

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (ORM), Pydantic v2.
- **Base de Datos:** PostgreSQL en **Neon.tech** (con soporte SSL) o **SQLite** local por defecto para desarrollo instantáneo sin configuración previa.
- **Frontend:** Jinja2 Templates, HTML5, Tailwind CSS, JavaScript Vanilla moderno.
- **Pasarela:** Flow.cl API REST + Simulador Mock.
- **Email:** Resend API.

---

## 🚀 Instalación y Puesta en Marcha

### 1. Clonar o ingresar a la carpeta del proyecto
```bash
cd "C:\Users\admin\Desktop\pagina-rifa-luis"
```

### 2. Crear y activar un entorno virtual de Python
```bash
python -m venv venv
# En Windows PowerShell:
.\venv\Scripts\Activate.ps1
```

### 3. Instalar las dependencias
```bash
pip install -r requirements.txt
```

### 4. Configurar variables de entorno (`.env`)
El proyecto ya cuenta con un archivo `.env` funcional con valores por defecto. Si deseas conectar **Neon.tech**, **Flow** o **Resend**, solo edita el `.env`:

```env
# BASE DE DATOS
# Para Neon PostgreSQL (reemplaza con tu cadena de conexión):
# DATABASE_URL="postgresql://neondb_owner:xxxx@ep-cool-fog-12345.us-east-2.aws.neon.tech/neondb?sslmode=require"
# Para SQLite local rápido:
DATABASE_URL="sqlite:///./rifa.db"

# SEGURIDAD PANEL ADMIN
ADMIN_PASSWORD="RifaLuis2026!"

# FLOW.CL
# Si lo dejas vacío, funcionará el simulador local para pruebas
FLOW_API_KEY=""
FLOW_SECRET_KEY=""
FLOW_URL="https://sandbox.flow.cl/api"

# RESEND (CORREOS)
RESEND_API_KEY=""
RESEND_FROM_EMAIL="Rifa Solidaria <onboarding@resend.dev>"

# SOPORTE Y DATOS DE TRANSFERENCIA (Ya preconfigurados)
WHATSAPP_NUMBER="56927178289"
BANK_BENEFICIARY_NAME="FRANCISCO ANDRES RIQUELME FARIAS"
BANK_BENEFICIARY_RUT="18.240.046-7"
BANK_NAME="Banco Estado"
BANK_ACCOUNT_TYPE="CuentaRUT"
BANK_ACCOUNT_NUMBER="18240046"
```

### 5. Iniciar el servidor
```bash
uvicorn main:app --reload --port 8000
```

- **Sitio Público:** [http://localhost:8000](http://localhost:8000)
- **Panel Administrador:** [http://localhost:8000/admin](http://localhost:8000/admin) (Contraseña: `RifaLuis2026!`)
- **Documentación Interactiva Swagger:** [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 📋 Reglas del Sorteo

- **Valor por número:** $2.000 CLP.
- **Fecha del sorteo:** **10 de diciembre de 2026** o al vender el 100% de los números.
- **Premios:**
  1. **1er Lugar:** $100.000 CLP en efectivo.
  2. **2do Lugar:** Canasta familiar premium + Cena para dos personas.
  3. **3er Lugar:** Audífonos inalámbricos Bluetooth + Premio sorpresa.
- **WhatsApp de soporte:** `+56927178289`.

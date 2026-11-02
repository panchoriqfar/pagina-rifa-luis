-- ==========================================================
-- SCRIPT SQL PARA NEON.TECH (POSTGRESQL)
-- Proyecto: Gran Rifa Solidaria Luis Henríquez
-- ==========================================================

-- 1. Crear tabla de Órdenes (orders)
CREATE TABLE IF NOT EXISTS orders (
    id VARCHAR(36) PRIMARY KEY,
    buyer_name VARCHAR(150) NOT NULL,
    buyer_initials VARCHAR(20) NOT NULL,
    buyer_phone VARCHAR(50) NOT NULL,
    buyer_email VARCHAR(150) NOT NULL,
    numbers_list JSON NOT NULL,
    total_amount INTEGER NOT NULL,
    payment_method VARCHAR(30) NOT NULL,
    payment_status VARCHAR(30) NOT NULL DEFAULT 'pending',
    flow_token VARCHAR(255),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc'),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc')
);

-- Índices para búsqueda rápida de órdenes
CREATE INDEX IF NOT EXISTS ix_orders_id ON orders (id);
CREATE INDEX IF NOT EXISTS ix_orders_payment_status ON orders (payment_status);
CREATE INDEX IF NOT EXISTS ix_orders_buyer_email ON orders (buyer_email);
CREATE INDEX IF NOT EXISTS ix_orders_buyer_phone ON orders (buyer_phone);

-- 2. Crear tabla de Números / Tickets (tickets)
CREATE TABLE IF NOT EXISTS tickets (
    number INTEGER PRIMARY KEY CHECK (number >= 1 AND number <= 100),
    status VARCHAR(20) NOT NULL DEFAULT 'available',
    reserved_until TIMESTAMP WITHOUT TIME ZONE,
    order_id VARCHAR(36) REFERENCES orders(id) ON DELETE SET NULL
);

-- Índices para grilla y limpieza de reservas expiradas
CREATE INDEX IF NOT EXISTS ix_tickets_number ON tickets (number);
CREATE INDEX IF NOT EXISTS ix_tickets_status_reserved ON tickets (status, reserved_until);

-- 3. Poblar automáticamente los 100 números (del 1 al 100) como disponibles
INSERT INTO tickets (number, status, reserved_until, order_id)
SELECT gs.num, 'available', NULL, NULL
FROM generate_series(1, 100) AS gs(num)
ON CONFLICT (number) DO NOTHING;

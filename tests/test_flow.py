import os
os.environ["DATABASE_URL"] = "sqlite:///./test_rifa_temp.db"

from fastapi.testclient import TestClient
import main

def test_full_flow():
    with TestClient(main.app) as client:
        # 0. Verificar vistas HTML principales (/ y /admin)
        home_res = client.get("/")
        assert home_res.status_code == 200, home_res.text
        assert "Premios Sorpresa" in home_res.text
        assert "Hacer donación de premio" in home_res.text
        admin_res = client.get("/admin")
        assert admin_res.status_code == 200, admin_res.text
        print("✓ PASS: Vistas HTML / y /admin renderizadas correctamente (incluyendo Premios Sorpresa y Donación de premio).")

        # 1. Verificar tickets inicializados
        res = client.get("/api/tickets")
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["total_tickets"] == 150, f"Expected 150 tickets, got {data['total_tickets']}"
        assert len(data["tickets"]) == 150
        print("✓ PASS: 150 tickets inicializados correctamente.")

        # 2. Crear reserva con Transferencia (incluyendo número 150)
        payload = {
            "numbers": [7, 150],
            "buyer_name": "Francisco Riquelme",
            "buyer_phone": "+56912345678",
            "buyer_email": "test@example.com",
            "payment_method": "transfer"
        }
        order_res = client.post("/api/orders", json=payload)
        assert order_res.status_code == 200, order_res.text
        order_data = order_res.json()
        assert order_data["order"]["buyer_initials"] == "F. R."
        assert order_data["order"]["total_amount"] == 4000
        order_id = order_data["order"]["id"]
        print(f"✓ PASS: Orden {order_id} creada exitosamente con iniciales F. R. y total $4.000 CLP.")

        # 3. Verificar que la grilla pública proteja datos privados
        grid_res = client.get("/api/tickets").json()
        t7 = next(t for t in grid_res["tickets"] if t["number"] == 7)
        assert t7["status"] == "reserved"
        assert "buyer_name" not in t7
        assert "buyer_phone" not in t7
        assert "buyer_email" not in t7
        print("✓ PASS: Número #07 en estado reservado y datos sensibles protegidos.")

        # 4. Aprobar transferencia desde el Panel de Administración
        cookies = {"admin_session": "RifaLuis2026!"}
        approve_res = client.post(f"/api/admin/orders/{order_id}/approve", cookies=cookies)
        assert approve_res.status_code == 200, approve_res.text
        print("✓ PASS: Administrador aprobó la transferencia.")

        # 5. Verificar que el número #07 ahora está VENDIDO con iniciales F. R.
        grid_res2 = client.get("/api/tickets").json()
        t7_sold = next(t for t in grid_res2["tickets"] if t["number"] == 7)
        assert t7_sold["status"] == "sold"
        assert t7_sold["buyer_initials"] == "F. R."
        print("✓ PASS: Número #07 ahora está VENDIDO y muestra 'F. R.'.")

        # 6. Probar buscador de Mis Números
        search_res = client.get("/api/orders/search?q=test@example.com")
        assert search_res.status_code == 200
        assert len(search_res.json()["results"]) >= 1
        print("✓ PASS: Buscador público encontró la compra.")

        # 7. Probar exportación a CSV para el sorteo
        csv_res = client.get("/api/admin/export-csv", cookies=cookies)
        assert csv_res.status_code == 200
        assert "Numero;Estado;Comprador;Iniciales" in csv_res.text
        print("✓ PASS: Exportación de CSV para el sorteo generada con éxito.")

        # 8. Verificar que el simulador está eliminado por completo (404)
        sim_get = client.get(f"/flow-checkout-simulation?order_id={order_id}")
        assert sim_get.status_code == 404, f"El simulador no debe existir, retornó {sim_get.status_code}"
        sim_post = client.post("/api/mock-flow/confirm", data={"order_id": order_id, "action": "pay"})
        assert sim_post.status_code == 404, f"El endpoint mock no debe existir, retornó {sim_post.status_code}"
        print("✓ PASS: Simulador de pagos eliminado de todo registro (HTTP 404).")

        # 9. Probar creación de orden con Pasarela Oficial Flow.cl
        flow_payload = {
            "numbers": [45],
            "buyer_name": "María González",
            "buyer_phone": "+56987654321",
            "buyer_email": "maria.test@gmail.com",
            "payment_method": "flow"
        }
        flow_res = client.post("/api/orders", json=flow_payload)
        assert flow_res.status_code == 200, flow_res.text
        flow_data = flow_res.json()
        flow_order_id = flow_data["order"]["id"]
        assert flow_data["order"]["flow_token"] is not None, "Se esperaba un token real de Flow.cl"
        assert "flow.cl" in flow_data["redirect_url"], f"Se esperaba URL de Flow.cl, se obtuvo: {flow_data['redirect_url']}"
        print(f"✓ PASS: Orden Flow.cl {flow_order_id} conectada en vivo -> {flow_data['redirect_url']}")

        # 9. Limpiar datos de prueba para dejar la base de datos impecable
        db = main.SessionLocal()
        try:
            for t in db.query(main.Ticket).filter(main.Ticket.number.in_([7, 21, 45, 150])).all():
                t.status = "available"
                t.reserved_until = None
                t.order_id = None
            for oid in [order_id, flow_order_id]:
                test_order = db.query(main.Order).filter(main.Order.id == oid).first()
                if test_order:
                    db.delete(test_order)
            db.commit()
        finally:
            db.close()
            main.engine.dispose()
            if os.path.exists("./test_rifa_temp.db"):
                try:
                    os.remove("./test_rifa_temp.db")
                except Exception:
                    pass
        print("✓ PASS: Datos de prueba limpiados; los 150 números quedaron disponibles en la BD.")

if __name__ == "__main__":
    test_full_flow()
    print("\n🎉 ¡TODAS LAS PRUEBAS PASARON EXITOSAMENTE!")

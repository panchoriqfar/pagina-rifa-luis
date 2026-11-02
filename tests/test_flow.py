from fastapi.testclient import TestClient
import main

def test_full_flow():
    with TestClient(main.app) as client:
        # 1. Verificar tickets inicializados
        res = client.get("/api/tickets")
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["total_tickets"] == 100, f"Expected 100 tickets, got {data['total_tickets']}"
        assert len(data["tickets"]) == 100
        print("✓ PASS: 100 tickets inicializados correctamente.")

        # 2. Crear reserva con Transferencia
        payload = {
            "numbers": [7, 21],
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

if __name__ == "__main__":
    test_full_flow()
    print("\n🎉 ¡TODAS LAS PRUEBAS PASARON EXITOSAMENTE!")

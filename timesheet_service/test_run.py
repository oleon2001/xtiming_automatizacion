import json
import logging
from web_automator import WebAutomator

# Leer los tickets pendientes para extraer uno y probarlo
try:
    with open('data/pending_tickets.json', 'r', encoding='utf-8') as f:
        pending_data = json.load(f)
        tickets = pending_data.get('tickets', [])
except Exception as e:
    print(f"No se pudo leer data/pending_tickets.json: {e}")
    tickets = []

if not tickets:
    print("No hay tickets pendientes para probar en data/pending_tickets.json.")
    print("Por favor, usa un diccionario de prueba de ejemplo.")
    # Datos de prueba genéricos
    test_data = {
        "title": "Prueba de Ingesta y Web Automator",
        "start_time": "25.02.2026 09:00",
        "end_time": "25.02.2026 10:00",
        "client": "Intelix",
        "project": "Gestión - Intelix",
        "activity": "Soporte",
        "tags": ["Soporte"],
        "ticket_id": "12345"
    }
else:
    # Usamos el primer ticket de la cola
    test_data = tickets[0]
    print(f"Probando con el ticket: {test_data.get('title')}")

print("\n--- INICIANDO PRUEBA DE WEB AUTOMATOR ---")
# Inicializamos el WebAutomator en modo no "headless" para que puedas ver el navegador si quieres
# (Para forzar ver el navegador, pasamos headless=False, aunque dependa de tu config.json)
automator = WebAutomator({"app": {"headless_browser": False}})

try:
    automator.start_browser()
    resultado = automator.fill_timesheet_entry(test_data)
    
    if resultado:
        print("\n¡EXITO! El ticket se registró correctamente.")
    else:
        print("\nFALLO. Revisa el archivo automator.log o las imágenes generadas (error_validation_...png).")
finally:
    print("Cerrando navegador...")
    automator.close_browser()

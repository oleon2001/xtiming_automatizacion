import os
import sys
# Añadir ruta temporal para importar módulos
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scheduler_service import SchedulerService
from datetime import datetime, timedelta

def get_dummy_config():
    return {
        "app": {},
        "schedule": {"target_hours": 8},
        "defaults": {},
        "entity_map": {}
    }

print("=== INICIANDO PRUEBA DE BLOQUEO DE SEMANA ===")
# Crear instancia ligera (podría fallar init web_automator si faltan vars, 
# pero solo queremos probar _is_ticket_locked puro)
# Para evitar fallos init, emulamos la clase o usamos un mock
class DummyScheduler:
    from scheduler_service import SchedulerService
    _is_ticket_locked = SchedulerService._is_ticket_locked

scheduler = DummyScheduler()

today = datetime.now()
today_name = today.strftime("%A")
today_isoday = today.isocalendar()[2]
print(f"LA FECHA MÁQUINA HOY ES: {today.strftime('%Y-%m-%d')} ({today_name}, Día ISO: {today_isoday})")

# Fechas de prueba
tests = [
    ("Hoy", today.strftime("%Y-%m-%d")),
    ("Hace 1 día", (today - timedelta(days=1)).strftime("%Y-%m-%d")),
    ("Hace 7 días (Semana pasada segura)", (today - timedelta(days=7)).strftime("%Y-%m-%d")),
    ("Hace 14 días (Hace 2 semanas)", (today - timedelta(days=14)).strftime("%Y-%m-%d")),
    ("Con Formato Completo GLPI", (today - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S"))
]

for label, date_str in tests:
    is_locked = scheduler._is_ticket_locked(date_str)
    estado = "BLOQUEADO" if is_locked else "PERMITIDO"
    print(f"[{estado}] Ticket de {label} ({date_str})")

print("========================================")

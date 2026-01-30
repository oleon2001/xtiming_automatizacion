import sys
import os
import json
import logging

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scheduler_service import SchedulerService

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Verifier")

def verify():
    print("="*60)
    print(" VERIFICADOR DE INGESTIÓN DE TICKETS")
    print("="*60)

    # 1. Load Config
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
    if not os.path.exists(config_path):
        print(f" Error: No se encontró config.json en {config_path}")
        return

    with open(config_path, 'r') as f:
        config = json.load(f)

    # 2. Init Service
    print(" Inicializando SchedulerService...")
    service = SchedulerService(config)
    
    print(f" Directorio de datos: {service.data_dir}")
    print(f" Archivo de pendientes: {service.pending_file}")

    # 3. Check DB Connection
    print("\n Testeando conexión a DB...")
    try:
        tickets = service.db.fetch_closed_tickets_today()
        print(f" Conexión exitosa. Tickets cerrados hoy en GLPI: {len(tickets)}")
        for t in tickets:
            print(f"   - [{t['ticket_id']}] {t['ticket_title']}")
    except Exception as e:
        print(f" Error conectando a DB: {e}")
        return

    # 4. Force Routine A
    print("\n Ejecutando Rutina A (Recolección)...")
    service.routine_a()

    # 5. Check File Content
    print("\nVerificando persistencia...")
    if os.path.exists(service.pending_file):
        size = os.path.getsize(service.pending_file)
        print(f" El archivo existe. Tamaño: {size} bytes")
        
        try:
            with open(service.pending_file, 'r') as f:
                content = f.read()
                if not content:
                    print(" El archivo está vacío.")
                else:
                    data = json.loads(content)
                    print(f" JSON válido. Tickets en cola: {len(data)}")
                    print(f"CONTENIDO: {json.dumps(data, indent=2)}")
        except Exception as e:
            print(f" Error leyendo JSON: {e}")
    else:
        print(" Error: El archivo pending_tickets.json NO se creó.")

    print("="*60)

if __name__ == "__main__":
    from dotenv import load_dotenv
    # Load .env from parent dir
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    load_dotenv(env_path)
    verify()

import sys
import os

# Add parent directory to path to allow importing modules from root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scheduler_service import SchedulerService
import json
import logging
from dotenv import load_dotenv

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("LocalRunner")

def run_local():
    # 1. Cargar .env desde el directorio padre
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(base_dir, '.env'))
    
    if not os.getenv("XTIMING_USER") or not os.getenv("GLPI_DB_HOST"):
        logger.error("No se encontraron variables de entorno críticas. Verifica tu archivo .env")
        return

    # 2. Cargar config desde el directorio padre
    try:
        config_path = os.path.join(base_dir, 'config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.error("config.json no encontrado")
        return

    # 3. FORZAR MODO GRAFICO (Para que lo veas)
    # Sobreescribimos la opción headless solo en memoria para esta ejecución
    if "app" not in config: config["app"] = {}
    config["app"]["headless_browser"] = False
    
    logger.info("="*60)
    logger.info(" INICIANDO EJECUCION LOCAL COMPLETA (DB + WEB)")
    logger.info(" Modo: HEADLESS = FALSE (Verás el navegador)")
    logger.info("="*60)

    # 4. Iniciar Servicio y ejecutar rutina UNA VEZ
    try:
        service = SchedulerService(config)
        logger.info("Conectando a BD y buscando tickets de hoy...")
        
        # Ejecutamos DIRECTAMENTE la rutina A (no el loop del scheduler)
        service.routine_a()
        
        logger.info("\n" + "="*60)
        logger.info(" Ejecución finalizada.")
        logger.info("="*60)
        
    except Exception as e:
        logger.critical(f"Error fatal: {e}", exc_info=True)

if __name__ == "__main__":
    run_local()

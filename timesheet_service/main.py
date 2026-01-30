import argparse
import sys
import json
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
import os

# Ensure we can import modules from current directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def setup_logging(config):
    """Configura el sistema de logging con rotación de archivos."""
    log_level = getattr(logging, config.get("app", {}).get("log_level", "INFO").upper(), logging.INFO)
    log_file = config.get("app", {}).get("log_file", "app.log")
    
    # Crear un handler que rota el archivo cada 5MB, manteniendo 3 backups
    file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
    console_handler = logging.StreamHandler()
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logging.basicConfig(
        level=log_level,
        handlers=[file_handler, console_handler]
    )
    return logging.getLogger("Main")

try:
    from scheduler_service import SchedulerService
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

def main():
    # Argument parsing
    parser = argparse.ArgumentParser(description="Xtiming Automation Service")
    parser.add_argument("--now", action="store_true", help="Fuerza la ejecución inmediata de todas las rutinas (incluyendo el llenado de horas) al iniciar.")
    args = parser.parse_args()

    # Load environment variables
    base_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(base_dir, '.env')
    config_path = os.path.join(base_dir, 'config.json')
    
    load_dotenv(env_path)
    
    # Cargar configuración
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        print("Error: config.json no encontrado.")
        return

    logger = setup_logging(config)
    
    logger.info("Iniciando servicio{config_name}...".format(
        config_name=f" con {os.path.basename(config_path)}" if config_path else ""
    ))

    if args.now:
        logger.info("Modo manual activado: Se ejecutarán todas las tareas inmediatamente.")

    # Pasar la configuración al servicio
    service = SchedulerService(config)
    try:
        service.run(force_now=args.now)
    except KeyboardInterrupt:
        logger.info("Service stopped by user.")
    except Exception as e:
        logger.critical(f"Critical error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()

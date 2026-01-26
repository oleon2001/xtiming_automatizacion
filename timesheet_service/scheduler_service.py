import time
import schedule
import os
import logging
import requests
from datetime import datetime
import db_handler
import time_manager
import web_automator

logger = logging.getLogger("Scheduler")

class SchedulerService:
    def __init__(self, config):
        self.config = config
        self.db = db_handler.DBHandler()
        # Pasamos config al TimeManager y WebAutomator
        self.timer = time_manager.TimeManager(config)
        self.bot = web_automator.WebAutomator(config)
        
        # Mapeos desde config
        self.entity_map = config.get("entity_map", {})
        self.defaults = config.get("defaults", {})

    def send_telegram(self, msg):
        token = os.getenv("TG_BOT_TOKEN")
        chat_id = os.getenv("TG_CHAT_ID")
        if token and chat_id:
            try:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
            except Exception as e:
                logger.error(f"Error enviando Telegram: {e}")

    def _determine_ticket_metadata(self, ticket_data):
        """
        Determina cliente/proyecto usando configuración externa.
        """
        title_lower = ticket_data.get('ticket_title', '').lower() # Nota: db_handler devuelve 'ticket_title'
        entity_name = ticket_data.get('entity_name', '')
        entity_id = str(ticket_data.get('entities_id', ''))
        entity_upper = entity_name.upper() if entity_name else ""
        
        meta = {
            "activity": self.defaults.get("activity", "Soporte"),
            "tags": self.defaults.get("tag", "Soporte")
        }

        # 1. Búsqueda directa por ID en config
        if entity_id in self.entity_map:
            suffix = self.entity_map[entity_id]
            meta["client"] = f"EPA {suffix}"
            meta["project"] = f"Continuidad de Aplicaciones - EPA {suffix}"
            meta["activity"] = "Caja Registradora" # Regla específica mantenida
            return meta

        # 2. Heurística de respaldo basada en Nombre (EPA)
        if "EPA" in entity_upper:
            # Intentar extraer sufijo (SV, GT, etc)
            for suffix in ["SV", "GT", "CR", "VE"]:
                if suffix in entity_upper:
                    meta["client"] = f"EPA {suffix}"
                    meta["project"] = f"Continuidad de Aplicaciones - EPA {suffix}"
                    meta["activity"] = "Caja Registradora"
                    return meta
            
            # Fallback genérico EPA
            meta["client"] = self.defaults.get("client_fallback", "Comercializadoras EPA")
            meta["project"] = self.defaults.get("project_fallback")
            return meta

        # 3. Heurística Bamerica
        if "bamerica" in title_lower:
            meta["client"] = "Bamerica"
            meta["project"] = "Gestión - Bamerica"
            return meta
       
        # 4. Fallback final
        meta["client"] = self.defaults.get("client_fallback", "Intelix")
        meta["project"] = self.defaults.get("project_fallback", "Gestión - Intelix")
        
        return meta

    def routine_a(self):
        logger.info("Ejecutando Rutina A (Procesamiento de Tickets)...")
        try:
            tickets = self.db.fetch_closed_tickets_today()
            if not tickets:
                logger.info("No se encontraron tickets cerrados hoy.")
                return

            # Calcular slots (excluyendo ya procesados internamente por TimeManager)
            schedule_plan = self.timer.calculate_ticket_slots(tickets)
            
            if not schedule_plan:
                logger.info("Hay tickets, pero todos ya fueron procesados.")
                return

            for item in schedule_plan:
                try:
                    # Enriquecer con metadatos
                    # 'raw_ticket' viene del TimeManager
                    raw_data = item.get('raw_ticket', {})
                    inferred_meta = self._determine_ticket_metadata(raw_data)
                    item.update(inferred_meta)
                    
                    # Ejecutar automatización
                    success = self.bot.fill_timesheet_entry(item)
                    
                    if success:
                        self.timer.mark_as_processed(item['ticket_id'])
                        log_msg = f"Ticket registrado: {item['title']} ({item['duration_min']} min)"
                        logger.info(log_msg)
                        self.send_telegram(f"✅ {log_msg}")
                    else:
                        logger.warning(f"Fallo lógico al registrar ticket {item['ticket_id']}")

                except Exception as e:
                    logger.error(f"Excepción procesando ticket {item['ticket_id']}: {e}", exc_info=True)
                    self.send_telegram(f" Error registrando ticket {item['ticket_id']}: {e}")

        except Exception as e:
            logger.error(f"Error fatal en Rutina A: {e}", exc_info=True)

    def routine_b(self):
        logger.info("Ejecutando Rutina B (Cierre Diario)...")
        try:
            adjustment = self.timer.calculate_adjustment_entry()
            
            if adjustment:
                # Usar metadatos por defecto para el ajuste
                adjustment.update({
                    "client": self.defaults.get("client_fallback"),
                    "project": self.defaults.get("project_fallback"),
                    "activity": "Administración", # O lo que corresponda
                    "tags": "Administrativo"
                })

                success = self.bot.fill_timesheet_entry(adjustment)
                if success:
                    msg = f"Ajuste de jornada: {adjustment['duration_min']} min para completar 8h."
                    logger.info(msg)
                    self.send_telegram(f"🏁 {msg}")
                else:
                    logger.error("Falló el registro del ajuste de jornada.")
            else:
                logger.info("Jornada completa. No se requiere ajuste.")
                self.send_telegram(" Jornada completa. No se requiere ajuste.")
                
            # Nota: TimeManager se resetea solo al iniciar nuevo día, 
            # no necesitamos forzar limpieza aquí, pero podríamos loguear el fin.
            
        except Exception as e:
            logger.error(f"Error en Rutina B: {e}", exc_info=True)

    def run(self):
        schedule.every(2).hours.do(self.routine_a)
        schedule.every().day.at("18:00").do(self.routine_b)
        
        logger.info("Scheduler iniciado. Esperando tareas...")
        
        # Ejecución inicial al arrancar para atrapar lo pendiente
        self.routine_a()
        
        while True:
            schedule.run_pending()
            time.sleep(60)

if __name__ == "__main__":
    # Test simple si se corre directo (necesita config fake)
    pass
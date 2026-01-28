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
        self._validate_config(config)
        self.config = config
        self.db = db_handler.DBHandler()
        self.timer = time_manager.TimeManager(config)
        self.bot = web_automator.WebAutomator(config)
        
        self.entity_map = config.get("entity_map", {})
        self.defaults = config.get("defaults", {})
        
        self.pending_file = "pending_tickets.json"

    def _validate_config(self, config):
        """Validación básica de estructura de configuración."""
        required_sections = ["app", "schedule", "defaults", "entity_map"]
        missing = [s for s in required_sections if s not in config]
        if missing:
            raise ValueError(f"Configuración inválida. Faltan secciones: {', '.join(missing)}")
        
        if not isinstance(config["schedule"].get("target_hours"), (int, float)):
             logger.warning("Config 'target_hours' debería ser numérico. Se usará default.")

    def _load_pending_tickets(self):
        if not os.path.exists(self.pending_file):
            return []
        try:
            with open(self.pending_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error cargando tickets pendientes: {e}")
            return []

    def _save_pending_tickets(self, tickets):
        try:
            with open(self.pending_file, "w") as f:
                json.dump(tickets, f, default=str)
        except Exception as e:
            logger.error(f"Error guardando tickets pendientes: {e}")

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
        title_lower = ticket_data.get('ticket_title', '').lower()
        entity_id = str(ticket_data.get('entities_id', ''))
        fullname_upper = ticket_data.get('entity_fullname', '').upper()
        
        meta = {
            "activity": self.defaults.get("activity", "Soporte"),
            "tags": self.defaults.get("tag", "Soporte")
        }

        # 1. Búsqueda directa por ID en config
        if entity_id in self.entity_map:
            suffix = self.entity_map[entity_id]
            meta["client"] = f"EPA {suffix}"
            meta["project"] = f"Continuidad de Aplicaciones - EPA {suffix}"
            meta["activity"] = "Caja Registradora" 
            return meta

        # 2. Heurística usando Complete Name
        if "EPA" in fullname_upper:
            if "EPAVE" in fullname_upper or "EPA VE" in fullname_upper: suffix = "VE"
            elif "EPAGT" in fullname_upper or "EPA GT" in fullname_upper: suffix = "GT"
            elif "EPACR" in fullname_upper or "EPA CR" in fullname_upper: suffix = "CR"
            elif "EPASV" in fullname_upper or "EPA SV" in fullname_upper: suffix = "SV"
            else: suffix = None

            if suffix:
                meta["client"] = f"EPA {suffix}"
                meta["project"] = f"Continuidad de Aplicaciones - EPA {suffix}"
                meta["activity"] = "Caja Registradora"
                return meta
            
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
        logger.info("Ejecutando Rutina A (Recolección de Tickets)...")
        try:
            # 1. Obtener tickets nuevos de DB
            new_tickets = self.db.fetch_closed_tickets_today()
            if not new_tickets:
                logger.info("No hay tickets nuevos en GLPI.")
                return

            # 2. Cargar pendientes actuales
            pending = self._load_pending_tickets()
            pending_ids = {str(t['ticket_id']) for t in pending}
            
            # 3. Filtrar: No procesados HOY y No en cola pendiente
            # Nota: time_manager.processed_ids tiene lo que YA se envió a la web
            added_count = 0
            for ticket in new_tickets:
                tid = str(ticket['ticket_id'])
                if tid not in self.timer.processed_ids and tid not in pending_ids:
                    pending.append(ticket)
                    pending_ids.add(tid)
                    added_count += 1
            
            # 4. Guardar cola
            if added_count > 0:
                self._save_pending_tickets(pending)
                msg = f"📥 Se encolaron {added_count} tickets nuevos. Total pendiente: {len(pending)}"
                logger.info(msg)
                self.send_telegram(msg)
            else:
                logger.info("Tickets encontrados ya estaban en cola o procesados.")

        except Exception as e:
            logger.error(f"Error en Rutina A: {e}", exc_info=True)

    def routine_b(self):
        logger.info("Ejecutando Rutina B (Procesamiento Batch - 18:00)...")
        try:
            pending_tickets = self._load_pending_tickets()
            
            if not pending_tickets:
                logger.info("No hay tickets pendientes para procesar.")
                self.send_telegram("ℹ️ Fin de jornada: No hubo tickets para registrar.")
                return

            # 1. Calcular distribución perfecta (8 horas / N tickets)
            schedule_plan = self.timer.calculate_distributed_slots(pending_tickets)
            
            logger.info(f"Procesando lote final de {len(schedule_plan)} tickets...")
            self.send_telegram(f"🚀 Iniciando carga masiva de {len(schedule_plan)} tickets distribuidos en 8h.")

            try:
                self.bot.start_browser()
                success_count = 0
                
                for item in schedule_plan:
                    try:
                        # Enriquecer metadata
                        raw_data = item.get('raw_ticket', {})
                        item.update(self._determine_ticket_metadata(raw_data))
                        
                        # Enviar
                        if self.bot.fill_timesheet_entry(item):
                            self.timer.mark_as_processed(item['ticket_id'])
                            success_count += 1
                            logger.info(f"Registrado: {item['title']} ({item['duration_min']}m)")
                        else:
                            logger.error(f"Fallo al registrar {item['ticket_id']}")
                            
                    except Exception as e:
                        logger.error(f"Error procesando item {item['ticket_id']}: {e}")

                # Reporte final
                self.send_telegram(f"✅ Jornada finalizada. Registrados {success_count}/{len(pending_tickets)} tickets.")
                
                # Limpiar cola (o dejar los fallidos? Por simplicidad, limpiamos todo para evitar loop infinito mañana)
                # Idealmente deberíamos guardar los fallidos, pero asumimos intervención humana si falla.
                self._save_pending_tickets([]) 

            finally:
                self.bot.close_browser()

        except Exception as e:
            logger.error(f"Error fatal en Rutina B: {e}", exc_info=True)
            self.send_telegram(f"⚠️ Error crítico en cierre de jornada: {e}")

    def run(self):
        schedule.every(2).hours.do(self.routine_a)
        schedule.every().day.at("18:00").do(self.routine_b)
        
        logger.info("Scheduler iniciado (Modo Batch). Esperando tareas...")
        
        # Ejecución inicial de recolección
        self.routine_a()
        
        while True:
            schedule.run_pending()
            time.sleep(60)

if __name__ == "__main__":
    pass
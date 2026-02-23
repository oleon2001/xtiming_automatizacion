import time
import schedule
import os
import json
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
        
        # Configuración del directorio de datos (Carpeta hermana en despliegue)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.abspath(os.path.join(base_dir, "..", "timesheet_data"))
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.pending_file = os.path.join(self.data_dir, "pending_tickets.json")

    def _validate_config(self, config):
        """Validación básica de estructura de configuración."""
        required_sections = ["app", "schedule", "defaults", "entity_map"]
        missing = [s for s in required_sections if s not in config]
        if missing:
            raise ValueError(f"Configuración inválida. Faltan secciones: {', '.join(missing)}")
        
        if not isinstance(config["schedule"].get("target_hours"), (int, float)):
             logger.warning("Config 'target_hours' debería ser numérico. Se usará default.")

    def _load_pending_tickets(self):
        if not os.path.exists(self.pending_file) or os.path.getsize(self.pending_file) == 0:
            return []
        try:
            with open(self.pending_file, "r", encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error cargando tickets pendientes: {e}")
            return []

    def _save_pending_tickets(self, tickets):
        try:
            with open(self.pending_file, "w", encoding='utf-8') as f:
                json.dump(tickets, f, default=str, ensure_ascii=False, indent=4)
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

    def routine_sync_backlog(self, days=7):
        logger.info(f"Ejecutando Sincronizacion de Backlog ({days} dias)...")
        try:
            # 1. Obtener tickets del rango de la ultima semana
            backlog_tickets = self.db.fetch_closed_tickets_range(days=days)
            if not backlog_tickets:
                logger.info("No se encontraron tickets en el periodo especificado.")
                return

            # 2. Cargar pendientes actuales y verificar procesados
            pending = self._load_pending_tickets()
            pending_ids = {str(t['ticket_id']) for t in pending}
            
            # 3. Filtrar: Solo los que no estan en procesados ni en la cola actual
            added_count = 0
            for ticket in backlog_tickets:
                tid = str(ticket['ticket_id'])
                if tid not in self.timer.processed_ids and tid not in pending_ids:
                    pending.append(ticket)
                    pending_ids.add(tid)
                    added_count += 1
            
            # 4. Guardar cola actualizada
            if added_count > 0:
                self._save_pending_tickets(pending)
                msg = f"Sincronizacion: Se recuperaron {added_count} tickets de la semana. Total pendiente: {len(pending)}"
                logger.info(msg)
                self.send_telegram(msg)
            else:
                logger.info("No se encontraron tickets faltantes en el periodo.")

        except Exception as e:
            logger.error(f"Error en Sincronizacion de Backlog: {e}", exc_info=True)

    def routine_a(self):
        logger.info("Ejecutando Rutina A (Recoleccion de Tickets)...")
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
                msg = f"Se encolaron {added_count} tickets nuevos. Total pendiente: {len(pending)}"
                logger.info(msg)
                self.send_telegram(msg)
            else:
                logger.info("Tickets encontrados ya estaban en cola o procesados.")

        except Exception as e:
            logger.error(f"Error en Rutina A: {e}", exc_info=True)

    def routine_b(self):
        logger.info("Ejecutando Rutina B (Procesamiento Batch)...")
        successful_ids = set()
        
        try:
            pending_tickets = self._load_pending_tickets()
            if not pending_tickets:
                logger.info("No hay tickets pendientes para procesar.")
                self.send_telegram("Fin de jornada: No hubo tickets para registrar.")
                return

            # 1. Agrupar tickets por fecha (YYYY-MM-DD)
            tickets_by_date = {}
            for t in pending_tickets:
                try:
                    # Soporte para tickets de Telegram (target_date) o GLPI (solvedate)
                    if t.get('source') == 'telegram':
                        date_str = t.get('target_date', datetime.now().strftime("%Y-%m-%d"))
                    else:
                        sdate = t.get('solvedate')
                        if not sdate:
                             date_str = datetime.now().strftime("%Y-%m-%d")
                        else:
                             date_str = sdate[:10] if isinstance(sdate, str) else sdate.strftime("%Y-%m-%d")
                except Exception as e:
                    logger.warning(f"Error parseando fecha de ticket: {e}. Usando HOY.")
                    date_str = datetime.now().strftime("%Y-%m-%d")
                
                if date_str not in tickets_by_date:
                    tickets_by_date[date_str] = []
                tickets_by_date[date_str].append(t)

            logger.info(f"Se detectaron tickets para {len(tickets_by_date)} dias diferentes.")
            self.send_telegram(f"Iniciando carga masiva. Dias a procesar: {', '.join(tickets_by_date.keys())}")

            try:
                self.bot.start_browser()
                
                for date_str, daily_tickets in sorted(tickets_by_date.items()):
                    logger.info(f"Procesando dia {date_str} ({len(daily_tickets)} tickets)...")
                    
                    # 2. Calcular distribucion para ESTE dia especifico
                    schedule_plan = self.timer.calculate_distributed_slots(daily_tickets)
                    
                    success_count = 0
                    for item in schedule_plan:
                        ticket_id = item.get('ticket_id')
                        try:
                            # Enriquecer metadata
                            raw_data = item.get('raw_ticket', {})
                            
                            if raw_data.get('source') == 'telegram':
                                # Usar datos ya provistos por el usuario en Telegram
                                item['client'] = raw_data.get('client')
                                item['project'] = raw_data.get('project')
                                item['activity'] = raw_data.get('activity')
                                item['tags'] = raw_data.get('tags')
                            else:
                                # Enriquecer con heurísticas para GLPI
                                item.update(self._determine_ticket_metadata(raw_data))
                            
                            # Enviar a la web
                            if self.bot.fill_timesheet_entry(item):
                                self.timer.mark_as_processed(ticket_id)
                                successful_ids.add(str(ticket_id))
                                success_count += 1
                                logger.info(f"Registrado con exito [{date_str}]: {item['title']} (ID: {ticket_id})")
                            else:
                                logger.error(f"Fallo al registrar Ticket ID {ticket_id} en fecha {date_str}")
                                
                        except Exception as e:
                            logger.error(f"Error critico procesando Ticket ID {ticket_id}: {str(e)}")
                            continue
                    
                    logger.info(f"Completado dia {date_str}: {success_count}/{len(daily_tickets)} exitosos.")

                self.send_telegram(f"Proceso finalizado. Total IDs procesados: {len(successful_ids)}")

            finally:
                self.bot.close_browser()
                
                # Solo remover de pendientes los que REALMENTE se procesaron
                remaining_tickets = [t for t in pending_tickets if str(t['ticket_id']) not in successful_ids]
                self._save_pending_tickets(remaining_tickets)
                
                if remaining_tickets:
                    logger.warning(f"Quedaron {len(remaining_tickets)} tickets pendientes.")
                    self.send_telegram(f"Quedaron {len(remaining_tickets)} tickets sin registrar. Ver log.")

        except Exception as e:
            logger.error(f"Error fatal en Rutina B: {e}", exc_info=True)
            self.send_telegram(f"Error critico en cierre de jornada: {e}")

        except Exception as e:
            logger.error(f"Error fatal en Rutina B: {e}", exc_info=True)
            self.send_telegram(f"Error crítico en cierre de jornada: {e}")

    def run(self, force_now=False, force_sync=False):
        # Programar tareas regulares
        schedule.every(2).hours.do(self.routine_a)
        schedule.every().day.at("18:00").do(self.routine_b)
        
        # Sincronización semanal opcional (ej: todos los Lunes a las 08:00)
        schedule.every().monday.at("08:00").do(self.routine_sync_backlog)
        
        logger.info("Scheduler iniciado. Esperando tareas...")
        
        # Ejecuciones iniciales si se solicitan
        if force_sync:
            logger.info("FORZANDO SINCRONIZACIÓN DE BACKLOG SEMANAL...")
            self.routine_sync_backlog()

        self.routine_a()

        if force_now:
            logger.info("FORZANDO EJECUCIÓN INMEDIATA (Argumento --now detectado)")
            self.routine_b()
        
        while True:
            schedule.run_pending()
            time.sleep(60)

if __name__ == "__main__":
    pass
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
import local_db

logger = logging.getLogger("Scheduler")

class SchedulerService:
    def __init__(self, config):
        self._validate_config(config)
        self.config = config
        self.db = db_handler.DBHandler()
        self.local_db = local_db.LocalDB()
        self.timer = time_manager.TimeManager(config, self.local_db)
        self.bot = web_automator.WebAutomator(config)
        
        self.entity_map = config.get("entity_map", {})
        self.defaults = config.get("defaults", {})
        
        # Cargar mapeos de negocio
        self.mappings = self._load_mappings()
        
        # Configuración del directorio de datos (Carpeta interna gestionada por Docker)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.join(base_dir, "data")
        os.makedirs(self.data_dir, exist_ok=True)
        
    def _load_mappings(self):
        """Carga el archivo de mapeos de negocio."""
        mappings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mappings.json')
        try:
            with open(mappings_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"No se pudo cargar mappings.json: {e}")
            return {"entity_rules": {}, "heuristics": []}

    def _validate_config(self, config):
        """Validación básica de estructura de configuración."""
        required_sections = ["app", "schedule", "defaults", "entity_map"]
        missing = [s for s in required_sections if s not in config]
        if missing:
            raise ValueError(f"Configuración inválida. Faltan secciones: {', '.join(missing)}")
        
        if not isinstance(config["schedule"].get("target_hours"), (int, float)):
             logger.warning("Config 'target_hours' debería ser numérico. Se usará default.")

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
        Determina cliente/proyecto usando reglas externas de mappings.json.
        """
        title = ticket_data.get('ticket_title', '')
        entity_id = str(ticket_data.get('entities_id', ''))
        fullname = ticket_data.get('entity_fullname', '')
        
        # Valores base por defecto
        meta = {
            "activity": self.defaults.get("activity", "Soporte"),
            "tags": self.defaults.get("tag", "Soporte"),
            "client": self.defaults.get("client_fallback", "Intelix"),
            "project": self.defaults.get("project_fallback", "Gestión - Intelix")
        }

        # 1. Búsqueda directa por ID de Entidad
        entity_rules = self.mappings.get("entity_rules", {})
        if entity_id in entity_rules:
            meta.update(entity_rules[entity_id])
            return meta

        # 2. Heurísticas basadas en texto (Contenido de nombre o título)
        heuristics = self.mappings.get("heuristics", [])
        for rule in heuristics:
            field_value = ""
            if rule["field"] == "entity_fullname":
                field_value = fullname.upper()
            elif rule["field"] == "ticket_title":
                field_value = title.lower()
            
            # Verificar si alguna de las palabras clave coincide
            match = False
            patterns = rule["contains"]
            if isinstance(patterns, str): patterns = [patterns]
            
            for p in patterns:
                p_check = p.upper() if rule["field"] == "entity_fullname" else p.lower()
                if p_check in field_value:
                    match = True
                    break
            
            if match:
                meta.update(rule["result"])
                # Si la regla no especificó proyecto pero sí cliente, intentamos heredar el proyecto del fallback
                if "client" in rule["result"] and "project" not in rule["result"]:
                    # Lógica especial para EPA si solo se detectó el cliente base
                    if "EPA" in rule["result"]["client"] and not meta.get("project"):
                         meta["project"] = self.defaults.get("project_fallback")
                return meta
       
        return meta

    def routine_sync_backlog(self, days=7):
        logger.info(f"Ejecutando Sincronizacion de Backlog ({days} dias)...")
        try:
            # 1. Obtener tickets del rango de la ultima semana
            backlog_tickets = self.db.fetch_closed_tickets_range(days=days)
            if not backlog_tickets:
                logger.info("No se encontraron tickets en el periodo especificado.")
                return

            # 2. Cargar pendientes actuales
            pending_list = self.local_db.get_pending_tickets()
            pending_ids = {str(t['ticket_id']) for t in pending_list}
            
            # 3. Filtrar: Solo los que no estan en procesados ni en la cola actual
            added_count = 0
            for ticket in backlog_tickets:
                tid = str(ticket['ticket_id'])
                if not self.local_db.is_processed(tid) and tid not in pending_ids:
                    self.local_db.add_pending_ticket(ticket)
                    pending_ids.add(tid)
                    added_count += 1
            
            # 4. Notificar
            if added_count > 0:
                msg = f"Sincronizacion: Se recuperaron {added_count} tickets de la semana. Total pendiente: {len(pending_ids)}"
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
            pending_list = self.local_db.get_pending_tickets()
            pending_ids = {str(t['ticket_id']) for t in pending_list}
            
            # 3. Filtrar: No procesados HOY y No en cola pendiente
            added_count = 0
            for ticket in new_tickets:
                tid = str(ticket['ticket_id'])
                if not self.local_db.is_processed(tid) and tid not in pending_ids:
                    self.local_db.add_pending_ticket(ticket)
                    pending_ids.add(tid)
                    added_count += 1
            
            # 4. Notificar
            if added_count > 0:
                msg = f"Se encolaron {added_count} tickets nuevos. Total pendiente: {len(pending_ids)}"
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
            pending_tickets = self.local_db.get_pending_tickets()
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
                                # Remover de pendientes inmediatamente si fue exitoso
                                self.local_db.remove_pending_ticket(ticket_id)
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
                
                # Verificar remanentes
                pending_after = self.local_db.get_pending_tickets()
                if pending_after:
                    logger.warning(f"Quedaron {len(pending_after)} tickets pendientes.")
                    self.send_telegram(f"Quedaron {len(pending_after)} tickets sin registrar. Ver log.")

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
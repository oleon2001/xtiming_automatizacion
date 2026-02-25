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

    def routine_backlog_sweep(self, days=7):
        """
        Realiza un barrido completo: Sincroniza el backlog y procesa inmediatamente
        los tickets que falten, sin interrumpir la jornada actual.
        """
        logger.info(f"INICIANDO BARRIDO DE BACKLOG ({days} días)...")
        self.send_telegram(f"Iniciando barrido automático de tickets pendientes de los últimos {days} días...")
        
        # 1. Sincronizar (Traer tickets de GLPI a la cola local)
        self.routine_sync_backlog(days=days)
        
        # 2. Procesar silenciosamente
        pending_after_sync = self.local_db.get_pending_tickets()
        if not pending_after_sync:
            logger.info("Barrido finalizado: No hay tickets pendientes por registrar.")
            self.send_telegram("Barrido completado: Todo está al día.")
            return

        # Filtrar solo tickets que pertenezcan al pasado (evitar procesar lo de HOY si se prefiere separar)
        # En este caso procesaremos TODO lo que esté en cola.
        logger.info(f"Barrido: Procesando {len(pending_after_sync)} tickets detectados.")
        self.routine_b() # Reutilizamos la lógica de procesamiento batch
        
        logger.info("BARRIDO DE BACKLOG COMPLETADO.")

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

    def _is_ticket_locked(self, ticket_date_str):
        """
        Bloquea tickets de semanas anteriores a partir del miércoles.
        Semana arranca el lunes. Miércoles es el día 3 (ISO isoweekday() == 3).
        Por regla, todo ticket de la semana (W-1) o menor está bloqueado si hoy es >= miércoles (3).
        """
        if not ticket_date_str:
            return False
            
        try:
            # Parsear fecha del ticket
            if len(ticket_date_str) >= 19:
                ticket_dt = datetime.strptime(ticket_date_str[:19], "%Y-%m-%d %H:%M:%S")
            else:
                ticket_dt = datetime.strptime(ticket_date_str[:10], "%Y-%m-%d")
        except Exception as e:
            logger.warning(f"Error parseando fecha para bloqueo '{ticket_date_str}': {e}")
            return False # En caso de duda, no bloquear

        now_dt = datetime.now()
        
        ticket_year, ticket_week, _ = ticket_dt.isocalendar()
        now_year, now_week, now_day = now_dt.isocalendar()

        # Si el ticket es de este año, pero de una semana estrictamente menor
        # O si el ticket es del año pasado
        is_past_week = (ticket_year < now_year) or (ticket_year == now_year and ticket_week < now_week)

        # today_is_wednesday_or_later. isoformat: 1=Mon, 2=Tue, 3=Wed, 4=Thu...
        is_locked_day = now_day >= 3

        return is_past_week and is_locked_day

    def routine_b(self):
        logger.info("Ejecutando Rutina B (Procesamiento Batch)...")
        successful_ids = set()
        
        try:
            pending_tickets = self.local_db.get_pending_tickets()
            if not pending_tickets:
                logger.info("No hay tickets pendientes para procesar.")
                self.send_telegram("Fin de jornada: No hubo tickets para registrar.")
                return

            # 1. Agrupar tickets por fecha (YYYY-MM-DD) y Filtrar Bloqueados
            tickets_by_date = {}
            locked_count = 0
            
            for t in pending_tickets:
                try:
                    # Soporte para tickets de Telegram (target_date) o GLPI (solvedate)
                    if t.get('source') == 'telegram':
                        raw_date = t.get('target_date', datetime.now().strftime("%Y-%m-%d"))
                    else:
                        sdate = t.get('solvedate')
                        raw_date = sdate if sdate else datetime.now().strftime("%Y-%m-%d")
                        
                    date_str = raw_date[:10] if isinstance(raw_date, str) else raw_date.strftime("%Y-%m-%d")
                except Exception as e:
                    logger.warning(f"Error parseando fecha de ticket: {e}. Usando HOY.")
                    date_str = datetime.now().strftime("%Y-%m-%d")
                    raw_date = date_str
                
                # --- REGLA DE NEGOCIO: FECHA LÍMITE ---
                ticket_id = t.get('ticket_id')
                if self._is_ticket_locked(raw_date):
                    logger.warning(f"TICKET BLOQUEADO: El ticket {ticket_id} ({date_str}) pertenece a una semana ya cerrada.")
                    self.send_telegram(f"Bloqueado: Ticket {ticket_id} ({date_str}) es de la semana pasada y el sistema ya cerró (Miércoles o posterior).")
                    
                    # Lo marcamos procesado para que no vuelva a ser pendiente nunca más
                    self.timer.mark_as_processed(ticket_id)
                    self.local_db.remove_pending_ticket(ticket_id)
                    locked_count += 1
                    continue
                
                if date_str not in tickets_by_date:
                    tickets_by_date[date_str] = []
                tickets_by_date[date_str].append(t)

            if locked_count > 0:
                 logger.info(f"Se descartaron {locked_count} tickets por reglas de semana cerrada.")

            if not tickets_by_date:
                logger.info("Tras el filtrado de bloqueo, no quedaron tickets viables para procesar.")
                self.send_telegram("Sin tickets procesables (Los pendientes estaban bloqueados por fecha).")
                return

            logger.info(f"Se detectaron tickets para {len(tickets_by_date)} dias diferentes.")
            self.send_telegram(f"Iniciando carga masiva. Dias a procesar: {', '.join(tickets_by_date.keys())}")

            try:
                self.bot.start_browser()
                
                for date_str, daily_tickets in sorted(tickets_by_date.items()):
                    logger.info(f"Procesando dia {date_str} ({len(daily_tickets)} tickets)...")
                    
                    # 2. Calcular distribucion para ESTE dia especifico
                    schedule_plan = self.timer.calculate_distributed_slots(daily_tickets)
                    
                    day_successful_ids = set()
                    skipped_ids = set()  # Tickets que superaron el máximo de reintentos
                    failure_counter = {}  # {ticket_id: int} — contador de fallos por ticket
                    MAX_FAILURES_PER_TICKET = 3
                    success_count = 0
                    
                    for item in schedule_plan:
                        ticket_id = item.get('ticket_id')
                        tid_str = str(ticket_id)
                        
                        # --- SKIP si este ticket ya fue marcado como irrecuperable ---
                        if tid_str in skipped_ids:
                            logger.info(f"Saltando slot de ticket {tid_str} (ya marcado como irrecuperable).")
                            continue
                        
                        try:
                            # Enriquecer metadata
                            raw_data = item.get('raw_ticket', {})
                            
                            if raw_data.get('source') == 'telegram':
                                item['client'] = raw_data.get('client') or self.defaults.get('client_fallback', 'Intelix')
                                item['project'] = raw_data.get('project') or self.defaults.get('project_fallback', 'Gestión - Intelix')
                                item['activity'] = raw_data.get('activity') or self.defaults.get('activity', 'Soporte')
                                item['tags'] = raw_data.get('tags') or self.defaults.get('tag', 'Soporte')
                                logger.info(f"Procesando ticket manual de Telegram: {ticket_id}")
                            else:
                                item.update(self._determine_ticket_metadata(raw_data))
                            
                            # Enviar a la web
                            if self.bot.fill_timesheet_entry(item):
                                day_successful_ids.add(tid_str)
                                success_count += 1
                                failure_counter.pop(tid_str, None)
                                logger.info(f"Registrado con exito [{date_str}]: {item['title']} (ID: {ticket_id})")
                            else:
                                failure_counter[tid_str] = failure_counter.get(tid_str, 0) + 1
                                logger.error(f"Fallo al registrar Ticket ID {ticket_id} en fecha {date_str} (intento {failure_counter[tid_str]}/{MAX_FAILURES_PER_TICKET})")
                                
                                if failure_counter[tid_str] >= MAX_FAILURES_PER_TICKET:
                                    logger.warning(f"TICKET IRRECUPERABLE: {ticket_id} falló {MAX_FAILURES_PER_TICKET} veces. Saltando todos sus slots restantes.")
                                    self.send_telegram(f"Ticket {ticket_id} falló {MAX_FAILURES_PER_TICKET} veces seguidas. Se omitió para continuar con los demás.")
                                    skipped_ids.add(tid_str)

                        except Exception as e:
                            logger.error(f"Error critico procesando Ticket ID {ticket_id}: {str(e)}")
                            failure_counter[tid_str] = failure_counter.get(tid_str, 0) + 1
                            
                            if failure_counter[tid_str] >= MAX_FAILURES_PER_TICKET:
                                logger.warning(f"TICKET IRRECUPERABLE (excepción): {ticket_id} falló {MAX_FAILURES_PER_TICKET} veces. Saltando.")
                                self.send_telegram(f"Ticket {ticket_id} falló {MAX_FAILURES_PER_TICKET} veces (error crítico). Omitido.")
                                skipped_ids.add(tid_str)
                            
                            # Intentar recuperar el navegador para que el siguiente ticket no falle en cascada
                            try:
                                logger.info("Intentando recuperar navegador tras excepción...")
                                self.bot.close_browser()
                                import time as _time
                                _time.sleep(2)
                                self.bot.start_browser()
                                logger.info("Navegador recuperado exitosamente.")
                            except Exception as recovery_err:
                                logger.error(f"No se pudo recuperar el navegador: {recovery_err}")
                                # Si no se puede recuperar, abortamos el día completo
                                self.send_telegram(f"Navegador no recuperable. Abortando procesamiento del día {date_str}.")
                                break
                            
                            continue
                    
                    # Marcar como procesados y eliminar de pendientes SOLO al final del bloque diario
                    for sid in day_successful_ids:
                        self.timer.mark_as_processed(sid)
                        self.local_db.remove_pending_ticket(sid)
                        successful_ids.add(sid)

                    logger.info(f"Completado dia {date_str}: {success_count} bloques registrados para {len(day_successful_ids)} tickets.")
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
            # Si solo era sync, terminamos
            if not force_now:
                logger.info("Sincronización finalizada. Saliendo de modo single-shot.")
                return

        self.routine_a()

        if force_now:
            logger.info("FORZANDO EJECUCIÓN INMEDIATA (Argumento detectado)")
            self.routine_b()
            # Si estabamos en modo sweep directo, terminamos
            logger.info("Ejecución manual finalizada. Saliendo de modo single-shot.")
            return
        
        while True:
            schedule.run_pending()
            time.sleep(60)

if __name__ == "__main__":
    pass
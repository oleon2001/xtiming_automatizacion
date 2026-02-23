from datetime import datetime, timedelta
import math
import json
import os
import logging

logger = logging.getLogger("TimeManager")

class TimeManager:
    """
    Clase principal para gestionar la planificación de tiempos y horarios (Time Boxing).
    Se encarga de distribuir las horas de trabajo entre los tickets asignados, 
    respetando los horarios de almuerzo y la duración total de la jornada.
    """
    def __init__(self, config=None, local_db=None):
        """
        Inicializa el TimeManager con la configuración proporcionada y la DB local.
        """
        self.schedule_config = config.get("schedule", {}) if config else {}
        self.local_db = local_db
        
        # Inicialización de variables de estado
        self._refresh_work_times()
        self.current_cursor = self.work_start
        self.daily_logged_minutes = 0
        self.processed_ids = set()
        
        # Lista básica de feriados (YYYY-MM-DD) - Se podría mover a config.json
        self.holidays = self.schedule_config.get("holidays", [])
        
        self.load_state()

    def _refresh_work_times(self, target_date=None):
        """Actualiza work_start, lunch_start y lunch_end a la fecha especificada o HOY."""
        dt = target_date if target_date else datetime.now()
        self.work_start = self._parse_time(self.schedule_config.get("work_start", "07:30"), dt)
        self.lunch_start = self._parse_time(self.schedule_config.get("lunch_start", "11:30"), dt)
        self.lunch_end = self._parse_time(self.schedule_config.get("lunch_end", "12:30"), dt)
        self.target_hours = self.schedule_config.get("target_hours", 8)

    def _parse_time(self, time_str, base_date=None):
        """
        Convierte una cadena de texto en formato 'HH:MM' a un objeto datetime con la fecha base.
        """
        dt = base_date if base_date else datetime.now()
        h, m = map(int, time_str.split(':'))
        return dt.replace(hour=h, minute=m, second=0, microsecond=0)

    def _format_time(self, dt):
        return dt.strftime("%d.%m.%Y %H:%M")

    def save_state(self):
        """
        Guarda el estado actual en la DB local.
        """
        if not self.local_db: return
        try:
            state = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "cursor": self.current_cursor.isoformat(),
                "logged_minutes": self.daily_logged_minutes
            }
            self.local_db.save_state("time_manager_cursor", state)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def load_state(self):
        """
        Carga el estado desde la DB local. Resetea si es un día nuevo.
        """
        if not self.local_db: return

        try:
            state = self.local_db.load_state("time_manager_cursor")
            if not state: 
                # Si no hay estado en DB, intentar resetear cursor
                self.reset_daily_cursor()
                return
            
            saved_date = state.get("date")
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            if saved_date == today_str:
                self.current_cursor = datetime.fromisoformat(state.get("cursor"))
                self.daily_logged_minutes = state.get("logged_minutes", 0)
                logger.info(f"Estado restaurado. Cursor: {self.current_cursor}, Logueado: {self.daily_logged_minutes}m")
            else:
                logger.info("Estado guardado es de un día anterior. Reseteando cursor.")
                self.reset_daily_cursor()
        except Exception as e:
            logger.error(f"Error loading state: {e}")

    def reset_daily_cursor(self):
        """Resetea el estado diario."""
        self._refresh_work_times()
        self.current_cursor = self.work_start
        self.daily_logged_minutes = 0
        self.save_state()

    def mark_as_processed(self, ticket_id):
        if self.local_db:
            self.local_db.mark_processed(ticket_id)

    def is_holiday(self, date_obj):
        if not date_obj: return False
        date_str = date_obj.strftime("%Y-%m-%d")
        return date_str in self.holidays

    def calculate_distributed_slots(self, tickets):
        """
        Redistribuye las horas objetivo equitativamente entre los tickets dados.
        """
        if not tickets:
            return []

        # Intentar extraer la fecha del primer ticket
        first_ticket_date = None
        # Para tickets de GLPI es 'solvedate', para manuales puede ser 'target_date'
        
        # Buscar fecha en el primer ticket disponible
        for t in tickets:
            sdate = t.get('solvedate') or t.get('target_date')
            if sdate:
                try:
                    if isinstance(sdate, str):
                        # Intentar formatos comunes
                        if len(sdate) >= 19:
                            first_ticket_date = datetime.strptime(sdate[:19], "%Y-%m-%d %H:%M:%S")
                        else:
                            first_ticket_date = datetime.strptime(sdate[:10], "%Y-%m-%d")
                    else:
                        first_ticket_date = sdate
                    break
                except:
                    continue
        
        if not first_ticket_date:
            first_ticket_date = datetime.now()

        # Validar feriados (si se implementara logica compleja, aqui iria)
        date_str = first_ticket_date.strftime("%Y-%m-%d")
        if self.is_holiday(first_ticket_date):
            logger.warning(f"La fecha {date_str} es feriado. No se planificarán horas.")
            return []

        self._refresh_work_times(target_date=first_ticket_date)
        
        # Separar manuales y automáticos
        manual_tickets = [t for t in tickets if t.get('source') == 'telegram' and 'manual_hours' in t]
        auto_tickets = [t for t in tickets if t not in manual_tickets]
        
        total_manual_min = sum(int(t['manual_hours'] * 60) for t in manual_tickets)
        target_minutes = self.target_hours * 60
        remaining_minutes = max(0, target_minutes - total_manual_min)
        
        logger.info(f"PLANIFICANDO JORNADA ({date_str}): {target_minutes} min totales.")
        logger.info(f"Fijos (Manuales): {total_manual_min} min. A distribuir: {remaining_minutes} min entre {len(auto_tickets)} tickets.")

        schedule_list = []
        # Reiniciar cursor al inicio del dia para calcular este batch especifico
        current_cursor = self.work_start
        
        # --- SMART ROUNDING CONSTANTS ---
        MIN_BLOCK_SIZE = 15 # No crear bloques menores a 15 min

        # Construir lista unificada para iterar
        all_tickets_ordered = manual_tickets + auto_tickets 

        for i, ticket in enumerate(all_tickets_ordered):
            if ticket.get('source') == 'telegram' and 'manual_hours' in ticket:
                total_ticket_duration = int(ticket['manual_hours'] * 60)
            else:
                # Distribuir los minutos restantes entre los automáticos
                count_auto = len(auto_tickets)
                if count_auto > 0:
                    base_auto = remaining_minutes // count_auto
                    # Distribuir el resto simple entre los primeros
                    rem_auto = remaining_minutes % count_auto
                    # Identificar indice dentro de auto_tickets para saber si le toca resto
                    idx_in_auto = auto_tickets.index(ticket)
                    total_ticket_duration = base_auto + (1 if idx_in_auto < rem_auto else 0)
                else:
                    total_ticket_duration = 0

            if total_ticket_duration <= 0:
                continue
            
            # --- DIVISIÓN INTELIGENTE EN SUB-BLOQUES ---
            # Si el ticket dura poco, no dividirlo
            if total_ticket_duration <= MIN_BLOCK_SIZE:
                blocks_count = 1
            else:
                blocks_count = 4 # Intentar 4 bloques por defecto
                # Ajustar si los bloques quedan muy pequeños (< 15 min)
                if (total_ticket_duration // blocks_count) < MIN_BLOCK_SIZE:
                    blocks_count = max(1, total_ticket_duration // MIN_BLOCK_SIZE)

            sub_base = total_ticket_duration // blocks_count
            sub_rem = total_ticket_duration % blocks_count
            
            for b in range(blocks_count):
                duration = sub_base + (1 if b < sub_rem else 0)
                if duration <= 0: continue

                start_dt = current_cursor
                
                # Normalizar inicio: Si cae en almuerzo, saltamos a 12:30
                if self.lunch_start <= start_dt < self.lunch_end:
                    start_dt = self.lunch_end

                tentative_end = start_dt + timedelta(minutes=duration)
                
                # Verificar solapamiento con Almuerzo
                # Caso: empieza antes y termina despues (atraviesa)
                if start_dt < self.lunch_start and tentative_end > self.lunch_start:
                    
                    # Parte 1: hasta inicio de almuerzo
                    duration_p1 = int((self.lunch_start - start_dt).total_seconds() / 60)
                    # Parte 2: resto
                    duration_p2 = duration - duration_p1
                    
                    if duration_p1 > 0:
                        schedule_list.append({
                            "ticket_id": ticket['ticket_id'],
                            "title": f"{ticket['ticket_title']}" + (f" ({b+1}.1)" if blocks_count > 1 else ""),
                            "start_time": self._format_time(start_dt),
                            "end_time": self._format_time(self.lunch_start),
                            "duration_min": duration_p1,
                            "raw_ticket": ticket
                        })
                        
                    current_cursor = self.lunch_end
                    
                    if duration_p2 > 0:
                        end_dt_p2 = current_cursor + timedelta(minutes=duration_p2)
                        schedule_list.append({
                            "ticket_id": ticket['ticket_id'],
                            "title": f"{ticket['ticket_title']}" + (f" ({b+1}.2)" if blocks_count > 1 else ""),
                            "start_time": self._format_time(current_cursor),
                            "end_time": self._format_time(end_dt_p2),
                            "duration_min": duration_p2,
                            "raw_ticket": ticket
                        })
                        current_cursor = end_dt_p2
                        
                else:
                    # Flujo normal
                    schedule_list.append({
                        "ticket_id": ticket['ticket_id'],
                        "title": f"{ticket['ticket_title']}" + (f" ({b+1})" if blocks_count > 1 else ""),
                        "start_time": self._format_time(start_dt),
                        "end_time": self._format_time(tentative_end),
                        "duration_min": duration,
                        "raw_ticket": ticket
                    })
                    current_cursor = tentative_end

        if schedule_list:
            last_entry = schedule_list[-1]
            logger.info(f"Planificación finalizada. Jornada termina a las: {last_entry['end_time']}")

        return schedule_list

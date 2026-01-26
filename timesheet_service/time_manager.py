import pickle
import os
import logging
from datetime import datetime, timedelta

STATE_FILE = "scheduler_state.pkl"
logger = logging.getLogger("TimeManager")

class TimeManager:
    def __init__(self, config):
        self.config = config
        self.schedule_cfg = config.get('schedule', {})
        
        # Horarios base desde config
        self.start_time_str = self.schedule_cfg.get("work_start", "08:30")
        self.lunch_start_str = self.schedule_cfg.get("lunch_start", "11:30")
        self.lunch_end_str = self.schedule_cfg.get("lunch_end", "12:30")
        self.target_hours = self.schedule_cfg.get("target_hours", 8)
        
        # Estado dinámico
        self.current_cursor = None
        self.daily_logged_minutes = 0
        self.processed_ids = set()
        
        # Inicializar (cargar estado o resetear si es nuevo día)
        self._initialize_state()

    def _parse_time_today(self, time_str):
        """Convierte HH:MM a datetime con la fecha de hoy."""
        now = datetime.now()
        h, m = map(int, time_str.split(':'))
        return now.replace(hour=h, minute=m, second=0, microsecond=0)

    def _initialize_state(self):
        """Carga el estado del disco o resetea si es un nuevo día."""
        default_start = self._parse_time_today(self.start_time_str)
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        state = self._load_state_from_disk()
        
        if state and state.get('date') == today_str:
            logger.info("Restaurando estado de sesión anterior del mismo día.")
            self.current_cursor = state.get('cursor', default_start)
            self.daily_logged_minutes = state.get('logged_minutes', 0)
            self.processed_ids = state.get('processed_ids', set())
        else:
            logger.info("Iniciando nuevo ciclo diario (Estado reseteado).")
            self.current_cursor = default_start
            self.daily_logged_minutes = 0
            self.processed_ids = set()
            self._save_state()

    def _load_state_from_disk(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "rb") as f:
                    return pickle.load(f)
            except Exception as e:
                logger.error(f"Error cargando estado: {e}")
        return None

    def _save_state(self):
        state = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "cursor": self.current_cursor,
            "logged_minutes": self.daily_logged_minutes,
            "processed_ids": self.processed_ids
        }
        try:
            with open(STATE_FILE, "wb") as f:
                pickle.dump(state, f)
        except Exception as e:
            logger.error(f"Error guardando estado: {e}")

    def get_processed_ids(self):
        return self.processed_ids

    def mark_as_processed(self, ticket_id):
        self.processed_ids.add(ticket_id)
        self._save_state()

    def _format_time(self, dt):
        return dt.strftime("%d.%m.%Y %H:%M")

    def calculate_ticket_slots(self, tickets):
        """
        Asigna slots de tiempo a los tickets. Actualiza el cursor y guarda estado.
        """
        schedule = []
        slot_duration = self.schedule_cfg.get("slot_duration_minutes", 30)
        
        lunch_start_dt = self._parse_time_today(self.lunch_start_str)
        lunch_end_dt = self._parse_time_today(self.lunch_end_str)
        
        for ticket in tickets:
            tid = ticket['ticket_id']
            if tid in self.processed_ids:
                continue

            start_dt = self.current_cursor
            
            # Lógica de Almuerzo: Si cae dentro o solapa el almuerzo, saltar al final
            if lunch_start_dt <= start_dt < lunch_end_dt:
                start_dt = lunch_end_dt
            
            end_dt = start_dt + timedelta(minutes=slot_duration)
            
            # Si el bloque termina dentro del almuerzo, empujamos todo después del almuerzo
            if start_dt < lunch_start_dt and end_dt > lunch_start_dt:
                start_dt = lunch_end_dt
                end_dt = start_dt + timedelta(minutes=slot_duration)
            
            # Actualizamos cursor y métricas
            self.current_cursor = end_dt
            self.daily_logged_minutes += slot_duration
            
            schedule.append({
                "ticket_id": tid,
                "title": ticket['ticket_title'],
                "start_time": self._format_time(start_dt),
                "end_time": self._format_time(end_dt),
                "duration_min": slot_duration,
                # Pasamos datos crudos para que el Scheduler decida metadata
                "raw_ticket": ticket 
            })
            
            # Guardamos estado tras calcular el slot (aunque aún no se confirme en web)
            # Nota: Idealmente se confirma tras éxito web, pero para simplificar el flujo
            # actualizamos el cursor aquí. La confirmación de ID procesado se hace fuera.
            self._save_state()
            
        return schedule

    def get_remaining_minutes(self):
        target_minutes = self.target_hours * 60
        return max(0, target_minutes - self.daily_logged_minutes)

    def calculate_adjustment_entry(self):
        missing = self.get_remaining_minutes()
        if missing <= 0:
            return None
            
        start_dt = self.current_cursor
        lunch_start_dt = self._parse_time_today(self.lunch_start_str)
        lunch_end_dt = self._parse_time_today(self.lunch_end_str)

        if lunch_start_dt <= start_dt < lunch_end_dt:
            start_dt = lunch_end_dt
            
        end_dt = start_dt + timedelta(minutes=missing)
        
        return {
            "title": "Ajuste de Jornada",
            "start_time": self._format_time(start_dt),
            "end_time": self._format_time(end_dt),
            "duration_min": missing
        }
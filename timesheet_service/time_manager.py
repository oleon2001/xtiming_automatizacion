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
    def __init__(self, config=None):
        """
        Inicializa el TimeManager con la configuración proporcionada.
        """
        self.schedule_config = config.get("schedule", {}) if config else {}
        
        # Configuración del directorio de datos (Carpeta hermana en despliegue)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.abspath(os.path.join(base_dir, "..", "timesheet_data"))
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.state_file = os.path.join(self.data_dir, "time_manager_state.json")
        self.processed_file = os.path.join(self.data_dir, "processed_tickets.idx")
        
        # Inicialización de variables de estado
        self._refresh_work_times()
        self.current_cursor = self.work_start
        self.daily_logged_minutes = 0
        self.processed_ids = set()
        
        self.load_state()
        self.load_processed_ids()

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
        Guarda el estado actual (cursor de tiempo y minutos logueados) en un archivo JSON.
        Esto permite reanudar la planificación si el script se interrumpe.
        """
        try:
            state = {
                "date": datetime.now().strftime("%Y-%m-%d"), # Fecha para validar si el estado es de hoy
                "cursor": self.current_cursor.isoformat(),   # Dónde nos quedamos planificando
                "logged_minutes": self.daily_logged_minutes  # Cuánto llevamos acumulado
            }
            with open(self.state_file, "w") as f:
                json.dump(state, f)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def load_state(self):
        """
        Carga el estado desde el archivo JSON si existe y corresponde a la fecha de hoy.
        Si el estado es de un día anterior, resetea todo para empezar un nuevo día limpio.
        """
        if not os.path.exists(self.state_file):
            return

        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
            
            saved_date = state.get("date")
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            if saved_date == today_str:
                # Si es de hoy, restauramos el cursor y acumuladores
                self.current_cursor = datetime.fromisoformat(state.get("cursor"))
                self.daily_logged_minutes = state.get("logged_minutes", 0)
                logger.info(f"Estado restaurado. Cursor: {self.current_cursor}, Logueado: {self.daily_logged_minutes}m")
            else:
                # Si es de ayer, reseteamos para empezar de cero
                logger.info("Estado guardado es de un día anterior. Reseteando cursor.")
                self.reset_daily_cursor() # Ensure clean slate
        except Exception as e:
            logger.error(f"Error loading state: {e}")

    def load_processed_ids(self):
        """Load processed ticket IDs from disk."""
        if not os.path.exists(self.processed_file):
            return

        try:
            with open(self.processed_file, "r") as f:
                lines = f.readlines()
            self.processed_ids = {line.strip() for line in lines if line.strip()}
            logger.info(f"Loaded {len(self.processed_ids)} processed tickets.")
        except Exception as e:
            logger.error(f"Error loading processed IDs: {e}")

    def reset_daily_cursor(self):
        """
        Resetea el estado diario. Pone el cursor al inicio de la jornada (ej. 07:30)
        y borra el registro de tickets procesados para permitir procesar nuevos.
        """
        self._refresh_work_times()
        self.current_cursor = self.work_start
        self.daily_logged_minutes = 0
        self.processed_ids = set()
        self.save_state()
        
        # Limpia el archivo de tickets procesados para el nuevo día
        try:
            open(self.processed_file, 'w').close()
            logger.info("Reseteo diario: processed_tickets.idx limpiado.")
        except Exception as e:
            logger.error(f"Error clearing processed file: {e}")

    def calculate_ticket_slots(self, tickets, processed_ids=None):
        """
        Asigna tiempos a una lista de tickets de manera dinámica (Rutina A).
        Asume una duración fija por defecto (30 mins) por ticket.
        """
        self._refresh_work_times()
        schedule = []
        DEFAULT_DURATION_MINUTES = 30
        
        # Fusionar IDs procesados previamente con los que se pasen como argumento
        effective_processed = self.processed_ids.copy()
        if processed_ids:
            effective_processed.update(processed_ids)
        
        for ticket in tickets:
            t_id = str(ticket['ticket_id'])
            if t_id in effective_processed:
                continue # Saltar si ya fue procesado

            start_dt = self.current_cursor
            
            # Si el cursor es de un día anterior al refresh, lo forzamos al work_start de hoy
            if start_dt < self.work_start:
                start_dt = self.work_start

            # --- Lógica de Almuerzo ---
            # Si el inicio cae dentro del almuerzo [11:30, 12:30), movemos el inicio a 12:30
            if self.lunch_start <= start_dt < self.lunch_end:
                start_dt = self.lunch_end
            
            end_dt = start_dt + timedelta(minutes=DEFAULT_DURATION_MINUTES)
            
            # Si el bloque TERMINA después de que inició el almuerzo (solapamiento), 
            # movemos TODO el bloque para después del almuerzo.
            if start_dt < self.lunch_start and end_dt > self.lunch_start:
                start_dt = self.lunch_end
                end_dt = start_dt + timedelta(minutes=DEFAULT_DURATION_MINUTES)
            
            # Actualizamos cursor y acumuladores
            self.current_cursor = end_dt
            self.daily_logged_minutes += DEFAULT_DURATION_MINUTES
            self.save_state() # Guardar después de cada paso para seguridad
            
            schedule.append({
                "ticket_id": ticket['ticket_id'],
                "title": ticket['ticket_title'],
                "start_time": self._format_time(start_dt),
                "end_time": self._format_time(end_dt),
                "duration_min": DEFAULT_DURATION_MINUTES,
                "raw_ticket": ticket
            })
            
        return schedule

    def get_remaining_minutes(self):
        target_minutes = self.target_hours * 60
        return max(0, target_minutes - self.daily_logged_minutes)

    def calculate_adjustment_entry(self):
        # Logic for Routine B
        missing = self.get_remaining_minutes()
        
        if missing <= 0:
            return None
            
        # Find next valid start time
        start_dt = self.current_cursor
        if self.lunch_start <= start_dt < self.lunch_end:
            start_dt = self.lunch_end
            
        end_dt = start_dt + timedelta(minutes=missing)
        
        return {
            "title": "Ajuste de Jornada",
            "start_time": self._format_time(start_dt),
            "end_time": self._format_time(end_dt),
            "duration_min": missing
        }

    def _add_minutes_skipping_lunch(self, start_dt, minutes):
        """Calculates end time respecting lunch break logic."""
        # 1. Tentative end
        end_dt = start_dt + timedelta(minutes=minutes)
        
        # 2. Check overlap with lunch
        # Case A: Starts before lunch, ends after lunch start
        if start_dt < self.lunch_start and end_dt > self.lunch_start:
            overlap = end_dt - self.lunch_start
            # Shift the entire overlap duration to after lunch
            return self.lunch_end + overlap
        
        # Case B: Starts inside lunch (shouldn't happen if logic is correct, but safe guard)
        if self.lunch_start <= start_dt < self.lunch_end:
            remaining = minutes
            return self.lunch_end + timedelta(minutes=remaining)
            
        return end_dt

    def calculate_distributed_slots(self, tickets):
        """
        Redistribuye las horas objetivo equitativamente entre los tickets dados.
        Detecta la fecha del primer ticket para establecer el dia de registro.
        """
        if not tickets:
            return []

        # Intentar extraer la fecha del primer ticket para normalizar la jornada
        first_ticket_date = None
        if 'solvedate' in tickets[0]:
            try:
                # El formato de solvedate en GLPI suele ser YYYY-MM-DD HH:MM:SS
                sdate = tickets[0]['solvedate']
                if isinstance(sdate, str):
                    first_ticket_date = datetime.strptime(sdate, "%Y-%m-%d %H:%M:%S")
                else:
                    first_ticket_date = sdate
            except:
                pass

        self._refresh_work_times(target_date=first_ticket_date)
        
        # Separar tickets con horas manuales vs automáticos
        manual_tickets = [t for t in tickets if t.get('source') == 'telegram' and 'manual_hours' in t]
        auto_tickets = [t for t in tickets if t not in manual_tickets]
        
        total_manual_min = sum(int(t['manual_hours'] * 60) for t in manual_tickets)
        target_minutes = self.target_hours * 60
        remaining_minutes = max(0, target_minutes - total_manual_min)
        
        logger.info(f"PLANIFICANDO JORNADA: {target_minutes} min totales.")
        logger.info(f"Fijos (Manuales): {total_manual_min} min. A distribuir: {remaining_minutes} min entre {len(auto_tickets)} tickets.")

        schedule_list = []
        current_cursor = self.work_start
        
        # Procesar todos los tickets (primero manuales para asegurar su espacio, luego auto)
        # O mantener orden original? Mejor mantener orden para respetar la cronología del día si existiera.
        # Pero como routine_b es al final del día, el orden da un poco igual.
        
        for i, ticket in enumerate(tickets):
            if ticket.get('source') == 'telegram' and 'manual_hours' in ticket:
                total_ticket_duration = int(ticket['manual_hours'] * 60)
            else:
                # Distribuir los minutos restantes entre los automáticos
                count_auto = len(auto_tickets)
                if count_auto > 0:
                    # Encontrar qué índice de auto_ticket es este
                    idx_auto = auto_tickets.index(ticket)
                    base_auto = remaining_minutes // count_auto
                    rem_auto = remaining_minutes % count_auto
                    total_ticket_duration = base_auto + (1 if idx_auto < rem_auto else 0)
                else:
                    total_ticket_duration = 0

            if total_ticket_duration <= 0:
                continue
            
            # --- DIVISIÓN EN 4 SUB-BLOQUES ---
            # Dividimos la duración total del ticket en 4 partes
            BLOCKS = 4
            sub_base = total_ticket_duration // BLOCKS
            sub_rem = total_ticket_duration % BLOCKS
            
            for b in range(BLOCKS):
                # Calculamos duración de este sub-bloque
                duration = sub_base + (1 if b < sub_rem else 0)
                if duration <= 0: continue

                start_dt = current_cursor
                
                # Normalizar inicio: Si cae en almuerzo, saltamos a 12:30
                if self.lunch_start <= start_dt < self.lunch_end:
                    logger.debug(f"Salto de almuerzo detectado al inicio: {self._format_time(start_dt)} -> {self._format_time(self.lunch_end)}")
                    start_dt = self.lunch_end

                tentative_end = start_dt + timedelta(minutes=duration)
                
                # Verificar solapamiento con Almuerzo: Empieza ANTES y Termina DESPUÉS
                if start_dt < self.lunch_start and tentative_end > self.lunch_start:
                    # CASO: El bloque atraviesa el almuerzo. Lo dividimos en 2 partes.
                    logger.info(f"Ticket {ticket['ticket_id']} (Bloque {b+1}) se divide por almuerzo.")
                    
                    # Parte 1: Desde inicio hasta inicio de almuerzo
                    duration_p1 = int((self.lunch_start - start_dt).total_seconds() / 60)
                    duration_p2 = duration - duration_p1
                    
                    # Agregar Parte 1
                    if duration_p1 > 0:
                        schedule_list.append({
                            "ticket_id": ticket['ticket_id'],
                            "title": f"{ticket['ticket_title']} (Bloque {b+1}.1)",
                            "start_time": self._format_time(start_dt),
                            "end_time": self._format_time(self.lunch_start),
                            "duration_min": duration_p1,
                            "raw_ticket": ticket
                        })
                        
                    current_cursor = self.lunch_end # Resetear cursor post-almuerzo
                    
                    # Agregar Parte 2 (lo que sobra del bloque)
                    if duration_p2 > 0:
                        end_dt_p2 = current_cursor + timedelta(minutes=duration_p2)
                        schedule_list.append({
                            "ticket_id": ticket['ticket_id'],
                            "title": f"{ticket['ticket_title']} (Bloque {b+1}.2)",
                            "start_time": self._format_time(current_cursor),
                            "end_time": self._format_time(end_dt_p2),
                            "duration_min": duration_p2,
                            "raw_ticket": ticket
                        })
                        current_cursor = end_dt_p2
                        
                else:
                    # CASO: Flujo lineal normal (sin intersección con almuerzo)
                    schedule_list.append({
                        "ticket_id": ticket['ticket_id'],
                        "title": f"{ticket['ticket_title']} (Bloque {b+1})",
                        "start_time": self._format_time(start_dt),
                        "end_time": self._format_time(tentative_end),
                        "duration_min": duration,
                        "raw_ticket": ticket
                    })
                    current_cursor = tentative_end

        # Final Log Summary
        if schedule_list:
            last_entry = schedule_list[-1]
            logger.info(f"Planificación finalizada. Jornada termina a las: {last_entry['end_time']}")

        return schedule_list

    def mark_as_processed(self, ticket_id):
        t_id = str(ticket_id)
        if t_id in self.processed_ids:
            return

        self.processed_ids.add(t_id)
        logger.debug(f"Ticket {t_id} marked as processed.")
        
        try:
            with open(self.processed_file, "a") as f:
                f.write(f"{t_id}\n")
        except Exception as e:
            logger.error(f"Error appending to processed index: {e}")

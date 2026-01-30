from datetime import datetime, timedelta
import math
import json
import os
import logging

logger = logging.getLogger("TimeManager")

class TimeManager:
    def __init__(self, config=None):
        schedule_config = config.get("schedule", {}) if config else {}
        
        # Data directory configuration
        self.data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.state_file = os.path.join(self.data_dir, "time_manager_state.json")
        self.processed_file = os.path.join(self.data_dir, "processed_tickets.idx")
        
        self.work_start = self._parse_time(schedule_config.get("work_start", "07:30"))
        self.lunch_start = self._parse_time(schedule_config.get("lunch_start", "11:30"))
        self.lunch_end = self._parse_time(schedule_config.get("lunch_end", "12:30"))
        self.target_hours = schedule_config.get("target_hours", 8)
        
        # Initialize defaults
        self.current_cursor = self.work_start
        self.daily_logged_minutes = 0
        self.processed_ids = set()
        
        # Load state and processed IDs
        self.load_state()
        self.load_processed_ids()

    def _parse_time(self, time_str):
        # Parses HH:MM to a datetime object (using today's date)
        now = datetime.now()
        h, m = map(int, time_str.split(':'))
        return now.replace(hour=h, minute=m, second=0, microsecond=0)

    def _format_time(self, dt):
        return dt.strftime("%d.%m.%Y %H:%M")

    def save_state(self):
        """Persist current cursor and logged minutes to disk."""
        try:
            state = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "cursor": self.current_cursor.isoformat(),
                "logged_minutes": self.daily_logged_minutes
            }
            with open(self.state_file, "w") as f:
                json.dump(state, f)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def load_state(self):
        """Load state if it matches today's date."""
        if not os.path.exists(self.state_file):
            return

        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
            
            saved_date = state.get("date")
            today_str = datetime.now().strftime("%Y-%m-%d")
            
            if saved_date == today_str:
                self.current_cursor = datetime.fromisoformat(state.get("cursor"))
                self.daily_logged_minutes = state.get("logged_minutes", 0)
                logger.info(f"State restored. Cursor: {self.current_cursor}, Logged: {self.daily_logged_minutes}m")
            else:
                logger.info("Saved state is from a previous day. Resetting cursor.")
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
        """Resets the daily state and clears processed tickets log."""
        self.current_cursor = self.work_start
        self.daily_logged_minutes = 0
        self.processed_ids = set()
        self.save_state()
        
        # Clear the processed tickets file for the new day
        try:
            open(self.processed_file, 'w').close()
            logger.info("Daily reset: processed_tickets.idx cleared.")
        except Exception as e:
            logger.error(f"Error clearing processed file: {e}")

    def calculate_ticket_slots(self, tickets, processed_ids=None):
        """
        Assigns time slots to tickets dynamically.
        Assumption: 30 mins per ticket default.
        """
        schedule = []
        DEFAULT_DURATION_MINUTES = 30
        
        # Merge passed processed_ids with internal state
        effective_processed = self.processed_ids.copy()
        if processed_ids:
            effective_processed.update(processed_ids)
        
        for ticket in tickets:
            t_id = str(ticket['ticket_id'])
            if t_id in effective_processed:
                continue

            start_dt = self.current_cursor
            
            # Check Lunch Constraint logic:
            # If start is in lunch [11:30, 12:30), move to 12:30
            if self.lunch_start <= start_dt < self.lunch_end:
                start_dt = self.lunch_end
            
            end_dt = start_dt + timedelta(minutes=DEFAULT_DURATION_MINUTES)
            
            # If end overlaps lunch (e.g. 11:15 to 11:45), move whole block to after lunch
            if start_dt < self.lunch_start and end_dt > self.lunch_start:
                start_dt = self.lunch_end
                end_dt = start_dt + timedelta(minutes=DEFAULT_DURATION_MINUTES)
            
            # Update cursor and log
            self.current_cursor = end_dt
            self.daily_logged_minutes += DEFAULT_DURATION_MINUTES
            self.save_state() # Save after every calculation step
            
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
        Redistributes the target hours evenly across all provided tickets using integers only.
        Ensures the total sum is exactly target_hours * 60.
        Splits tickets that overlap with lunch into two entries.
        """
        if not tickets:
            return []

        target_minutes = self.target_hours * 60
        count = len(tickets)
        
        # Exact integer distribution:
        base_minutes = target_minutes // count
        remainder = target_minutes % count
        
        logger.info(f"PLANIFICANDO JORNADA: {target_minutes} min / {count} tickets = {base_minutes} min base (+{remainder} residual)")
        logger.info(f"Rango Configurado: {self._format_time(self.work_start)} -> Fin (según carga) | Almuerzo: {self._format_time(self.lunch_start)}-{self._format_time(self.lunch_end)}")
        
        schedule_list = []
        current_cursor = self.work_start
        
        for i, ticket in enumerate(tickets):
            # Distribute remainder: first 'remainder' tickets get an extra minute
            duration = base_minutes + (1 if i < remainder else 0)
            
            start_dt = current_cursor
            
            # CRITICAL: Always normalize start time before calculating end
            # If start is inside lunch window [11:30, 12:30), jump to 12:30
            if self.lunch_start <= start_dt < self.lunch_end:
                logger.debug(f"Salto de almuerzo detectado al inicio: {self._format_time(start_dt)} -> {self._format_time(self.lunch_end)}")
                start_dt = self.lunch_end

            tentative_end = start_dt + timedelta(minutes=duration)
            
            # Check for lunch overlap: Starts BEFORE lunch AND Ends AFTER lunch starts
            # (Strict > check ensures we don't split if it ends EXACTLY at 11:30)
            if start_dt < self.lunch_start and tentative_end > self.lunch_start:
                # SPLIT LOGIC
                logger.info(f"Ticket {ticket['ticket_id']} se divide por almuerzo.")
                
                # Part 1: Start to Lunch Start
                duration_p1 = int((self.lunch_start - start_dt).total_seconds() / 60)
                
                # Part 2: Remainder
                duration_p2 = duration - duration_p1
                
                # Entry 1
                if duration_p1 > 0:
                    schedule_list.append({
                        "ticket_id": ticket['ticket_id'],
                        "title": f"{ticket['ticket_title']} (Parte 1)",
                        "start_time": self._format_time(start_dt),
                        "end_time": self._format_time(self.lunch_start),
                        "duration_min": duration_p1,
                        "raw_ticket": ticket
                    })
                
                # Entry 2 (starts after lunch)
                start_dt_p2 = self.lunch_end
                end_dt_p2 = start_dt_p2 + timedelta(minutes=duration_p2)
                
                if duration_p2 > 0:
                    schedule_list.append({
                        "ticket_id": ticket['ticket_id'],
                        "title": f"{ticket['ticket_title']} (Parte 2)",
                        "start_time": self._format_time(start_dt_p2),
                        "end_time": self._format_time(end_dt_p2),
                        "duration_min": duration_p2,
                        "raw_ticket": ticket
                    })
                
                # Actualizamos el cursor global al final de la parte 2
                current_cursor = end_dt_p2
                
            else:
                # LINEAR FLOW (No split)
                schedule_list.append({
                    "ticket_id": ticket['ticket_id'],
                    "title": ticket['ticket_title'],
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

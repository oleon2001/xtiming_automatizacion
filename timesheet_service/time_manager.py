from datetime import datetime, timedelta
import math

class TimeManager:
    def __init__(self, start_time_str="08:30"):
        self.work_start = self._parse_time(start_time_str)
        self.lunch_start = self._parse_time("11:30")
        self.lunch_end = self._parse_time("12:30")
        self.target_hours = 8
        self.current_cursor = self.work_start
        self.daily_logged_minutes = 0

    def _parse_time(self, time_str):
        # Parses HH:MM to a datetime object (using today's date)
        now = datetime.now()
        h, m = map(int, time_str.split(':'))
        return now.replace(hour=h, minute=m, second=0, microsecond=0)

    def _format_time(self, dt):
        return dt.strftime("%H:%M")

    def reset_daily_cursor(self):
        self.current_cursor = self.work_start
        self.daily_logged_minutes = 0

    def calculate_ticket_slots(self, tickets, processed_ids=[]):
        """
        Assigns time slots to tickets dynamically.
        Assumption: 30 mins per ticket default.
        """
        schedule = []
        DEFAULT_DURATION_MINUTES = 30
        
        for ticket in tickets:
            if ticket['ticket_id'] in processed_ids:
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
            
            # Check if we exceeded the day? (Example: past 18:00?)
            # Validating "logic" requires not going too late, but for now we just append.
            
            # Update cursor and log
            self.current_cursor = end_dt
            self.daily_logged_minutes += DEFAULT_DURATION_MINUTES
            
            schedule.append({
                "ticket_id": ticket['ticket_id'],
                "title": ticket['ticket_title'],
                "start_time": self._format_time(start_dt),
                "end_time": self._format_time(end_dt),
                "duration_min": DEFAULT_DURATION_MINUTES
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

import time
import schedule
import pickle
import os
from datetime import datetime
import db_handler
import time_manager
import web_automator
import requests

PROCESSED_FILE = "processed_tickets.pkl"

class SchedulerService:
    def __init__(self):
        self.db = db_handler.DBHandler()
        self.timer = time_manager.TimeManager()
        self.bot = web_automator.WebAutomator()
        self.processed_tickets = self._load_processed()

    def _load_processed(self):
        if os.path.exists(PROCESSED_FILE):
            try:
                with open(PROCESSED_FILE, "rb") as f:
                    return pickle.load(f)
            except:
                return set()
        return set()

    def _save_processed(self):
        with open(PROCESSED_FILE, "wb") as f:
            pickle.dump(self.processed_tickets, f)

    def send_telegram(self, msg):
        token = os.getenv("TG_BOT_TOKEN")
        chat_id = os.getenv("TG_CHAT_ID")
        if token and chat_id:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": msg})

    def routine_a(self):
        print(f"Running Routine A: {datetime.now()}")
        tickets = self.db.fetch_closed_tickets_today()
        if not tickets:
            print("No tickets found today.")
            return

        schedule_plan = self.timer.calculate_ticket_slots(tickets, self.processed_tickets)
        
        for item in schedule_plan:
            try:
                self.bot.fill_timesheet_entry(item)
                self.processed_tickets.add(item['ticket_id'])
                self._save_processed()
                self.send_telegram(f" Ticket registrado: {item['title']} ({item['duration_min']} min)")
            except Exception as e:
                print(f"Failed to process ticket {item['ticket_id']}: {e}")
                self.send_telegram(f" Error registrando ticket {item['ticket_id']}: {e}")

    def routine_b(self):
        print(f"Running Routine B (Daily Close): {datetime.now()}")
        adjustment = self.timer.calculate_adjustment_entry()
        
        if adjustment:
             try:
                self.bot.fill_timesheet_entry(adjustment)
                self.send_telegram(f" Ajuste de jornada registrado: {adjustment['duration_min']} min para completar 8h.")
             except Exception as e:
                self.send_telegram(f" Error registrando ajuste: {e}")
        else:
            self.send_telegram(" Jornada completa. No se requiere ajuste.")
            
        # Limpieza para el próximo día
        print("Limpiando tickets procesados para el nuevo día...")
        self.processed_tickets = set()
        self._save_processed()
        self.timer.reset_daily_cursor()

    def run(self):
        # Schedule Routine A every 2 hours
        schedule.every(2).hours.do(self.routine_a)
        
        # Schedule Routine B at 18:00
        schedule.every().day.at("18:00").do(self.routine_b)
        
        print("Scheduler Started...")
        while True:
            schedule.run_pending()
            time.sleep(60)

if __name__ == "__main__":
    svc = SchedulerService()
    svc.routine_a() # Test run

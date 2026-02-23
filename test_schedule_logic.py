import sys
import os
import logging
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from timesheet_service.time_manager import TimeManager

# Setup basic config
config = {
    "schedule": {
        "work_start": "07:30",
        "lunch_start": "11:30",
        "lunch_end": "12:30",
        "target_hours": 8
    }
}

def test_schedule():
    tm = TimeManager(config)
    # Dummy ticket
    tickets = [{"ticket_id": 100, "ticket_title": "Test Ticket"}]
    
    print("--- Calculating Schedule for 1 Ticket ---")
    schedule = tm.calculate_distributed_slots(tickets)
    
    for item in schedule:
        print(f"Block: {item['title']} | Start: {item['start_time']} | End: {item['end_time']} | Duration: {item['duration_min']}")
        
    print(f"Total Blocks: {len(schedule)}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    test_schedule()

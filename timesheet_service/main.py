import os
import sys
from dotenv import load_dotenv

# Ensure we can import modules from current directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from scheduler_service import SchedulerService
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Ensure you are running this script from the 'timesheet_service' directory or that requirements are installed.")
    sys.exit(1)

def main():
    # Load environment variables
    # Assuming .env is in the same directory
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    load_dotenv(env_path)
    
    print("Starting Timesheet Automation Service v2.0")
    print(f"Loading configuration from {env_path}")
    
    service = SchedulerService()
    try:
        service.run()
    except KeyboardInterrupt:
        print("\nService stopped by user.")
    except Exception as e:
        print(f"Critical error: {e}")
        # Optionally send telegram notification of crash?
        # service.send_telegram(f"CRASH: {e}") 
        raise

if __name__ == "__main__":
    main()

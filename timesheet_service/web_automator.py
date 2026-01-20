from playwright.sync_api import sync_playwright
import os
import time

class WebAutomator:
    def __init__(self):
        self.user = os.getenv("XTIMING_USER")
        self.password = os.getenv("XTIMING_PASSWORD")
        self.base_url = "https://xtiming.intelix.biz/index.php/es"
        # Defaults
        self.default_client = os.getenv("DEFAULT_CLIENT", "INTELIX")
        self.default_service = os.getenv("DEFAULT_SERVICE_TYPE", "SOPORTE")
        self.default_activity = os.getenv("DEFAULT_ACTIVITY", "REMOTO")
        
    def login(self, page):
        print("INICIAMOS SESION PARA MENTIR!")
        page.goto(f"{self.base_url}/login")
        
        # Fill credentials
        # Selectors assumed based on standard forms. Will need adjustment if IDs differ.
        page.fill("input[name='username']", self.user)
        page.fill("input[name='password']", self.password)
        page.click("button[type='submit']")
        page.wait_for_load_state('networkidle')
        
        # Verify login success (e.g. check for logout button or dashboard)
        if "login" in page.url:
             raise Exception("Fallo en el login. Verifique credenciales.")
        print("Login exitoso.")

    def fill_timesheet_entry(self, entry_data):
        """
        entry_data dict:
          - title
          - start_time (HH:MM)
          - end_time (HH:MM)
          - glpi_id (optional)
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False) # Headless=False for visual debugging/verification
            page = browser.new_page()
            
            try:
                self.login(page)
                
                print(f"Registrando entrada: {entry_data['title']}")
                page.goto(f"{self.base_url}/timesheet/create")
                
                # Filling the form
                # Mapping fields based on description. 
                # "Ticket GLPI": Insertar ID
                if 'ticket_id' in entry_data:
                    # Look for input for GLPI Ticket. 
                    # Assuming a label 'Ticket' or 'GLPI' exists, or input name.
                    # Using placeholder selectors that need to be verified.
                    # page.fill("input[name='ticket_id']", str(entry_data['ticket_id']))
                    # For robustness, we try to find by label if possible, or generic name.
                    # We will assume standard names: 'ticket', 'description', etc.
                    pass 

                # Descripción (Title)
                page.fill("textarea[name='description']", entry_data['title']) # Description usually textarea?
                
                # Horarios
                # Assuming inputs are type time or text
                page.fill("input[name='start_time']", entry_data['start_time'])
                page.fill("input[name='end_time']", entry_data['end_time'])
                
                # Selects
                # page.select_option("select[name='customer_id']", label=self.default_client)
                # page.select_option("select[name='service_type']", label=self.default_service)
                # page.select_option("select[name='activity_id']", label=self.default_activity)
                
                # Submit
                page.click("button[type='submit']")
                page.wait_for_load_state('networkidle')
                
                print(f"Entrada registrada: {entry_data['title']}")
                return True

            except Exception as e:
                print(f"Error registrando entrada en web: {e}")
                raise e
            finally:
                browser.close()

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    svc = WebAutomator()
    svc.fill_timesheet_entry({
        "title": "Test Entry",
        "start_time": "08:00",
        "end_time": "09:00",
    })
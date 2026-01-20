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
        
        
        page.fill("input[name='_username']", self.user)
        page.fill("input[name='_password']", self.password)
        page.click("button[type='submit']")
        page.wait_for_load_state('networkidle')
        
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
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            
            try:
                self.login(page)
                
                print(f"Registrando mentiras: {entry_data['title']}")
                page.goto(f"{self.base_url}/timesheet/create")
                
                
                if 'ticket_id' in entry_data:
                    
                    pass 

                # descripcion del titulo 
                page.fill("textarea[name='description']", entry_data['title']) # Description usually textarea?
                
                # Horarios
                # Assuming inputs are type time or text
                page.fill("input[name='timesheet_edit_form[begin]']", entry_data['timesheet_edit_form_begin'])
                page.fill("input[name='timesheet_edit_form[end]']", entry_data['timesheet_edit_form_end'])

                #cliente
                page.select_opcion("input[name='timesheet_edit_form[begin]']", entry_data['timesheet_edit_form_begin'])

                #tipo de servicio
                page.select_option("input[name='timesheet_edit_form[end]']", entry_data['timesheet_edit_form_end'])

                #actividad
                page.select_option("input[name='timesheet_edit_form[end]']", entry_data['timesheet_edit_form_end'])

                #etiquetas
                page.select_option("input[name='timesheet_edit_form[end]']", entry_data['timesheet_edit_form_end'])

                #

                
                
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
        "timesheet_edit_form_begin": "08:00",
        "timesheet_edit_form_end": "09:00",
    })
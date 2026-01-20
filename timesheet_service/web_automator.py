from playwright.sync_api import sync_playwright
import os
import time

class WebAutomator:
    def __init__(self):
        self.user = os.getenv("XTIMING_USER")
        self.password = os.getenv("XTIMING_PASSWORD")
        self.base_url = "https://xtiming.intelix.biz/index.php/es"
        # Valores por defecto desde .env
        self.default_client = os.getenv("DEFAULT_CLIENT", "Intelix")
        self.default_project = os.getenv("DEFAULT_PROJECT", "Gestión - Intelix")
        self.default_activity = os.getenv("DEFAULT_ACTIVITY", "Soporte")
        self.default_tag = os.getenv("DEFAULT_TAG", "Soporte")
        
    def login(self, page):
        print(f"Iniciando sesión para {self.user}...")
        page.goto(f"{self.base_url}/login")
        page.fill("input[name='_username']", self.user)
        page.fill("input[name='_password']", self.password)
        page.click("button[type='submit']")
        page.wait_for_load_state('networkidle')
        
        if "login" in page.url:
             raise Exception("Fallo en el login. Verifique credenciales.")
        print(" Login exitoso.")

    def fill_timesheet_entry(self, entry_data):
        """
        entry_data dict:
          - title
          - start_time (DD.MM.YYYY HH:MM)
          - end_time (DD.MM.YYYY HH:MM)
          - ticket_id (opcional)
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False) 
            context = browser.new_context()
            page = context.new_page()
            
            try:
                self.login(page)
                
                print(f"Registrando: {entry_data['title']} [{entry_data['start_time']} - {entry_data['end_time']}]")
                page.goto(f"{self.base_url}/timesheet/create")
                page.wait_for_load_state('networkidle')

                # 1. Fechas y Horas
                page.fill("#timesheet_edit_form_begin", entry_data['start_time'])
                page.press("#timesheet_edit_form_begin", "Enter")
                
                page.fill("#timesheet_edit_form_end", entry_data['end_time'])
                page.press("#timesheet_edit_form_end", "Enter")

                # 2. Selección de Cliente (Select2)
                # Kimai usa Select2, a veces select_option funciona directamente sobre el select oculto
                page.select_option("#timesheet_edit_form_customer", label=self.default_client)
                
                # 3. Selección de Proyecto (Depende del cliente, hay que esperar a que cargue)
                time.sleep(1) # Pequeña espera para que el API de Kimai cargue los proyectos
                page.select_option("#timesheet_edit_form_project", label=self.default_project)

                # 4. Selección de Actividad (Depende del proyecto)
                time.sleep(1)
                page.select_option("#timesheet_edit_form_activity", label=self.default_activity)

                # 5. Descripción
                page.fill("#timesheet_edit_form_description", entry_data['title'])

                # 6. Etiquetas (Multiselect)
                try:
                    page.select_option("#timesheet_edit_form_tags", label=self.default_tag)
                except:
                    print("Warn: No se pudo seleccionar la etiqueta por defecto.")

                # 7. Campo personalizado: Ticket GLPI
                if 'ticket_id' in entry_data and entry_data['ticket_id']:
                    selector_glpi = "#timesheet_edit_form_metaFields_ticket_glpi_value"
                    if page.is_visible(selector_glpi):
                        page.fill(selector_glpi, str(entry_data['ticket_id']))

                # 8. Guardar
                # Buscamos el botón de submit
                page.click("input[type='submit']")
                
                # Esperar a que la URL cambie o aparezca mensaje de éxito
                page.wait_for_load_state('networkidle')
                
                if "create" in page.url:
                    # Si seguimos en la página de creación, algo falló (quizás campos requeridos)
                    print(f" Error al guardar: La página no redireccionó. Revisar campos.")
                    # Tomar screenshot para debug si es necesario
                    # page.screenshot(path="error.png")
                    return False

                print(f"Entrada registrada con éxito.")
                return True

            except Exception as e:
                print(f" Error en la automatización web: {e}")
                raise e
            finally:
                browser.close()

if __name__ == "__main__":
    # Test rápido
    from dotenv import load_dotenv
    load_dotenv()
    
    svc = WebAutomator()
    svc.fill_timesheet_entry({
        "title": "Test de Automatización",
        "start_time": "20.01.2026 08:30",
        "end_time": "20.01.2026 09:00",
        "ticket_id": "12345"
    })

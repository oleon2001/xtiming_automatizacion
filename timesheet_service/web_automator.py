from playwright.sync_api import sync_playwright
import os
import time
import logging

logger = logging.getLogger("WebBot")

class WebAutomator:
    def __init__(self, config=None):
        self.config = config or {}
        self.user = os.getenv("XTIMING_USER")
        self.password = os.getenv("XTIMING_PASSWORD")
        self.base_url = "https://xtiming.intelix.biz/index.php/es"
        
        # Configuración de navegador
        self.headless = self.config.get("app", {}).get("headless_browser", False)

        # Defaults (por si no vienen en entry_data)
        defaults = self.config.get("defaults", {})
        self.default_client = defaults.get("client_fallback", "Intelix")
        self.default_project = defaults.get("project_fallback", "Gestión - Intelix")
        self.default_activity = defaults.get("activity", "Soporte")
        self.default_tag = defaults.get("tag", "Soporte")

    def login(self, page):
        logger.info(f"Iniciando sesión para usuario {self.user}...")
        try:
            page.goto(f"{self.base_url}/login")
            page.fill("input[name='_username']", self.user)
            page.fill("input[name='_password']", self.password)
            page.click("button[type='submit']")
            page.wait_for_load_state('networkidle')
            
            # Validación mejorada
            if page.locator(".user-menu").is_visible() or "login" not in page.url:
                logger.info("Login exitoso.")
                return True
            else:
                logger.error("Fallo en login: Seguimos en la página de login.")
                raise Exception("Credenciales inválidas o error de carga.")
                
        except Exception as e:
            logger.error(f"Excepción durante login: {e}")
            raise

    def _select_select2(self, page, select_id, label_text):
        if not label_text: return

        try:
            logger.debug(f"Seleccionando '{label_text}' en {select_id}")
            clean_id = select_id.lstrip('#')
            container_selector = f"#select2-{clean_id}-container"
            
            if page.is_visible(container_selector):
                page.click(container_selector)
            else:
                page.click(f"#{clean_id} + .select2 .select2-selection")

            search_input = ".select2-container--open .select2-search__field"
            page.wait_for_selector(search_input, state="visible", timeout=3000)
            
            # 3. Escribir y seleccionar
            page.fill(search_input, label_text)
            time.sleep(1.5) # Espera para que el JS filtre los resultados
            
            # Estrategia Robusta: Click en la opción resaltada
            # Select2 marca la opción seleccionada con la clase .select2-results__option--highlighted
            option_selector = ".select2-results__option--highlighted"
            
            try:
                page.wait_for_selector(option_selector, state="visible", timeout=2000)
                page.click(option_selector)
            except:
                # Fallback: Si no encuentra el selector específico, intenta Enter
                logger.warning(f"No se pudo hacer click en opción para '{label_text}', intentando Enter.")
                page.press(search_input, "Enter")
            
            # Breve pausa para asegurar que la selección se procese antes de mover el foco
            time.sleep(0.5)

        except Exception as e:
            logger.warning(f"Error select2 '{label_text}': {e}. Intentando fallback nativo.")
            try:
                page.select_option(select_id, label=label_text)
            except:
                logger.error(f"Fallback también falló para {label_text}")

    def fill_timesheet_entry(self, entry_data):
        with sync_playwright() as p:
            # Usar configuración headless
            browser = p.chromium.launch(headless=self.headless) 
            context = browser.new_context()
            page = context.new_page()
            
            try:
                self.login(page)
                
                logger.info(f"Registrando: {entry_data['title']} [{entry_data['start_time']} - {entry_data['end_time']}]")
                page.goto(f"{self.base_url}/timesheet/create")
                page.wait_for_load_state('networkidle')

                # 1. Fechas y Horas
                page.fill("#timesheet_edit_form_begin", entry_data['start_time'])
                page.press("#timesheet_edit_form_begin", "Enter")
                
                page.fill("#timesheet_edit_form_end", entry_data['end_time'])
                page.press("#timesheet_edit_form_end", "Enter")

                # Valores
                target_client = entry_data.get('client', self.default_client)
                target_project = entry_data.get('project', self.default_project)
                target_activity = entry_data.get('activity', self.default_activity)
                target_tags = entry_data.get('tags', self.default_tag)

                # Selectores
                self._select_select2(page, "#timesheet_edit_form_customer", target_client)
                time.sleep(1.5) 
                self._select_select2(page, "#timesheet_edit_form_project", target_project)
                time.sleep(3.0)
                self._select_select2(page, "#timesheet_edit_form_activity", target_activity)

                page.fill("#timesheet_edit_form_description", entry_data['title'])

                time.sleep(0.5)
                if isinstance(target_tags, list):
                    for tag in target_tags:
                        self._select_select2(page, "#timesheet_edit_form_tags", tag)
                else:
                    self._select_select2(page, "#timesheet_edit_form_tags", target_tags)
                
                page.click("#timesheet_edit_form_description") # Cerrar dropdown

                # Ticket GLPI
                if 'ticket_id' in entry_data and entry_data['ticket_id']:
                    selector_glpi = "#timesheet_edit_form_metaFields_ticket_glpi_value"
                    if page.is_visible(selector_glpi):
                        page.fill(selector_glpi, str(entry_data['ticket_id']))

                # Guardar
                if page.locator("#form_modal_save").is_visible():
                    page.click("#form_modal_save")
                else:
                    page.click(".box-footer .btn-primary")
                
                page.wait_for_load_state('networkidle')
                
                if "create" in page.url:
                    logger.error("No se redireccionó tras guardar. Posible error de validación.")
                    logger.warning("!!! DEPURACION: El navegador permanecerá abierto 60 segundos. POR FAVOR MIRA LA PANTALLA Y REVISA QUE CAMPO ESTA EN ROJO.")
                    time.sleep(60) # Pausa para depuración visual
                    return False

                logger.info("Entrada registrada con éxito.")
                return True

            except Exception as e:
                logger.error(f"Error en automatización web: {e}")
                return False # Retornar False en lugar de lanzar excepción para que el Scheduler siga
            finally:
                browser.close()

if __name__ == "__main__":
    pass
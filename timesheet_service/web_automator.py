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

        # Estado del navegador persistente
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def start_browser(self):
        """Inicia una sesión de navegador persistente."""
        if self.page:
            return # Ya iniciado

        logger.info("Iniciando navegador...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        
        try:
            self.login(self.page)
        except Exception as e:
            self.close_browser()
            raise e

    def close_browser(self):
        """Cierra la sesión del navegador y libera recursos."""
        logger.info("Cerrando navegador...")
        if self.page: self.page.close()
        if self.context: self.context.close()
        if self.browser: self.browser.close()
        if self.playwright: self.playwright.stop()
        
        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None

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
            
            # 1. Abrir dropdown
            if page.is_visible(container_selector):
                page.click(container_selector)
            else:
                page.click(f"#{clean_id} + .select2 .select2-selection")

            # 2. Esperar input de búsqueda
            search_input = ".select2-container--open .select2-search__field"
            page.wait_for_selector(search_input, state="visible", timeout=5000)
            
            # 3. Escribir y esperar resultados
            page.fill(search_input, label_text)
            
            # Esperar a que aparezca al menos una opción resaltada o la opción específica
            option_selector = ".select2-results__option--highlighted"
            page.wait_for_selector(option_selector, state="visible", timeout=5000)
            
            # 4. Click en la opción
            page.click(option_selector)
            
            # 5. Esperar a que el container refleje el cambio (opcional, pero seguro)
            # O simplemente esperar que el dropdown se cierre
            page.wait_for_selector(".select2-container--open", state="hidden", timeout=2000)

        except Exception as e:
            logger.warning(f"Error select2 '{label_text}': {e}. Intentando fallback nativo.")
            try:
                # Fallback extremo: intentar forzar el valor en el select oculto
                page.evaluate(f"""
                    document.querySelector('{select_id}').value = '{label_text}'; # Esto suele requerir el ID del option, no el texto.
                    # Mejor no hacer nada si falla el select2 visual.
                """)
            except:
                pass

    def fill_timesheet_entry(self, entry_data):
        # Auto-start si no está iniciado
        if not self.page:
            self.start_browser()
        
        page = self.page

        try:
            logger.info(f"Registrando: {entry_data['title']} [{entry_data['start_time']} - {entry_data['end_time']}]")
            page.goto(f"{self.base_url}/timesheet/create")
            page.wait_for_load_state('networkidle')

            # 1. Fechas y Horas
            page.fill("#timesheet_edit_form_begin", entry_data['start_time'])
            page.press("#timesheet_edit_form_begin", "Tab") # Tab es más seguro que Enter a veces
            
            page.fill("#timesheet_edit_form_end", entry_data['end_time'])
            page.press("#timesheet_edit_form_end", "Tab")

            # Valores
            target_client = entry_data.get('client', self.default_client)
            target_project = entry_data.get('project', self.default_project)
            target_activity = entry_data.get('activity', self.default_activity)
            target_tags = entry_data.get('tags', self.default_tag)

            # Selectores Robustos
            self._select_select2(page, "#timesheet_edit_form_customer", target_client)
            page.wait_for_timeout(500) # Pequeña pausa para que cargue el siguiente select dependiente
            
            self._select_select2(page, "#timesheet_edit_form_project", target_project)
            page.wait_for_timeout(500)
            
            self._select_select2(page, "#timesheet_edit_form_activity", target_activity)

            page.fill("#timesheet_edit_form_description", entry_data['title'])

            if isinstance(target_tags, list):
                for tag in target_tags:
                    self._select_select2(page, "#timesheet_edit_form_tags", tag)
            else:
                self._select_select2(page, "#timesheet_edit_form_tags", target_tags)
            
            # Cerrar dropdown de tags si quedó abierto (click afuera)
            page.click("#timesheet_edit_form_description") 

            # Ticket GLPI
            if 'ticket_id' in entry_data and entry_data['ticket_id']:
                selector_glpi = "#timesheet_edit_form_metaFields_ticket_glpi_value"
                if page.is_visible(selector_glpi):
                    page.fill(selector_glpi, str(entry_data['ticket_id']))

            # Guardar
            save_btn = "#form_modal_save" if page.is_visible("#form_modal_save") else ".box-footer .btn-primary"
            page.click(save_btn)
            
            page.wait_for_load_state('networkidle')
            
            # Validación de éxito
            if "create" in page.url:
                logger.error("No se redireccionó tras guardar. Posible error de validación.")
                if self.headless:
                    page.screenshot(path=f"error_validation_{int(time.time())}.png")
                return False

            logger.info("Entrada registrada con éxito.")
            return True

        except Exception as e:
            logger.error(f"Error en automatización web: {e}")
            return False

if __name__ == "__main__":
    import dotenv
    dotenv.load_dotenv()
    bot = WebAutomator()
    bot.start_browser()
    test_entry = {
        "title": "Prueba de entrada automática",
        "start_time": "2024-06-01 09:00",
        "end_time": "2024-06-01 09:30",
        "client": "Intelix",
        "project": "Gestión - Intelix",
        "activity": "Soporte",
        "tags": "Soporte",
        "ticket_id": 1234
    }
    success = bot.fill_timesheet_entry(test_entry)
    print(f"Entrada de prueba registrada: {'Éxito' if success else 'Fallo'}")
    bot.close_browser()
    
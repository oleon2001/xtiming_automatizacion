from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext, Playwright
import os
import time
import logging
from typing import Dict, Any, Union, Optional, List

logger = logging.getLogger("WebBot")

class WebAutomator:
    # Centralized Selectors for easier maintenance
    SELECTORS = {
        "login_user": "input[name='_username']",
        "login_pass": "input[name='_password']",
        "login_btn": "button[type='submit']",
        "user_menu": ".user-menu",
        
        "ts_start_time": "#timesheet_edit_form_begin",
        "ts_end_time": "#timesheet_edit_form_end",
        
        "ts_customer": "#timesheet_edit_form_customer",
        "ts_project": "#timesheet_edit_form_project",
        "ts_activity": "#timesheet_edit_form_activity",
        "ts_description": "#timesheet_edit_form_description",
        "ts_tags": "#timesheet_edit_form_tags",
        
        "ts_ticket_glpi": "#timesheet_edit_form_metaFields_ticket_glpi_value",
        "ts_save_modal": "#form_modal_save",
        "ts_save_footer": ".box-footer .btn-primary",
        
        "select2_search": ".select2-container--open .select2-search__field",
        "select2_highlighted": ".select2-results__option--highlighted",
        "select2_open_container": ".select2-container--open"
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
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
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

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

    def login(self, page: Page) -> bool:
        logger.info(f"Iniciando sesión para usuario {self.user}...")
        try:
            page.goto(f"{self.base_url}/login")
            page.fill(self.SELECTORS["login_user"], self.user)
            page.fill(self.SELECTORS["login_pass"], self.password)
            page.click(self.SELECTORS["login_btn"])
            page.wait_for_load_state('networkidle')
            
            # Validación mejorada
            if page.locator(self.SELECTORS["user_menu"]).is_visible() or "login" not in page.url:
                logger.info("Login exitoso.")
                return True
            else:
                logger.error("Fallo en login: Seguimos en la página de login.")
                raise Exception("Credenciales inválidas o error de carga.")
                
        except Exception as e:
            logger.error(f"Excepción durante login: {e}")
            raise

    def _select_select2(self, page: Page, select_id: str, label_text: str):
        if not label_text: return

        try:
            logger.debug(f"Seleccionando '{label_text}' en {select_id}")
            clean_id = select_id.lstrip('#')
            container_selector = f"#select2-{clean_id}-container"
            
            # 1. Abrir dropdown
            if page.is_visible(container_selector):
                page.click(container_selector)
            else:
                # Fallback por si el container tiene otro ID dinámico, clickeamos el sibling visual
                page.click(f"#{clean_id} + .select2 .select2-selection")

            # 2. Esperar input de búsqueda
            search_input = self.SELECTORS["select2_search"]
            page.wait_for_selector(search_input, state="visible", timeout=5000)
            
            # 3. Escribir y esperar resultados
            page.fill(search_input, label_text)
            
            # Esperar a que aparezca al menos una opción resaltada
            option_selector = self.SELECTORS["select2_highlighted"]
            page.wait_for_selector(option_selector, state="visible", timeout=5000)
            
            # 4. Click en la opción
            page.click(option_selector)
            
            # 5. Esperar a que el dropdown se cierre
            page.wait_for_selector(self.SELECTORS["select2_open_container"], state="hidden", timeout=2000)

        except Exception as e:
            logger.warning(f"Error select2 '{label_text}': {e}. Intentando fallback nativo.")
            try:
                # Fallback extremo: intentar forzar el valor en el select oculto
                # Esto es arriesgado en SPAs reactivas, pero funciona en jQuery apps viejas
                page.evaluate(f"document.querySelector('{select_id}').value = '{label_text}'")
            except:
                pass

    def fill_timesheet_entry(self, entry_data: Dict[str, Any]) -> bool:
        # Auto-start si no está iniciado
        if not self.page:
            self.start_browser()
        
        page = self.page

        try:
            logger.info(f"Registrando: {entry_data['title']} [{entry_data['start_time']} - {entry_data['end_time']}]")
            page.goto(f"{self.base_url}/timesheet/create")
            page.wait_for_load_state('networkidle')

            # 1. Fechas y Horas
            page.fill(self.SELECTORS["ts_start_time"], entry_data['start_time'])
            page.press(self.SELECTORS["ts_start_time"], "Tab")
            
            page.fill(self.SELECTORS["ts_end_time"], entry_data['end_time'])
            page.press(self.SELECTORS["ts_end_time"], "Tab")

            # Valores
            target_client = entry_data.get('client', self.default_client)
            target_project = entry_data.get('project', self.default_project)
            target_activity = entry_data.get('activity', self.default_activity)
            target_tags = entry_data.get('tags', self.default_tag)

            # Selectores Robustos con Select2
            self._select_select2(page, self.SELECTORS["ts_customer"], target_client)
            page.wait_for_timeout(500) # Yield al UI
            
            self._select_select2(page, self.SELECTORS["ts_project"], target_project)
            page.wait_for_timeout(500)
            
            self._select_select2(page, self.SELECTORS["ts_activity"], target_activity)

            page.fill(self.SELECTORS["ts_description"], entry_data['title'])

            if isinstance(target_tags, list):
                for tag in target_tags:
                    self._select_select2(page, self.SELECTORS["ts_tags"], tag)
            else:
                self._select_select2(page, self.SELECTORS["ts_tags"], target_tags)
            
            # Cerrar dropdown de tags si quedó abierto (click afuera en descripción)
            page.click(self.SELECTORS["ts_description"]) 

            # Ticket GLPI
            if 'ticket_id' in entry_data and entry_data['ticket_id']:
                if page.is_visible(self.SELECTORS["ts_ticket_glpi"]):
                    page.fill(self.SELECTORS["ts_ticket_glpi"], str(entry_data['ticket_id']))

            # Guardar
            if page.is_visible(self.SELECTORS["ts_save_modal"]):
                page.click(self.SELECTORS["ts_save_modal"])
            else:
                page.click(self.SELECTORS["ts_save_footer"])
            
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
    
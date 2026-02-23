from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext, Playwright, TimeoutError as PlaywrightTimeout
import os
import time
import logging
import functools
from typing import Dict, Any, Union, Optional, List

logger = logging.getLogger("WebBot")

def retry_action(max_retries=3, delay=1):
    """Decorador para reintentar acciones de Playwright."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (PlaywrightTimeout, Exception) as e:
                    last_exception = e
                    logger.warning(f"Intento {attempt + 1}/{max_retries} fallido en {func.__name__}: {str(e)}")
                    time.sleep(delay * (attempt + 1)) # Backoff lineal
            
            logger.error(f"Acción {func.__name__} falló después de {max_retries} intentos.")
            raise last_exception
        return wrapper
    return decorator

class WebAutomator:
    # Centralized Selectors for easier maintenance
    SELECTORS = {
        "login_user": "input[name='_username']",
        "login_pass": "input[name='_password']",
        "login_btn": "button[type='submit']",
        "user_menu": ".user-menu, .dropdown-user", 
        
        "ts_start_time": "#timesheet_edit_form_begin",
        "ts_end_time": "#timesheet_edit_form_end",
        
        "ts_customer": "#timesheet_edit_form_customer",
        "ts_project": "#timesheet_edit_form_project",
        "ts_activity": "#timesheet_edit_form_activity",
        "ts_description": "#timesheet_edit_form_description",
        "ts_tags": "#timesheet_edit_form_tags",
        
        "ts_ticket_glpi": "#timesheet_edit_form_metaFields_ticket_glpi_value",
        "ts_save_btn": "button[type='submit']",
        
        "select2_container": ".select2-container",
        "select2_search": ".select2-search__field",
        "select2_results": ".select2-results__options",
        "select2_option": ".select2-results__option",
        
        "alert_success": ".alert-success, .flash-success",
        "alert_error": ".alert-danger, .has-error, .flash-error"
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.user = os.getenv("XTIMING_USER")
        self.password = os.getenv("XTIMING_PASSWORD")
        self.base_url = "https://xtiming.intelix.biz/index.php/es"
        
        self.headless = self.config.get("app", {}).get("headless_browser", False)

        defaults = self.config.get("defaults", {})
        self.default_client = defaults.get("client_fallback", "Intelix")
        self.default_project = defaults.get("project_fallback", "Gestión - Intelix")
        self.default_activity = defaults.get("activity", "Soporte")
        self.default_tag = defaults.get("tag", "Soporte")

        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    def start_browser(self):
        if self.page: return

        logger.info("Iniciando navegador...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        
        try:
            self.login()
        except Exception as e:
            logger.error(f"Error crítico iniciando navegador: {e}")
            self.close_browser()
            raise e

    def close_browser(self):
        logger.info("Cerrando navegador...")
        if self.page: self.page.close()
        if self.context: self.context.close()
        if self.browser: self.browser.close()
        if self.playwright: self.playwright.stop()
        
        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None

    @retry_action(max_retries=3, delay=2)
    def login(self):
        page = self.page
        logger.info(f"Iniciando sesión para usuario {self.user}...")
        page.goto(f"{self.base_url}/login")
        
        if page.locator(self.SELECTORS["user_menu"]).is_visible():
            logger.info("Sesión recuperada.")
            return True

        page.fill(self.SELECTORS["login_user"], self.user)
        page.fill(self.SELECTORS["login_pass"], self.password)
        page.click(self.SELECTORS["login_btn"])
        
        try:
            page.wait_for_selector(self.SELECTORS["user_menu"], timeout=15000)
            logger.info("Login exitoso.")
            return True
        except PlaywrightTimeout:
            if "login" in page.url:
                raise Exception("Credenciales inválidas o error de carga.")
            # Si cambió la URL pero no vimos el menú, asumimos éxito parcial
            return True

    def _select_select2(self, selector_id: str, label_text: str):
        """Manejo robusto de Select2."""
        if not label_text: return
        page = self.page

        try:
            # 1. Click para abrir (puede ser el select oculto o el container generado)
            # Intentamos clickear el container de Select2 asociado
            clean_id = selector_id.replace("#", "")
            
            # Select2 suele poner un span con aria-labelledby apuntando al select original
            container_selector = f"#select2-{clean_id}-container"
            
            if page.is_visible(container_selector):
                page.click(container_selector)
            else:
                # Fallback: clickear el hermano siguiente (estructura clásica)
                page.click(f"{selector_id} + .select2 .select2-selection")

            # 2. Esperar input de búsqueda
            page.wait_for_selector(self.SELECTORS["select2_search"], state="visible", timeout=3000)
            
            # 3. Escribir
            page.fill(self.SELECTORS["select2_search"], label_text)
            
            # 4. Esperar resultados
            page.wait_for_selector(self.SELECTORS["select2_results"], state="visible", timeout=3000)
            
            # 5. Seleccionar opción (click en la primera coincidencia o resaltada)
            # Primero buscamos coincidencia exacta de texto
            option = page.locator(f".select2-results__option:text-is('{label_text}')")
            if option.count() > 0:
                option.first.click()
            else:
                # Si no, la primera opción visible (que debería ser la filtrada)
                page.locator(self.SELECTORS["select2_option"]).first.click()

        except Exception as e:
            logger.warning(f"Fallo select2 en {selector_id} para '{label_text}': {e}")
            # Intento de cierre de emergencia (ESC)
            page.keyboard.press("Escape")

    def fill_timesheet_entry(self, entry_data: Dict[str, Any]) -> bool:
        if not self.page: self.start_browser()
        page = self.page

        try:
            logger.info(f"Registrando: {entry_data['title']} [{entry_data['start_time']} - {entry_data['end_time']}]")
            
            page.goto(f"{self.base_url}/timesheet/create")
            page.wait_for_load_state('domcontentloaded')

            # --- Llenado ---
            page.fill(self.SELECTORS["ts_start_time"], entry_data['start_time'])
            page.evaluate(f"document.querySelector('{self.SELECTORS['ts_start_time']}').blur()")
            
            page.fill(self.SELECTORS["ts_end_time"], entry_data['end_time'])
            page.evaluate(f"document.querySelector('{self.SELECTORS['ts_end_time']}').blur()")

            # Selects
            self._select_select2(self.SELECTORS["ts_customer"], entry_data.get('client', self.default_client))
            time.sleep(0.5) 
            self._select_select2(self.SELECTORS["ts_project"], entry_data.get('project', self.default_project))
            time.sleep(0.5)
            self._select_select2(self.SELECTORS["ts_activity"], entry_data.get('activity', self.default_activity))

            page.fill(self.SELECTORS["ts_description"], entry_data['title'])

            target_tags = entry_data.get('tags', self.default_tag)
            if isinstance(target_tags, list):
                for tag in target_tags:
                    self._select_select2(self.SELECTORS["ts_tags"], tag)
            else:
                self._select_select2(self.SELECTORS["ts_tags"], target_tags)
            
            # Cerrar dropdown de tags clickeando afuera
            page.click("body", force=True, position={"x": 0, "y": 0})

            # ID Ticket (si es numérico)
            ticket_id = entry_data.get('ticket_id')
            # Check if ticket_id is a valid integer string (excludes "TEL-1234")
            if ticket_id and str(ticket_id).isdigit():
                 if page.locator(self.SELECTORS["ts_ticket_glpi"]).is_visible():
                    page.fill(self.SELECTORS["ts_ticket_glpi"], str(ticket_id))

            # --- Guardado ---
            # Esperar navegación tras click
            with page.expect_navigation(timeout=10000): 
                 page.click(self.SELECTORS["ts_save_btn"])
            
            # Validación post-navegación
            if "create" not in page.url: 
                logger.info("Redirección detectada. Registro exitoso.")
                return True
            
            if page.locator(self.SELECTORS["alert_error"]).is_visible():
                error_text = page.locator(self.SELECTORS["alert_error"]).first.inner_text()
                raise Exception(f"Error de validación: {error_text}")

            return True

        except Exception as e:
            logger.error(f"Error registrando ticket: {e}")
            timestamp = int(time.time())
            screenshot_path = os.path.abspath(f"error_validation_{timestamp}.png")
            try:
                page.screenshot(path=screenshot_path)
                logger.info(f"Screenshot guardada: {screenshot_path}")
            except:
                pass
            return False

if __name__ == "__main__":
    pass

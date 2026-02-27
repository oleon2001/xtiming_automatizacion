from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext, Playwright, TimeoutError as PlaywrightTimeout
import os
import time
import logging
import functools
from typing import Dict, Any, Union, Optional, List

import logging
import sys

logger = logging.getLogger("WebBot")
logger.setLevel(logging.DEBUG)

# Create handlers
c_handler = logging.StreamHandler(sys.stdout)
f_handler = logging.FileHandler('automator.log', encoding='utf-8')
c_handler.setLevel(logging.INFO)
f_handler.setLevel(logging.DEBUG)

# Create formatters and add it to handlers
c_format = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
f_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s')
c_handler.setFormatter(c_format)
f_handler.setFormatter(f_format)

# Add handlers to the logger
if not logger.handlers:
    logger.addHandler(c_handler)
    logger.addHandler(f_handler)
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

        # En Docker/servidores sin pantalla, forzar headless aunque el config diga lo contrario
        is_headless = self.headless
        if not os.environ.get("DISPLAY") and os.name != 'nt':
            if not is_headless:
                logger.warning("No se detectó DISPLAY (ambiente Docker/servidor). Forzando headless=True.")
            is_headless = True

        logger.info(f"Iniciando navegador (headless={is_headless})...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=is_headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
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
        logger.debug(f"Select2: Intentando seleccionar '{label_text}' en {selector_id}")

        try:
            # 1. Click para abrir (puede ser el select oculto o el container generado)
            clean_id = selector_id.replace("#", "")
            container_selector = f"#select2-{clean_id}-container"
            
            # Scroll al elemento para que sea visible sin que Playwright haga scroll salvaje
            if page.is_visible(container_selector):
                logger.debug(f"Select2: container {container_selector} visible, haciendo scroll y click")
                page.locator(container_selector).scroll_into_view_if_needed()
                time.sleep(0.3)
                page.click(container_selector)
            else:
                fallback = f"{selector_id} + .select2 .select2-selection"
                logger.debug(f"Select2: container no visible, usando fallback: {fallback}")
                page.locator(fallback).scroll_into_view_if_needed()
                time.sleep(0.3)
                page.click(fallback)

            # 2. Esperar input de búsqueda
            logger.debug("Select2: Esperando campo de búsqueda...")
            page.wait_for_selector(self.SELECTORS["select2_search"], state="visible", timeout=5000)
            
            # 3. Escribir
            logger.debug(f"Select2: Escribiendo '{label_text}' en búsqueda")
            page.fill(self.SELECTORS["select2_search"], label_text)
            time.sleep(0.5)  # Esperar que filtre resultados
            
            # 4. Esperar resultados
            logger.debug("Select2: Esperando resultados...")
            page.wait_for_selector(self.SELECTORS["select2_results"], state="visible", timeout=5000)
            
            # 5. Seleccionar opción
            option = page.locator(f".select2-results__option:text-is('{label_text}')")
            if option.count() > 0:
                logger.debug(f"Select2: Coincidencia exacta encontrada para '{label_text}', clickeando")
                option.first.click()
            else:
                first_opt = page.locator(self.SELECTORS["select2_option"]).first
                opt_text = first_opt.inner_text() if first_opt.count() > 0 else "N/A"
                logger.debug(f"Select2: Sin coincidencia exacta. Seleccionando primera opción: '{opt_text}'")
                first_opt.click()
            
            logger.info(f"Select2: '{label_text}' seleccionado exitosamente en {selector_id}")

        except Exception as e:
            logger.error(f"Fallo select2 en {selector_id} para '{label_text}': {e}")
            # Capturar estado actual de la página para debug
            try:
                timestamp = int(time.time())
                page.screenshot(path=f"error_select2_{clean_id}_{timestamp}.png")
                logger.info(f"Screenshot de error Select2 guardada: error_select2_{clean_id}_{timestamp}.png")
            except:
                pass
            page.keyboard.press("Escape")

    def fill_timesheet_entry(self, entry_data: Dict[str, Any]) -> bool:
        if not self.page: self.start_browser()
        page = self.page

        try:
            logger.info(f"Registrando: {entry_data['title']} [{entry_data['start_time']} - {entry_data['end_time']}]")
            
            page.goto(f"{self.base_url}/timesheet/create")
            page.wait_for_load_state('domcontentloaded')

            # --- Llenado de fechas via JavaScript para NO activar el datepicker ---
            start_selector = self.SELECTORS["ts_start_time"]
            end_selector = self.SELECTORS["ts_end_time"]

            # Inyectar valor de inicio directamente con JS
            page.evaluate(f"""(() => {{
                const el = document.querySelector('{start_selector}');
                el.value = '{entry_data["start_time"]}';
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                el.blur();
            }})()""")
            logger.debug(f"Start time seteado via JS: {entry_data['start_time']}")

            # Inyectar valor de fin directamente con JS  
            page.evaluate(f"""(() => {{
                const el = document.querySelector('{end_selector}');
                el.value = '{entry_data["end_time"]}';
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                el.blur();
            }})()""")
            logger.debug(f"End time seteado via JS: {entry_data['end_time']}")

            # Cerrar cualquier datepicker residual que pueda estar abierto
            page.evaluate("""(() => {
                // Intentar cerrar datepickers de jQuery UI / bootstrap-datepicker
                document.querySelectorAll('.datepicker, .daterangepicker, .bootstrap-datetimepicker-widget, .flatpickr-calendar').forEach(el => {
                    el.style.display = 'none';
                });
                // También cerrar con jQuery si existe
                if (typeof jQuery !== 'undefined' && jQuery.fn.datepicker) {
                    jQuery('.datepicker-input, input[data-toggle="datetimepicker"]').datepicker('hide');
                }
                document.activeElement.blur();
            })()""")
            page.keyboard.press("Escape")
            time.sleep(0.5)
            logger.debug("Datepickers cerrados, procediendo con selects.")

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
            page.keyboard.press("Escape")
            page.evaluate("document.body.click()")

            # ID Ticket (si es numérico)
            ticket_id = entry_data.get('ticket_id')
            # Check if ticket_id is a valid integer string (excludes "TEL-1234")
            if ticket_id and str(ticket_id).isdigit():
                 if page.locator(self.SELECTORS["ts_ticket_glpi"]).is_visible():
                    page.fill(self.SELECTORS["ts_ticket_glpi"], str(ticket_id))

            # --- Guardado ---
            logger.info("Procediendo a guardar el registro...")
            
            # Buscar el botón Guardar específico (no cualquier submit)
            save_btn = page.locator("button:has-text('Guardar'), input[type='submit'][value='Guardar']").first
            if save_btn.count() == 0:
                # Fallback al último botón submit del formulario
                save_btn = page.locator("form button[type='submit']").last
                logger.debug("Usando fallback: último submit del formulario")
            
            # Scroll al botón para que sea visible
            save_btn.scroll_into_view_if_needed()
            time.sleep(0.5)
            logger.debug("Botón Guardar visible, haciendo click...")
            
            # Esperar navegación tras click
            with page.expect_navigation(timeout=15000): 
                 save_btn.click()
            
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

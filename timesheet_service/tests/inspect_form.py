import os
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

# Cargar entorno
load_dotenv()

USER = os.getenv("XTIMING_USER")
PASSWORD = os.getenv("XTIMING_PASSWORD")
BASE_URL = "https://xtiming.intelix.biz/index.php/es"

def inspect_page():
    if not USER or not PASSWORD:
        print("ERROR: No se encontraron XTIMING_USER o XTIMING_PASSWORD en el .env")
        return

    with sync_playwright() as p:
        # Lanzamos navegador (headless=True para que no necesite interfaz gráfica en WSL/Linux)
        print("Abriendo navegador...")
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            # 1. Login
            print(f"Intentando login en {BASE_URL}/login ...")
            page.goto(f"{BASE_URL}/login")
            page.fill("input[name='_username']", USER)
            page.fill("input[name='_password']", PASSWORD)
            page.click("button[type='submit']")
            page.wait_for_load_state('networkidle')

            if "login" in page.url:
                print(" Error: Seguimos en la página de login. Revisa las credenciales.")
                return

            print(" Login exitoso.")

            # 2. Ir al formulario de creación
            print("Navegando a /timesheet/create ...")
            page.goto(f"{BASE_URL}/timesheet/create")
            page.wait_for_load_state('networkidle')

            # 3. Extraer el HTML del formulario
            # Buscamos el form principal. A veces es 'form', a veces tiene un ID específico.
            # Grabaremos todo el body para asegurar que no se nos escape nada.
            content = page.content()

            output_file = "form_dump.html"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(content)

            print(f" ÉXITO: El código de la página se guardó en '{output_file}'.")

        except Exception as e:
            print(f" Ocurrió un error: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    inspect_page()

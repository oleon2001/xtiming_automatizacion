FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Interactividad para tzdata
ENV DEBIAN_FRONTEND=noninteractive

# Instalar dependencias del sistema si son necesarias (el de playwright ya trae mucho)
RUN apt-get update && apt-get install -y \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Configurar zona horaria
ENV TZ=America/Caracas
# Forzar a Playwright a usar una ruta global para los navegadores
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar navegadores en la ruta global definida arriba
RUN python -m playwright install chromium
RUN python -m playwright install-deps

COPY . .

# Comando de inicio
CMD ["python", "-u", "main.py"]

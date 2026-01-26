FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Interactividad para tzdata
ENV DEBIAN_FRONTEND=noninteractive

# Instalar dependencias del sistema si son necesarias (el de playwright ya trae mucho)
RUN apt-get update && apt-get install -y \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Configurar zona horaria (opcional pero recomendada para logs correctos)
ENV TZ=America/Caracas

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar navegadores de playwright (en caso de que la imagen base no tenga la version exacta o para asegurar)
RUN playwright install chromium
RUN playwright install-deps

COPY . .

# Comando de inicio
CMD ["python", "-u", "main.py"]

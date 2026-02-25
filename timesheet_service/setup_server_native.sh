#!/bin/bash
# setup_server_native.sh
# Script para instalar el servicio Timesheet de forma nativa en Ubuntu/Linux
# (Sin usar Docker)

echo "=== Configurando Timesheet Service BARE-METAL (Nativo) ==="

# 1. Asegurar dependencias del sistema operativo base
echo "1. Instalando dependencias base de Python y del sistema..."
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip

# 2. Crear y activar Entorno Virtual
echo "2. Creando Entorno Virtual Python (venv)..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo " > venv creado."
else
    echo " > venv ya existía."
fi

echo "3. Activando venv y actualizando pip..."
source venv/bin/activate
pip install --upgrade pip

# 3. Instalar dependencias del proyecto
echo "4. Instalando dependencias python de requirements.txt..."
pip install -r requirements.txt

# 4. INSTALACION VITAL: Playwright y Navegador
echo "5. Instalando Playwright y su navegador interno (Chromium)..."
# Se usa 'python -m playwright' para asegurar que agarre el contexto del venv activo
python -m playwright install chromium
echo " > Descargando dependencias de SO para el navegador..."
sudo venv/bin/python -m playwright install-deps

# 5. Crear carpeta de datos si no existe
echo "6. Asegurando carpeta de datos..."
mkdir -p data
echo " > Carpeta 'data/' lista."

echo "=== Instalación Nativa Completada ==="
echo ""
echo "Para correr el servicio en background usando 'nohup' ejecuta:"
echo "  source venv/bin/activate"
echo "  nohup python -u main.py > nohup.out 2>&1 &"
echo ""
echo "Para forzar un barrido manual ahora mismo:"
echo "  source venv/bin/activate"
echo "  python main.py --sweep"

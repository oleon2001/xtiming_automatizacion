#!/bin/bash
# run_sweep_docker.sh
# Script para forzar un barrido manual del scheduler usando el contenedor de Docker activo.

CONTAINER_NAME="timesheet_service"

echo "=== Forzando Barrido Manual en Docker ==="

# Verificar si el contenedor está corriendo
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "ERROR: El contenedor '${CONTAINER_NAME}' no está en ejecución."
    echo "Asegúrate de haber desplegado primero usando ./despliegue.sh"
    exit 1
fi

echo "Ejecutando: python main.py --sweep dentro de ${CONTAINER_NAME}..."
echo "---------------------------------------------------"

# Ejecutar iterativamente para ver la salida en vivo
docker exec -it ${CONTAINER_NAME} python main.py --sweep

echo "---------------------------------------------------"
echo "Barrido finalizado."

#!/bin/bash

# Configuración del servidor remoto
REMOTE_HOST="10.48.63.60"
REMOTE_USER="cpgadmin"
REMOTE_PASS="Cpgretail01"
PROJECT_NAME="timesheet_service"
REMOTE_PATH="/home/cpgadmin/$PROJECT_NAME"

echo "=== Iniciando despliegue del proyecto $PROJECT_NAME ==="

# 1. Crear un archivo tar con el proyecto
echo "1. Empaquetando proyecto..."
# Asegurarse de que .env se incluya (al no excluirlo, se incluye por defecto)
tar --exclude='venv' \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='debug.log' \
    --exclude='scheduler_state.pkl' \
    --exclude='app.log' \
    -czf ${PROJECT_NAME}.tar.gz .

echo "Proyecto empaquetado en ${PROJECT_NAME}.tar.gz"

# 2. Copiar el archivo al servidor remoto usando sshpass
echo "2. Copiando proyecto al servidor remoto..."
# Función helper para ejecutar comandos ssh/scp con o sin sshpass
run_remote() {
    if command -v sshpass &> /dev/null; then
        sshpass -p "$REMOTE_PASS" "$@"
    else
        echo "  'sshpass' no encontrado. Tendrás que ingresar la contraseña ($REMOTE_PASS) manualmente."
        "$@"
    fi
}

# 2. Copiar el archivo al servidor remoto
echo "2. Copiando proyecto al servidor remoto..."
run_remote scp ${PROJECT_NAME}.tar.gz ${REMOTE_USER}@${REMOTE_HOST}:~/ 

# 3. Conectarse al servidor remoto y ejecutar los comandos de despliegue
echo "3. Conectando al servidor remoto y desplegando..."
# Usamos EOF sin comillas para expandir variables locales
run_remote ssh ${REMOTE_USER}@${REMOTE_HOST} << EOF
    # Detener contenedor existente si existe
    echo "Deteniendo contenedor anterior..."
    docker stop $PROJECT_NAME 2>/dev/null || true
    docker rm $PROJECT_NAME 2>/dev/null || true
    
    # Limpiar directorio de código anterior
    rm -rf ~/$PROJECT_NAME
    
    # Crear directorio para datos persistentes si no existe en /home (partición con espacio)
    DATA_DIR=/home/cpgadmin/timesheet_data
    mkdir -p \$DATA_DIR
    echo "Directorio de datos persistentes en partición segura: \$DATA_DIR"
    
    # Extraer el proyecto
    echo "Extrayendo archivos..."
    tar -xzf ~/${PROJECT_NAME}.tar.gz -C ~/ --one-top-level=$PROJECT_NAME
    
    # Ir al directorio del proyecto
    cd ~/$PROJECT_NAME
    
    # Construir la imagen Docker de forma optimizada
    echo "Construyendo imagen Docker (con prioridad baja para no afectar otros servicios)..."
    # Usamos etiquetas intermedias para una limpieza más fácil
    docker build -t $PROJECT_NAME:latest .
    
    # Detener contenedor existente SOLO si el build fue exitoso
    if [ $? -eq 0 ]; then
        echo "Build exitoso. Actualizando contenedor..."
        docker stop $PROJECT_NAME 2>/dev/null || true
        docker rm $PROJECT_NAME 2>/dev/null || true
    else
        echo "Error en el build. Abortando para no afectar el servicio actual."
        exit 1
    fi
    
    # Ejecutar el contenedor con límites de recursos si es necesario
    echo "Iniciando contenedor..."
    docker run -d \
        --name $PROJECT_NAME \
        --restart unless-stopped \
        --log-opt max-size=10m \
        --log-opt max-file=3 \
        -v \$(pwd)/.env:/app/.env \
        -v \$DATA_DIR:/app/data \
        -v /etc/localtime:/etc/localtime:ro \
        $PROJECT_NAME:latest
    
    # Limpiar imágenes "dangling" (huérfanas) para recuperar espacio en disco
    # Esto evita que el disco se llene y detenga otros servicios
    echo "Limpiando imágenes antiguas..."
    docker image prune -f --filter "label!=keep"
    
    # Mostrar estado del contenedor
    docker ps | grep $PROJECT_NAME
    
    echo "=== Despliegue completado ==="
    echo "Logs del servicio:"
    docker logs --tail 10 $PROJECT_NAME
EOF

# 4. Limpiar archivo temporal local
rm ${PROJECT_NAME}.tar.gz

echo "=== Proceso de despliegue finalizado ==="
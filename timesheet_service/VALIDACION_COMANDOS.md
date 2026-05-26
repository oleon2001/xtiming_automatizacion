# Guía de Validación y Ejecución - XTiming Automation Service

Esta guía proporciona los comandos necesarios para validar, configurar y ejecutar el servicio de automatización de XTiming de manera correcta en diferentes entornos.

## 1. Configuración del Entorno Local

Antes de ejecutar cualquier comando, asegúrese de tener las dependencias instaladas y las variables de entorno configuradas.

### Instalación de dependencias
```bash
pip install -r requirements.txt
```

### Configuración de archivos clave
- **`.env`**: Verifique que contenga las credenciales de base de datos y tokens de Telegram.
- **`config.json`**: Ajuste las preferencias de ejecución (headless mode, logs, etc.).

---

## 2. Ejecución Local (Python Directo)

El script principal `main.py` admite varios flags para controlar el comportamiento del servicio.

### Modo Estándar (Scheduler Activo + Bot de Telegram)
Ejecuta el servicio de forma continua basado en los horarios definidos en el scheduler.
```bash
python main.py
```

### Ejecución Inmediata (`--now`)
Fuerza la ejecución de todas las rutinas programadas inmediatamente sin esperar al próximo intervalo.
```bash
python main.py --now
```

### Sincronización de Semana (`--sync-week`)
Busca y encola tickets no registrados de los últimos 7 días.
```bash
python main.py --sync-week
```

### Barrido Completo (`--sweep`)
Realiza una sincronización y registro masivo del backlog de los últimos 7 días. **Nota:** Este modo omite el inicio del bot de Telegram para evitar conflictos.
```bash
python main.py --sweep
```

---

## 3. Pruebas de Integración y Módulos

### Prueba de Web Automator
Para validar que el navegador puede loguearse y llenar el timesheet sin ejecutar todo el flujo:
```bash
python test_run.py
```
*Este script intentará procesar el primer ticket en `data/pending_tickets.json` o usará datos de prueba.*

### Validación de Base de Datos
Para verificar la conexión y el estado de los tickets locales:
```bash
python local_db.py
```

---

## 4. Gestión con Docker

### Despliegue en Servidor Remoto
El script `despliegue.sh` automatiza el empaquetado, envío y reconstrucción en el servidor destino.
```bash
./despliegue.sh
```

### Barrido Manual en Contenedor Activo
Si el servicio ya está corriendo en Docker y desea forzar un barrido:
```bash
./run_sweep_docker.sh
```
*Equivalente a ejecutar `docker exec -it timesheet_service python main.py --sweep`.*

### Verificación de Logs en Docker
```bash
docker logs -f timesheet_service
```

---

## 5. Validación de Resultados

Después de ejecutar los comandos, verifique los siguientes artefactos:
- **`app.log`**: Log general del sistema y scheduler.
- **`automator.log`**: Log detallado de las interacciones con el navegador.
- **`data/pending_tickets.json`**: Estado de la cola de tickets.
- **Capturas de pantalla**: En caso de error, el sistema genera imágenes `error_validation_...png` para depuración visual.

---

**Desarrollado por:** Senior Software Developer - Intelix Project Team

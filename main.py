import time
import mysql.connector
import requests
import os
from datetime import datetime
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

# Config DB
try:
    DB_CONFIG = {
        "host": os.getenv("GLPI_DB_HOST"),
        "port": int(os.getenv("GLPI_DB_PORT", "3306")),
        "user": os.getenv("GLPI_DB_USER"),
        "password": os.getenv("GLPI_DB_PASSWORD"),
        "database": os.getenv("GLPI_DB_NAME"),
    }
except Exception as e:
    raise Exception("Error al cargar la configuración de la base de datos: " + str(e))

# Config Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "TU_TOKEN_DE_BOT")
TELEGRAM_CHAT_ID = os.getenv("TG_CHAT_ID", "TU_CHAT_ID")

# Queries SQL
QUERY_1_TICKETS_70_PORCIENTO = """
SELECT 
    gt.id AS ticket_id,
    gt.name AS titulo_ticket,
    gt.date AS fecha_creacion,
    gt.time_to_resolve AS fecha_vencimiento,
    CONCAT(gu.realname, ' ', gu.firstname) AS tecnico_asignado,
    TIMESTAMPDIFF(SECOND, gt.date, gt.time_to_resolve) AS tiempo_total_segundos,
    TIMESTAMPDIFF(SECOND, gt.date, NOW()) AS tiempo_transcurrido_segundos,
    ROUND((TIMESTAMPDIFF(SECOND, gt.date, NOW()) * 100.0 / 
           NULLIF(TIMESTAMPDIFF(SECOND, gt.date, gt.time_to_resolve), 0)), 2) AS porcentaje_transcurrido
FROM glpi_tickets gt
INNER JOIN glpi_tickets_users gtu ON gt.id = gtu.tickets_id AND gtu.type = 2
INNER JOIN glpi_users gu ON gtu.users_id = gu.id
INNER JOIN glpi_groups_users ggu ON gu.id = ggu.users_id
WHERE gt.is_deleted = 0
    AND gt.status NOT IN (6)
    AND gt.time_to_resolve IS NOT NULL
    AND ggu.groups_id = 11
    AND gt.solvedate IS NULL
    AND TIMESTAMPDIFF(SECOND, gt.date, NOW()) >= (TIMESTAMPDIFF(SECOND, gt.date, gt.time_to_resolve) * 0.7)
    AND TIMESTAMPDIFF(SECOND, gt.date, NOW()) < TIMESTAMPDIFF(SECOND, gt.date, gt.time_to_resolve)
ORDER BY gt.time_to_resolve ASC;
"""

QUERY_2_TICKETS_VENCIMIENTO_24H = """
SELECT 
    gt.id AS ticket_id,
    gt.name AS titulo_ticket,
    gt.date AS fecha_creacion,
    gt.time_to_resolve AS fecha_vencimiento,
    CONCAT(gu.realname, ' ', gu.firstname) AS tecnico_asignado,
    TIMESTAMPDIFF(MINUTE, gt.time_to_resolve, NOW()) AS minutos_vencido,
    CASE 
        WHEN gt.time_to_resolve < NOW() THEN 'VENCIDO'
        WHEN TIMESTAMPDIFF(MINUTE, NOW(), gt.time_to_resolve) <= 60 THEN 'VENCIENDO_PRONTAMENTE'
        ELSE 'PENDIENTE'
    END AS estado_vencimiento
FROM glpi_tickets gt
INNER JOIN glpi_tickets_users gtu ON gt.id = gtu.tickets_id AND gtu.type = 2
INNER JOIN glpi_users gu ON gtu.users_id = gu.id
INNER JOIN glpi_groups_users ggu ON gu.id = ggu.users_id
WHERE gt.is_deleted = 0
    AND gt.status NOT IN (6)
    AND gt.time_to_resolve IS NOT NULL
    AND ggu.groups_id = 11
    AND gt.solvedate IS NULL
    AND (
        gt.time_to_resolve < NOW()
        OR
        (TIMESTAMPDIFF(MINUTE, NOW(), gt.time_to_resolve) <= 60 
         AND TIMESTAMPDIFF(MINUTE, NOW(), gt.time_to_resolve) >= 0)
    )
ORDER BY 
    CASE 
        WHEN gt.time_to_resolve < NOW() THEN 0 
        ELSE 1 
    END,
    gt.time_to_resolve ASC;
"""

QUERY_3_TICKETS_VENCIDOS_PROXIMA_ACTUALIZACION = """
SELECT 
    gt.id AS ticket_id,
    gt.name AS titulo_ticket,
    gt.date AS fecha_creacion,
    gt.time_to_resolve AS fecha_vencimiento,
    CONCAT(gu.realname, ' ', gu.firstname) AS tecnico_asignado,
    TIMESTAMPDIFF(MINUTE, gt.time_to_resolve, NOW()) AS minutos_vencido,
    CASE 
        WHEN gt.time_to_resolve < NOW() THEN 'VENCIDO'
        WHEN TIMESTAMPDIFF(MINUTE, NOW(), gt.time_to_resolve) <= 60 THEN 'VENCIENDO_PRONTAMENTE'
        ELSE 'PENDIENTE'
    END AS estado_vencimiento
FROM glpi_tickets gt
INNER JOIN glpi_tickets_users gtu ON gt.id = gtu.tickets_id AND gtu.type = 2
INNER JOIN glpi_users gu ON gtu.users_id = gu.id
INNER JOIN glpi_groups_users ggu ON gu.id = ggu.users_id
WHERE gt.is_deleted = 0
    AND gt.status NOT IN (6)
    AND gt.time_to_resolve IS NOT NULL
    AND ggu.groups_id = 11
    AND gt.solvedate IS NULL
    AND (
        gt.time_to_resolve < NOW()
        OR
        (TIMESTAMPDIFF(MINUTE, NOW(), gt.time_to_resolve) <= 60 
         AND TIMESTAMPDIFF(MINUTE, NOW(), gt.time_to_resolve) >= 0)
    )
ORDER BY 
    CASE 
        WHEN gt.time_to_resolve < NOW() THEN 0 
        ELSE 1 
    END,
    gt.time_to_resolve ASC;
"""


def execute_query(query, query_name):
    """Ejecuta una consulta en la BD y devuelve las filas."""
    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query)
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        print(f"Error ejecutando {query_name}: {e}")
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def format_message_query1(rows):
    """Formatea los resultados de la Query 1: Tickets al 70% del tiempo."""
    if not rows:
        return "*Reporte 1: Tickets al 70% del tiempo*\n\nNo se encontraron tickets en esta condición."

    lines = ["*Reporte 1: Tickets al 70% del tiempo antes del vencimiento*"]
    lines.append(f"\nTotal de tickets: {len(rows)}\n")
    
    for row in rows:
        porcentaje = row.get('porcentaje_transcurrido', 0)
        horas_restantes = (row.get('tiempo_total_segundos', 0) - row.get('tiempo_transcurrido_segundos', 0)) / 3600
        
        lines.append(
            f"*Ticket ID:* {row['ticket_id']}\n"
            f"*Título:* {row['titulo_ticket']}\n"
            f"*Técnico:* {row['tecnico_asignado']}\n"
            f"*Fecha creación:* {row['fecha_creacion']}\n"
            f"*Fecha vencimiento:* {row['fecha_vencimiento']}\n"
            f"*Porcentaje transcurrido:* {porcentaje}%\n"
            f"*Horas restantes:* {horas_restantes:.2f}h\n"
            f"---"
        )
    
    return "\n".join(lines)


def format_message_query2(rows):
    """Formatea los resultados de la Query 2: Tickets vencidos o próximos a vencer."""
    if not rows:
        return "*Reporte 2: Tickets vencidos o próximos a vencer (24h)*\n\nNo se encontraron tickets en esta condición."

    lines = ["*Reporte 2: Tickets vencidos o próximos a vencer (24h)*"]
    lines.append(f"\nTotal de tickets: {len(rows)}\n")
    
    for row in rows:
        estado = row.get('estado_vencimiento', 'PENDIENTE')
        minutos = row.get('minutos_vencido', 0)
        
        if estado == 'VENCIDO':
            tiempo_info = f"Vencido hace {abs(minutos)} minutos"
        elif estado == 'VENCIENDO_PRONTAMENTE':
            tiempo_info = f"Vence en {abs(minutos)} minutos"
        else:
            tiempo_info = "Pendiente"
        
        lines.append(
            f"*Ticket ID:* {row['ticket_id']}\n"
            f"*Título:* {row['titulo_ticket']}\n"
            f"*Técnico:* {row['tecnico_asignado']}\n"
            f"*Fecha creación:* {row['fecha_creacion']}\n"
            f"*Fecha vencimiento:* {row['fecha_vencimiento']}\n"
            f"*Estado:* {estado}\n"
            f"*Tiempo:* {tiempo_info}\n"
            f"---"
        )
    
    return "\n".join(lines)


def format_message_query3(rows):
    """Formatea los resultados de la Query 3: Tickets vencidos o próximos a vencer."""
    if not rows:
        return "*Reporte 3: Tickets vencidos o próximos a vencer (próxima actualización)*\n\nNo se encontraron tickets en esta condición."

    lines = ["*Reporte 3: Tickets vencidos o próximos a vencer (próxima actualización)*"]
    lines.append(f"\nTotal de tickets: {len(rows)}\n")
    
    for row in rows:
        estado = row.get('estado_vencimiento', 'PENDIENTE')
        minutos = row.get('minutos_vencido', 0)
        
        if estado == 'VENCIDO':
            tiempo_info = f"Vencido hace {abs(minutos)} minutos"
        elif estado == 'VENCIENDO_PRONTAMENTE':
            tiempo_info = f"Vence en {abs(minutos)} minutos"
        else:
            tiempo_info = "Pendiente"
        
        lines.append(
            f"*Ticket ID:* {row['ticket_id']}\n"
            f"*Título:* {row['titulo_ticket']}\n"
            f"*Técnico:* {row['tecnico_asignado']}\n"
            f"*Fecha creación:* {row['fecha_creacion']}\n"
            f"*Fecha vencimiento:* {row['fecha_vencimiento']}\n"
            f"*Estado:* {estado}\n"
            f"*Tiempo:* {tiempo_info}\n"
            f"---"
        )
    
    return "\n".join(lines)


def send_telegram_message(text):
    """Envía un mensaje de texto a Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=payload)
    if not response.ok:
        raise Exception(f"Error al enviar mensaje a Telegram: {response.text}")


def process_and_send_query(query, query_name, formatter):
    """Ejecuta una query, la formatea y la envía por Telegram."""
    try:
        rows = execute_query(query, query_name)
        message = formatter(rows)
        send_telegram_message(message)
        print(f"Reporte {query_name} enviado correctamente. Tickets encontrados: {len(rows)}")
        return True
    except Exception as e:
        error_msg = f"Error en {query_name}: {str(e)}"
        print(error_msg)
        try:
            send_telegram_message(f"Error en el reporte {query_name}: {str(e)}")
        except Exception:
            pass
        return False


def run_reports():
    """Ejecuta todas las consultas una vez y envía los reportes por Telegram."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] Iniciando ejecución de reportes...")
    
    try:
        # Ejecutar Query 1
        process_and_send_query(
            QUERY_1_TICKETS_70_PORCIENTO,
            "Query 1 - Tickets al 70%",
            format_message_query1
        )
        
        # Pequeña pausa entre reportes
        time.sleep(2)
        
        # Ejecutar Query 2
        process_and_send_query(
            QUERY_2_TICKETS_VENCIMIENTO_24H,
            "Query 2 - Tickets vencidos/próximos 24h",
            format_message_query2
        )
        
        # Pequeña pausa entre reportes
        time.sleep(2)
        
        # Ejecutar Query 3
        process_and_send_query(
            QUERY_3_TICKETS_VENCIDOS_PROXIMA_ACTUALIZACION,
            "Query 3 - Tickets vencidos/próximos actualización",
            format_message_query3
        )
        
        print(f"[{timestamp}] Ciclo de reportes completado exitosamente.")
        
    except Exception as e:
        error_msg = f"Error crítico en la ejecución: {str(e)}"
        print(error_msg)
        try:
            send_telegram_message(f"Error crítico en el script GLPI: {str(e)}")
        except Exception:
            pass
        raise


def main_loop():
    """Bucle infinito que ejecuta las consultas cada hora (para uso con systemd)."""
    print("Iniciando sistema de reportes GLPI en modo continuo...")
    print(f"Ejecutando reportes cada 6 horas (21600 segundos)")
    print(f"Fecha/Hora inicial: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    while True:
        try:
            run_reports()
            print(f"Esperando 6 horas hasta la próxima ejecución...\n")
        except Exception as e:
            print(f"Error en el ciclo: {e}. Reintentando en 6 horas...\n")
        
        # Esperar 6 horas (21600 segundos)
        time.sleep(21600)


if __name__ == "__main__":
    import sys
    
    # Si se pasa el argumento --once, ejecutar una vez y terminar (para Cron)
    # Si no, ejecutar en modo loop (para systemd)
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        run_reports()
    else:
        main_loop()

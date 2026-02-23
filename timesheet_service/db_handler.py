import mysql.connector
import os

class DBHandler:
    def __init__(self):
        try:
            self.config = {
                "host": os.getenv("GLPI_DB_HOST"),
                "port": int(os.getenv("GLPI_DB_PORT", "3306")),
                "user": os.getenv("GLPI_DB_USER"),
                "password": os.getenv("GLPI_DB_PASSWORD"),
                "database": os.getenv("GLPI_DB_NAME"),
            }
        except Exception as e:
            raise Exception(f"Error cargando la configuracion de la base de datos: {str(e)}")

    def get_connection(self):
        return mysql.connector.connect(**self.config)

    def fetch_closed_tickets_range(self, days=7):
        # Obtener el correo del tecnico desde variables de entorno
        user_email = os.getenv("GLPI_USER_EMAIL")
        if not user_email:
            print("ADVERTENCIA: GLPI_USER_EMAIL no configurado.")

        query = """
        SELECT 
            gt.id AS ticket_id,
            gt.name AS ticket_title,
            gt.solvedate,
            gt.entities_id,
            ge.name AS entity_name,
            ge.completename AS entity_fullname,
            CONCAT(gu.realname, ' ', gu.firstname) AS technician_name,
            gu.id AS technician_id
        FROM glpi_tickets gt
        LEFT JOIN glpi_entities ge ON gt.entities_id = ge.id
        INNER JOIN glpi_tickets_users gtu ON gt.id = gtu.tickets_id AND gtu.type = 2
        INNER JOIN glpi_users gu ON gtu.users_id = gu.id
        INNER JOIN glpi_useremails gue ON gu.id = gue.users_id
        WHERE gt.is_deleted = 0
            AND gt.status > 4 
            AND gt.solvedate >= DATE_SUB(CURRENT_DATE(), INTERVAL %s DAY)
            AND gue.email = %s
        ORDER BY gt.solvedate ASC;
        """
        
        results = []
        conn = None
        cursor = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, (days, user_email))
            return cursor.fetchall()
        except Exception as e:
            print(f"Error fetching tickets range: {e}")
            return []
        finally:
            if cursor: cursor.close()
            if conn: conn.close()

    def fetch_closed_tickets_today(self):
        # Obtener el correo del tecnico desde variables de entorno
        user_email = os.getenv("GLPI_USER_EMAIL")
        if not user_email:
            print("ADVERTENCIA: GLPI_USER_EMAIL no configurado. La consulta podría fallar o traer datos incorrectos.")

        query = """
        SELECT 
            gt.id AS ticket_id,
            gt.name AS ticket_title,
            gt.solvedate,
            gt.entities_id,
            ge.name AS entity_name,
            ge.completename AS entity_fullname,
            CONCAT(gu.realname, ' ', gu.firstname) AS technician_name,
            gu.id AS technician_id
        FROM glpi_tickets gt
        LEFT JOIN glpi_entities ge ON gt.entities_id = ge.id
        -- Unir con tickets_users (type=2 es Tecnico asignado)
        INNER JOIN glpi_tickets_users gtu ON gt.id = gtu.tickets_id AND gtu.type = 2
        -- Unir con usuarios
        INNER JOIN glpi_users gu ON gtu.users_id = gu.id
        -- Unir con emails de usuarios para filtrar por correo
        INNER JOIN glpi_useremails gue ON gu.id = gue.users_id
        WHERE gt.is_deleted = 0
            AND gt.status > 4 -- Closed/Solved
            AND DATE(gt.solvedate) = CURRENT_DATE()
            AND gue.email = %s
        ORDER BY gt.solvedate ASC;
        """
        
        results = []
        conn = None
        cursor = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            # Pasar el parametro de email de forma segura
            cursor.execute(query, (user_email,))
            rows = cursor.fetchall()
            
            return rows
            
        except Exception as e:
            print(f"Error fetching tickets: {e}")
            return []
        finally:
            if cursor: cursor.close()
            if conn: conn.close()

if __name__ == "__main__":
    from dotenv import load_dotenv
    
    # Cargar variables de entorno para pruebas locales
    load_dotenv()
    
    print("\n" + "="*50)
    print("PROBADOR DE CONEXIÓN DB - TIMESHEET SERVICE")
    print("="*50)
    
    try:
        handler = DBHandler()
        
        # 1. Validar variables de entorno críticas
        missing_vars = [k for k, v in handler.config.items() if not v and k != "port"]
        if missing_vars:
            print(f"ADVERTENCIA: Faltan variables de entorno: {', '.join(missing_vars)}")
        
        # 2. Probar conexión
        print(f"Intentando conectar a: {handler.config['host']}:{handler.config['port']}...")
        print(f"Usuario: {handler.config['user']}")
        print(f"Base de datos: {handler.config['database']}")
        
        conn = handler.get_connection()
        if conn.is_connected():
            print("CONEXIÓN EXITOSA!")
            
            db_info = conn.server_info
            print(f"Version del servidor: {db_info}")
            
            # 3. Probar consulta de tickets
            user_email = os.getenv("GLPI_USER_EMAIL")
            print(f"\nBuscando tickets cerrados hoy para: {user_email}")
            
            tickets = handler.fetch_closed_tickets_today()
            
            if tickets:
                print(f"Se encontraron {len(tickets)} tickets:")
                print("-" * 30)
                for t in tickets:
                    print(f"ID: {t['ticket_id']} | {t['ticket_title'][:50]}...")
                    print(f"   - Entidad: {t['entity_name']} | Tecnico: {t['technician_name']}")
                print("-" * 30)
            else:
                print("No se encontraron tickets cerrados hoy.")
                print("Asegurate de que los tickets tengan 'Solved Date' con fecha de hoy y el tecnico coincida con el email.")
                
            conn.close()
            print("\nConexion cerrada correctamente.")
        else:
            print("ERROR: El driver no reportó errores pero la conexión no está activa.")
            
    except Exception as e:
        print("\nERROR CRITICO:")
        print(f"Detalle: {str(e)}")
        print("\nVerifica tus credenciales en el archivo .env")
    
    print("="*50 + "\n")
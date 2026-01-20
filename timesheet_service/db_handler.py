import mysql.connector
import os
from datetime import datetime

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

    def fetch_closed_tickets_today(self):
        query = """
        SELECT 
            gt.id AS ticket_id,
            gt.name AS ticket_title,
            gt.solvedate,
            CONCAT(gu.realname, ' ', gu.firstname) AS technician_name,
            gu.id AS technician_id
        FROM glpi_tickets gt
        INNER JOIN glpi_tickets_users gtu ON gt.id = gtu.tickets_id AND gtu.type = 2
        INNER JOIN glpi_users gu ON gtu.users_id = gu.id
        WHERE gt.is_deleted = 0
            AND gt.status = 6 -- Closed/Solved
            AND DATE(gt.solvedate) = CURRENT_DATE()
        ORDER BY gt.solvedate ASC;
        """
        
        results = []
        conn = None
        cursor = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query)
            rows = cursor.fetchall()
            
            # Grouping by technician (optional logic, but returning flat list is easier for iterator)
            return rows
            
        except Exception as e:
            print(f"Error fetching tickets: {e}")
            return []
        finally:
            if cursor: cursor.close()
            if conn: conn.close()
